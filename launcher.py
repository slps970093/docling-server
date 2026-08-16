"""PyInstaller entry point for the document embedding API."""

import os
import sys
from pathlib import Path

# Force UTF-8 encoding on Windows to prevent cp950/cp1252 decoding errors
# when PyTorch internals read template files.
os.environ.setdefault("PYTHONUTF8", "1")

# Disable torch.compile (dynamo/inductor) in frozen (PyInstaller) builds.
# The inductor backend tries to import kernel templates that fail under
# PyInstaller's import system on Windows with non-UTF-8 locales.
os.environ.setdefault("TORCH_DISABLE_DYNAMO", "1")
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

# ---------------------------------------------------------------------------
# Default model storage: <exe_dir>/huggingface
# Override with HF_HOME environment variable.
# ---------------------------------------------------------------------------
if getattr(sys, "frozen", False):
    _base_dir = Path(sys.executable).resolve().parent
else:
    _base_dir = Path(__file__).resolve().parent

_hf_home = Path(os.getenv("HF_HOME", str(_base_dir / "huggingface")))
os.environ.setdefault("HF_HOME", str(_hf_home))

_docling_artifacts = Path(
    os.getenv("DOCLING_SERVE_ARTIFACTS_PATH", str(_base_dir / "docling_models"))
)
os.environ.setdefault("DOCLING_SERVE_ARTIFACTS_PATH", str(_docling_artifacts))

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "rag_server:app",
        factory=False,
        host=os.getenv("RAG_HOST", "0.0.0.0"),
        port=int(os.getenv("RAG_PORT", "8000")),
    )
