"""
Bootstrap launcher for Docling Serve.

On first run:
  1. Locates a system Python interpreter
  2. Creates a virtual environment at <exe_dir>/venv
  3. Detects NVIDIA GPU via nvidia-smi
  4. Installs the appropriate torch build (CPU or CUDA) + docling-serve
  5. Delegates execution to the installed entry point

Subsequent runs skip straight to step 5.

Environment variables:
  DOCLING_VERSION          Pin a specific docling-serve version (default: latest)
  DOCLING_FORCE_REINSTALL  Set to "1" to wipe venv and reinstall
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

DOCLING_VERSION = os.environ.get("DOCLING_VERSION", "")
FORCE_REINSTALL = os.environ.get("DOCLING_FORCE_REINSTALL", "0") == "1"

PACKAGE_SPEC = (
    f"docling-serve[ui]=={DOCLING_VERSION}" if DOCLING_VERSION else "docling-serve[ui]"
)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX   = platform.system() == "Linux"

# PyTorch CUDA index — same URL works for both Windows and Linux
# pip selects the correct wheel (win_amd64 vs manylinux) automatically
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"

TORCH_BASE_PACKAGES = ["torch", "torchvision", "torchaudio"]

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_install_dir() -> Path:
    """Venv lives next to the executable (or next to this script in dev mode)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_venv_python() -> Path:
    d = get_install_dir() / "venv"
    if IS_WINDOWS:
        return d / "Scripts" / "python.exe"
    return d / "bin" / "python"


def get_entry_point() -> Path:
    d = get_install_dir() / "venv"
    if IS_WINDOWS:
        return d / "Scripts" / "docling-serve.exe"
    return d / "bin" / "docling-serve"

# ---------------------------------------------------------------------------
# System Python detection (needed because sys.executable is the frozen binary)
# ---------------------------------------------------------------------------

def find_system_python() -> str:
    """
    Return a real Python 3 interpreter path.
    In a PyInstaller frozen build sys.executable points to the bootstrap binary,
    not a Python interpreter, so we search PATH instead.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    candidates = (
        ["python3.12", "python3.11", "python3.10", "python3", "python"]
        if not IS_WINDOWS
        else ["python", "python3", "py"]
    )
    for name in candidates:
        path = shutil.which(name)
        if path:
            # Make sure it's actually Python 3
            try:
                r = subprocess.run(
                    [path, "-c", "import sys; assert sys.version_info >= (3,10)"],
                    capture_output=True, timeout=5,
                )
                if r.returncode == 0:
                    return path
            except Exception:
                continue

    raise RuntimeError(
        "Python 3.10+ not found in PATH.\n"
        "Please install Python from https://www.python.org/downloads/ and re-run."
    )

# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------

def find_nvidia_smi() -> str | None:
    path = shutil.which("nvidia-smi")
    if path:
        return path
    # Windows: nvidia-smi is often not in PATH
    if IS_WINDOWS:
        fixed = r"C:\Windows\System32\nvidia-smi.exe"
        if os.path.exists(fixed):
            return fixed
    return None


def has_nvidia_gpu() -> bool:
    smi = find_nvidia_smi()
    if smi is None:
        return False
    try:
        r = subprocess.run(
            [smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and r.stdout.strip() != ""
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Install helpers
# ---------------------------------------------------------------------------

def run_cmd(*args, **kwargs):
    print(f"  $ {' '.join(str(a) for a in args)}")
    subprocess.run(list(args), check=True, **kwargs)


def create_venv():
    venv_path = get_install_dir() / "venv"
    print(f"[docling-serve] Creating venv at {venv_path} ...")
    run_cmd(find_system_python(), "-m", "venv", str(venv_path))


def install_packages(cuda: bool):
    python = str(get_venv_python())
    print(f"[docling-serve] Installing packages  (platform={platform.system()}, cuda={cuda}) ...")

    run_cmd(python, "-m", "pip", "install", "--upgrade", "pip", "--quiet")

    if cuda:
        print("[docling-serve] Installing PyTorch (CUDA) ...")
        run_cmd(
            python, "-m", "pip", "install",
            *TORCH_BASE_PACKAGES,
            "--index-url", TORCH_CUDA_INDEX,
            "--quiet",
        )
    else:
        print("[docling-serve] Installing PyTorch (CPU) ...")
        run_cmd(python, "-m", "pip", "install", *TORCH_BASE_PACKAGES, "--quiet")

    print(f"[docling-serve] Installing {PACKAGE_SPEC} ...")
    run_cmd(python, "-m", "pip", "install", PACKAGE_SPEC, "--quiet")

# ---------------------------------------------------------------------------
# Bootstrap entry point
# ---------------------------------------------------------------------------

def bootstrap():
    needs_install = FORCE_REINSTALL or not get_entry_point().exists()

    if needs_install:
        print("[docling-serve] First run — setting up environment ...")
        install_dir = get_install_dir()
        venv_path = install_dir / "venv"

        if FORCE_REINSTALL and venv_path.exists():
            print("[docling-serve] Removing existing venv ...")
            shutil.rmtree(venv_path)

        create_venv()

        cuda = has_nvidia_gpu()
        print(
            f"[docling-serve] GPU detected: {cuda} "
            f"({'CUDA build' if cuda else 'CPU build'})"
        )
        install_packages(cuda)
        print("[docling-serve] Setup complete.\n")

    entry = get_entry_point()
    if not entry.exists():
        print(f"[docling-serve] ERROR: entry point not found: {entry}", file=sys.stderr)
        print("[docling-serve] Run with DOCLING_FORCE_REINSTALL=1 to reinstall.", file=sys.stderr)
        sys.exit(1)

    # Hand off — Windows can't exec() so use subprocess; Linux uses execv
    if IS_WINDOWS:
        result = subprocess.run([str(entry)] + sys.argv[1:])
        sys.exit(result.returncode)
    else:
        os.execv(str(entry), [str(entry)] + sys.argv[1:])


if __name__ == "__main__":
    bootstrap()
