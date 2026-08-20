# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for Docling Serve.

The package uses dynamic imports and ships native libraries through PyTorch,
so collect the package data and submodules explicitly.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules


datas = []
binaries = []
hiddenimports = [
    "docling_serve.__main__",
    "docling_serve.app",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

for package in (
    "docling_serve",
    "docling",
    "docling_core",
    "docling_parse",
    "docling_jobkit",
    "sentence_transformers",
    "transformers",
    "scipy",
    "sklearn",
    "safehttpx",
    "groovy",
    "rapidocr",
    "omegaconf",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

import importlib.util, os as _os
_dp_spec = importlib.util.find_spec("docling_parse")
if _dp_spec and _dp_spec.origin:
    _dp_dir = _os.path.dirname(_dp_spec.origin)
    _dp_res = _os.path.join(_dp_dir, "pdf_resources")
    if _os.path.isdir(_dp_res):
        datas.append((_dp_res, _os.path.join("docling_parse", "pdf_resources")))

hiddenimports += collect_submodules("torch")
hiddenimports += collect_submodules("transformers")
hiddenimports += collect_submodules("scipy")
hiddenimports += collect_submodules("sklearn")
hiddenimports += collect_submodules("rapidocr")
hiddenimports += [
    "rag_server",
    "task_store",
    "scipy._external.array_api_compat.numpy.fft",
]

analysis = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook_encoding.py"],
    excludes=["pytest", "IPython"],
    noarchive=False,
    optimize=0,
)

# Strip CUDA libraries — CI runners and most deployments are CPU-only.
# These .so files can easily add 3-5 GB to the binary for zero benefit.
CUDA_PATTERNS = (
    "libcuda",
    "libcudart",
    "libcublas",
    "libcurand",
    "libcufft",
    "libcusolver",
    "libcusparse",
    "libcudnn",
    "libnccl",
    "libnvrtc",
    "libnvToolsExt",
    "libcaffe2_nvrtc",
    "libtorch_cuda",
    "libc10_cuda",
)

analysis.binaries = [
    (name, path, typecode)
    for name, path, typecode in analysis.binaries
    if not any(pat in name for pat in CUDA_PATTERNS)
]

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="docling-serve",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
