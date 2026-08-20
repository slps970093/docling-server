"""
Bootstrap launcher for Docling Serve.

On first run:
  1. Creates a virtual environment at <install_dir>/venv
  2. Detects NVIDIA GPU availability
  3. Installs docling-serve and the appropriate torch build (CPU or CUDA)
  4. Delegates execution to the installed docling-serve entry point

Subsequent runs skip installation and go straight to step 4.

Environment variables:
  DOCLING_INSTALL_DIR   Override the default install directory
                        (default: ~/.local/share/docling-serve on Linux/Mac,
                                  %LOCALAPPDATA%\docling-serve on Windows)
  DOCLING_VERSION       Pin a specific docling-serve version (default: latest)
  DOCLING_FORCE_REINSTALL  Set to "1" to force reinstall
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCLING_VERSION = os.environ.get("DOCLING_VERSION", "")  # empty = latest
FORCE_REINSTALL = os.environ.get("DOCLING_FORCE_REINSTALL", "0") == "1"

PACKAGE_SPEC = f"docling-serve[ui]=={DOCLING_VERSION}" if DOCLING_VERSION else "docling-serve[ui]"

TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_CPU_PACKAGES = ["torch", "torchvision", "torchaudio"]
TORCH_CUDA_PACKAGES = [
    "torch",
    "torchvision",
    "torchaudio",
    "--index-url",
    TORCH_CUDA_INDEX,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_install_dir() -> Path:
    if "DOCLING_INSTALL_DIR" in os.environ:
        return Path(os.environ["DOCLING_INSTALL_DIR"])
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "docling-serve"


def get_python() -> str:
    """Return path to Python executable inside the venv."""
    install_dir = get_install_dir()
    if platform.system() == "Windows":
        return str(install_dir / "venv" / "Scripts" / "python.exe")
    return str(install_dir / "venv" / "bin" / "python")


def get_entry_point() -> str:
    """Return path to the docling-serve entry point inside the venv."""
    install_dir = get_install_dir()
    if platform.system() == "Windows":
        return str(install_dir / "venv" / "Scripts" / "docling-serve.exe")
    return str(install_dir / "venv" / "bin" / "docling-serve")


def has_nvidia_gpu() -> bool:
    """Return True if nvidia-smi is available and reports at least one GPU."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return False
    try:
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        return False


def run(*args, check: bool = True, **kwargs):
    """Run a subprocess command, streaming output to the terminal."""
    print(f"  $ {' '.join(str(a) for a in args)}")
    result = subprocess.run(list(args), check=check, **kwargs)
    return result


def create_venv(venv_path: Path):
    print(f"[docling-serve] Creating virtual environment at {venv_path} ...")
    run(sys.executable, "-m", "venv", str(venv_path))


def install_packages(python: str, cuda: bool):
    print(f"[docling-serve] Installing packages (CUDA={cuda}) ...")

    # Upgrade pip first
    run(python, "-m", "pip", "install", "--upgrade", "pip", "--quiet")

    # Install torch (CPU or CUDA)
    if cuda:
        print("[docling-serve] Installing PyTorch with CUDA support ...")
        run(python, "-m", "pip", "install", *TORCH_CUDA_PACKAGES, "--quiet")
    else:
        print("[docling-serve] Installing PyTorch (CPU) ...")
        run(python, "-m", "pip", "install", *TORCH_CPU_PACKAGES, "--quiet")

    # Install docling-serve
    print(f"[docling-serve] Installing {PACKAGE_SPEC} ...")
    run(python, "-m", "pip", "install", PACKAGE_SPEC, "--quiet")


def is_installed() -> bool:
    return Path(get_entry_point()).exists()


# ---------------------------------------------------------------------------
# Main bootstrap logic
# ---------------------------------------------------------------------------

def bootstrap():
    install_dir = get_install_dir()
    venv_path = install_dir / "venv"

    needs_install = FORCE_REINSTALL or not is_installed()

    if needs_install:
        print("[docling-serve] First run — setting up environment ...")
        install_dir.mkdir(parents=True, exist_ok=True)

        if FORCE_REINSTALL and venv_path.exists():
            print(f"[docling-serve] Removing existing venv for reinstall ...")
            shutil.rmtree(venv_path)

        create_venv(venv_path)

        cuda = has_nvidia_gpu()
        if cuda:
            print("[docling-serve] NVIDIA GPU detected — will install CUDA build.")
        else:
            print("[docling-serve] No GPU detected — will install CPU build.")

        install_packages(get_python(), cuda)
        print("[docling-serve] Setup complete.\n")

    # Hand off to the installed entry point, passing all original arguments
    entry = get_entry_point()
    if not Path(entry).exists():
        print(f"[docling-serve] ERROR: entry point not found: {entry}", file=sys.stderr)
        print("[docling-serve] Try setting DOCLING_FORCE_REINSTALL=1 and re-run.", file=sys.stderr)
        sys.exit(1)

    # Replace current process with docling-serve (exec-style)
    if platform.system() == "Windows":
        result = subprocess.run([entry] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        os.execv(entry, [entry] + sys.argv[1:])


if __name__ == "__main__":
    bootstrap()
