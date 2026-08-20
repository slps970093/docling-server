# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the bootstrap launcher.

This only packages the bootstrap logic — no torch, no transformers, no CUDA.
The resulting binary is a few MB and builds in under a minute.
All heavy dependencies are downloaded at first launch by the bootstrap itself.
"""

analysis = Analysis(
    ["bootstrap.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

# Single-file binary — bootstrap is tiny so onefile is fine
exe = EXE(
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
