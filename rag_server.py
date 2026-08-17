"""Small, unauthenticated document parsing and embedding HTTP API."""

from __future__ import annotations

import os
import logging
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))
RAG_DEVICE = os.getenv("RAG_DEVICE", "auto")

_embedder: Any = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_embedder()
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


def _convert(path: Path) -> str:
    """Convert a document to markdown text using Docling with OCR disabled.

    OCR is disabled to avoid the RapidOCR dependency on missing model data files
    when running as a PyInstaller-bundled executable. For most use cases (native
    PDF text, DOCX, PPTX, etc.) OCR is not needed.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pdf_pipeline_options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        do_code_enrichment=False,
        do_formula_enrichment=False,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pdf_pipeline_options,
            ),
        }
    )

    result = converter.convert(path)
    return result.document.export_to_markdown()


def _cleanup_temp_file(path: Path) -> None:
    for _ in range(10):
        try:
            path.unlink(missing_ok=True)
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
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "embedding"}


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
