#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 is required. Install python3.12 and try again." >&2
  exit 1
fi

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf build dist .venv-build
fi

python3.12 -m venv .venv-build
.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python -m PyInstaller --clean --noconfirm docling-serve.spec

echo "Built dist/docling-serve"
