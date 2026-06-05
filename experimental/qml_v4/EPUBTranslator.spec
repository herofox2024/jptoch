# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for EPUB JP->ZH Translator (QML edition)
"""

import sys
from pathlib import Path

experiment_root = Path(SPECPATH).resolve()
project_root = experiment_root.parent.parent

a = Analysis(
    [str(experiment_root / "main.py")],
    pathex=[str(project_root), str(experiment_root)],
    binaries=[],
    datas=[
        (str(experiment_root / "qml"), "qml"),  # Include entire QML directory
        (str(experiment_root / "assets"), "assets"),
    ],
    hiddenimports=[
        "ebooklib",
        "bs4",
        "lxml",
        "requests",
        "translator",
        "epub_io",
        "glossary_store",
        "cache_store",
        "text_utils",
        "logging_config",
        "backend.config_bridge",
        "backend.translate_bridge",
        "backend.glossary_bridge",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "tkinterdnd2",
        "PyQt5",
        "qfluentwidgets",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EPUB日译中V4.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "app.ico") if (project_root / "assets" / "app.ico").exists() else None,
)
