"""Small, unauthenticated document parsing and embedding HTTP API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

import task_store

EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
RAG_DEVICE = os.getenv("RAG_DEVICE", "auto")

_embedder: Any = None
_converter: Any = None


def _detect_device() -> str:
    import torch
    if RAG_DEVICE != "auto":
        return RAG_DEVICE
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_embedder() -> None:
    global _embedder
    if _embedder is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = _detect_device()
        logger.info("Torch version: %s, CUDA available: %s", torch.__version__, torch.cuda.is_available())
        logger.info("Loading embedding model: %s (device=%s)", EMBEDDING_MODEL, device)
        _embedder = SentenceTransformer(EMBEDDING_MODEL, device=device)
        logger.info("Embedding model loaded: %s on %s", EMBEDDING_MODEL, device)


logger = logging.getLogger("docling-rag")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if getattr(sys, "frozen", False):
    _base_dir = Path(sys.executable).resolve().parent
else:
    _base_dir = Path(__file__).resolve().parent


def _preload_docling_models() -> None:
    global _converter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    logger.info("Pre-loading Docling models...")
    pdf_pipeline_options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        do_code_enrichment=False,
        do_formula_enrichment=False,
    )
    _converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pdf_pipeline_options,
            ),
        }
    )

    # Warm-up: 用空白 PDF 強制 pipeline 真正初始化
    import tempfile

    # 最小合法 PDF（單頁空白）
    _MINIMAL_PDF = (
        b"%PDF-1.0\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 72 72]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n183\n%%EOF\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(_MINIMAL_PDF)
        tmp_path = Path(tmp.name)

    try:
        _converter.convert(tmp_path)
    except Exception:
        pass  # 空白 PDF 可能無文字可擷取，忽略即可
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info("Docling models loaded (pipeline warm-up complete)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_embedder()
    _preload_docling_models()
    db_path = _base_dir / "tasks.db"
    task_store.init(db_path)
    logger.info("Task store initialized: %s", db_path)
    _start_webhook_worker()
    yield


app = FastAPI(title="Docling RAG API", version="1.2.0", lifespan=lifespan)


@app.middleware("http")
async def request_logging(request: Request, call_next: Any) -> Any:
    started = time.perf_counter()
    logger.info("Request started: %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Request failed: %s %s", request.method, request.url.path)
        raise
    elapsed = time.perf_counter() - started
    logger.info(
        "Request finished: %s %s -> %s (%.2fs)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


def _vectors(texts: list[str]) -> list[list[float]]:
    return _embedder.encode(texts, normalize_embeddings=True).tolist()


def _chunks(text: str) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    return [text[start : start + CHUNK_SIZE] for start in range(0, len(text), step)]


_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".jsonl", ".xml", ".html", ".htm", ".log", ".ini", ".cfg", ".yml", ".yaml", ".toml"}


def _convert(path: Path) -> str:
    """Convert a document to markdown text using the shared Docling converter.

    Plain text files are read directly without Docling to avoid unnecessary
    model loading and pipeline initialization.
    """
    if path.suffix.lower() in _TEXT_EXTENSIONS:
        logger.info("Reading plain text file directly: %s", path.name)
        return path.read_text(encoding="utf-8", errors="ignore")
    result = _converter.convert(path)
    return result.document.export_to_markdown()


def _cleanup_temp_file(path: Path) -> None:
    for _ in range(10):
        try:
            if path.exists():
                path.unlink()
                logger.info("Temp file deleted: %s", path)
            return
        except PermissionError:
            time.sleep(0.5)
    logger.warning("Could not remove temporary file: %s", path)


# ---------------------------------------------------------------------------
# Models for the /rag/import endpoint
# ---------------------------------------------------------------------------


class ImportItem(BaseModel):
    """A single chunk with its text. The server will compute the embedding."""

    text: str


class ImportRequest(BaseModel):
    """Request body for /rag/import.

    The caller provides pre-chunked text items. The server embeds them and
    returns the same structure as /rag/embed so the calling application can
    store results in its vector DB.
    """

    filename: str = "imported"
    items: list[ImportItem]


# ---------------------------------------------------------------------------
# Models for the /rag/embed/text endpoint
# ---------------------------------------------------------------------------


class TextEmbedRequest(BaseModel):
    """Request body for /rag/embed/text.

    Send one or more text strings, get embeddings back directly.
    No file parsing, no Docling, just chunk + embed.
    """

    texts: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "embedding"}


@app.post("/rag/embed/text")
async def embed_text(body: TextEmbedRequest) -> dict[str, Any]:
    """Send plain text(s), get embeddings back directly.

    No file parsing, no Docling. Just chunk each text and embed.

    Request:
        {"texts": ["第一段文字", "第二段文字"]}

    Response:
        {"model": "...", "dimensions": 512, "items": [{"id": "uuid", "text": "...", "embedding": [...]}]}
    """
    if not body.texts:
        raise HTTPException(status_code=422, detail="No texts provided")

    all_items: list[dict[str, Any]] = []
    for text in body.texts:
        chunks = _chunks(text)
        if not chunks:
            continue
        vectors = _vectors(chunks)
        for chunk, vector in zip(chunks, vectors):
            all_items.append({"id": str(uuid4()), "text": chunk, "embedding": vector})

    if not all_items:
        raise HTTPException(status_code=422, detail="All texts are empty")

    logger.info("Embedded %d texts -> %d chunks", len(body.texts), len(all_items))
    return {
        "model": EMBEDDING_MODEL,
        "dimensions": len(all_items[0]["embedding"]),
        "items": all_items,
    }


@app.post("/rag/embed")
async def embed(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a document, extract text, chunk, embed, and return vectors."""
    suffix = Path(file.filename or "document").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
        temporary.write(await file.read())
        path = Path(temporary.name)
    await file.close()
    try:
        logger.info("Converting document: %s", file.filename)
        chunks = _chunks(_convert(path))
        if not chunks:
            raise HTTPException(status_code=422, detail="No text was extracted")
        logger.info("Extracted %d chunks from %s", len(chunks), file.filename)
        vectors = _vectors(chunks)
        logger.info("Created %d embeddings", len(vectors))
        return {
            "filename": file.filename or "document",
            "model": EMBEDDING_MODEL,
            "dimensions": len(vectors[0]),
            "items": [
                {"id": str(uuid4()), "text": chunk, "embedding": vector}
                for chunk, vector in zip(chunks, vectors)
            ],
        }
    finally:
        _cleanup_temp_file(path)


@app.post("/rag/import")
async def import_vectors(body: ImportRequest) -> dict[str, Any]:
    """Accept pre-chunked text, embed them, return vectors for external DB import.

    This endpoint lets the calling application supply text chunks directly
    (e.g. from its own parser or database) and receive embeddings back,
    without needing to upload a file for Docling to parse.

    Request body example:
        {
            "filename": "manual.pdf",
            "items": [
                {"text": "First chunk of text..."},
                {"text": "Second chunk of text..."}
            ]
        }

    Response matches /rag/embed format so the caller can use the same
    vector DB import logic.
    """
    if not body.items:
        raise HTTPException(status_code=422, detail="No items provided")

    texts = [item.text for item in body.items]
    texts = [t for t in texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=422, detail="All items are empty")

    logger.info("Importing %d text chunks for embedding", len(texts))
    vectors = _vectors(texts)
    logger.info("Created %d embeddings for import", len(vectors))

    return {
        "filename": body.filename,
        "model": EMBEDDING_MODEL,
        "dimensions": len(vectors[0]),
        "items": [
            {"id": str(uuid4()), "text": text, "embedding": vector}
            for text, vector in zip(texts, vectors)
        ],
    }


# ---------------------------------------------------------------------------
# Models for the /rag/embed/async endpoint
# ---------------------------------------------------------------------------


class AsyncEmbedRequest(BaseModel):
    """Request body for /rag/embed/async with URL input."""

    url: str
    webhook_url: str | None = None
    webhook_secret: str | None = None


# ---------------------------------------------------------------------------
# Webhook helper
# ---------------------------------------------------------------------------

WEBHOOK_MAX_RETRIES = 3
WEBHOOK_DELAYS = [5, 30, 60]


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def _deliver_webhook(task: dict[str, Any]) -> bool:
    webhook_url = task.get("webhook_url")
    if not webhook_url:
        return True

    payload = {
        "task_id": task["task_id"],
        "status": task["status"],
        "filename": task["filename"],
    }
    if task["status"] == "completed" and task.get("result"):
        payload.update(json.loads(task["result"]))
    elif task["status"] == "failed":
        payload["error"] = task.get("error", "unknown")

    payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}

    secret = task.get("webhook_secret")
    if secret:
        headers["X-Webhook-Secret"] = _sign_payload(payload_bytes, secret)

    try:
        resp = httpx.post(webhook_url, content=payload_bytes, headers=headers, timeout=30)
        resp.raise_for_status()
        logger.info("Webhook delivered for task %s -> %s", task["task_id"], webhook_url)
        return True
    except Exception:
        logger.exception("Webhook delivery failed for task %s", task["task_id"])
        return False


def _webhook_worker() -> None:
    while True:
        try:
            tasks = task_store.pending_webhook_tasks()
            for task in tasks:
                if _deliver_webhook(task):
                    continue
                count = task_store.increment_retry(task["task_id"])
                if count >= WEBHOOK_MAX_RETRIES:
                    logger.warning("Webhook retry limit reached for task %s", task["task_id"])
        except Exception:
            logger.exception("Webhook worker error")
        time.sleep(5)


def _start_webhook_worker() -> None:
    t = threading.Thread(target=_webhook_worker, daemon=True)
    t.start()
    logger.info("Webhook worker started")


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------


def _process_task(task_id: str, file_path: Path, filename: str) -> None:
    try:
        logger.info("[task %s] Converting document: %s", task_id, filename)
        chunks = _chunks(_convert(file_path))
        if not chunks:
            task_store.fail_task(task_id, "No text was extracted")
            logger.warning("[task %s] No text extracted from %s", task_id, filename)
            return
        logger.info("[task %s] Extracted %d chunks", task_id, len(chunks))
        vectors = _vectors(chunks)
        logger.info("[task %s] Created %d embeddings", task_id, len(vectors))
        result = {
            "filename": filename,
            "model": EMBEDDING_MODEL,
            "dimensions": len(vectors[0]),
            "items": [
                {"id": str(uuid4()), "text": chunk, "embedding": vector}
                for chunk, vector in zip(chunks, vectors)
            ],
        }
        task_store.complete_task(task_id, result)
        logger.info("[task %s] Completed", task_id)
    except Exception as exc:
        task_store.fail_task(task_id, str(exc))
        logger.exception("[task %s] Failed", task_id)
    finally:
        _cleanup_temp_file(file_path)


def _process_task_from_url(task_id: str, url: str, filename: str) -> None:
    path: Path | None = None
    try:
        logger.info("[task %s] Downloading from URL: %s", task_id, url)
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
        suffix = Path(url.split("?")[0]).suffix or Path(filename).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(resp.content)
            path = Path(tmp.name)
        if not filename or filename == "document":
            filename = Path(url.split("?")[0]).name or f"download{suffix}"
        _process_task(task_id, path, filename)
    except Exception as exc:
        task_store.fail_task(task_id, f"Download failed: {exc}")
        logger.exception("[task %s] URL download failed: %s", task_id, url)
    finally:
        if path and path.exists():
            _cleanup_temp_file(path)


# ---------------------------------------------------------------------------
# Async endpoints
# ---------------------------------------------------------------------------


@app.post("/rag/embed/async")
async def embed_async(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    webhook_url: str | None = Form(None),
    webhook_secret: str | None = Form(None),
) -> dict[str, Any]:
    """Submit a document for async processing.

    Accept either a file upload or a URL. The server returns a task_id
    immediately and processes the document in the background. When finished,
    the result is delivered to webhook_url (if provided).

    The caller can also poll GET /rag/tasks/{task_id} to check status.
    """
    if file is None and url is None:
        raise HTTPException(status_code=422, detail="Provide either 'file' or 'url'")

    task_id = str(uuid4())
    filename = file.filename if file else Path(url.split("?")[0]).name or "document"

    task_store.create_task(
        task_id=task_id,
        filename=filename,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
    )
    logger.info("Task created: %s (filename=%s)", task_id, filename)

    if file is not None:
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
            temporary.write(await file.read())
            path = Path(temporary.name)
        await file.close()
        t = threading.Thread(target=_process_task, args=(task_id, path, filename), daemon=True)
    else:
        t = threading.Thread(target=_process_task_from_url, args=(task_id, url, filename), daemon=True)

    t.start()
    return {"task_id": task_id, "status": "processing"}


@app.get("/rag/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    """Query task status and result."""
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    response: dict[str, Any] = {
        "task_id": task["task_id"],
        "status": task["status"],
        "filename": task["filename"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
    if task["status"] == "completed" and task.get("result"):
        response["result"] = json.loads(task["result"])
    elif task["status"] == "failed":
        response["error"] = task.get("error")
    return response
