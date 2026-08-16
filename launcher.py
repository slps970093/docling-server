"""PyInstaller entry point for the document embedding API."""

import os
import sys

# Force UTF-8 encoding on Windows to prevent cp950/cp1252 decoding errors
# when PyTorch internals read template files.
os.environ.setdefault("PYTHONUTF8", "1")

# Disable torch.compile (dynamo/inductor) in frozen (PyInstaller) builds.
# The inductor backend tries to import kernel templates that fail under
# PyInstaller's import system on Windows with non-UTF-8 locales.
os.environ.setdefault("TORCH_DISABLE_DYNAMO", "1")
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "rag_server:app",
        factory=False,
        host=os.getenv("RAG_HOST", "0.0.0.0"),
        port=int(os.getenv("RAG_PORT", "8000")),
    )
