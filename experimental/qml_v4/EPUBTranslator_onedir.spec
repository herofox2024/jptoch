# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller onedir spec for EPUB JP->ZH Translator (QML edition).

This build keeps Qt/PySide files as separate files so Inno Setup can compress
the whole directory more effectively than wrapping an already-packed onefile exe.
"""

from pathlib import Path

experiment_root = Path(SPECPATH).resolve()
project_root = experiment_root.parent.parent
app_icon = experiment_root / "assets" / "app_icon.ico"
fallback_icon = project_root / "assets" / "app.ico"

a = Analysis(
    [str(experiment_root / "main.py")],
    pathex=[str(project_root), str(experiment_root)],
    binaries=[],
    datas=[
        (str(experiment_root / "qml"), "qml"),
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
        "style_detector",
        "logging_config",
        "backend.app_info",
        "backend.config_bridge",
        "backend.translate_bridge",
        "backend.glossary_bridge",
        "backend.toast_bridge",
        "backend.update_bridge",
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
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI日译中(EPUB)V4.1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon) if app_icon.exists() else (str(fallback_icon) if fallback_icon.exists() else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI日译中(EPUB)V4.1_onedir",
)
