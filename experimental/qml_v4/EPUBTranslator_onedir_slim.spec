# -*- mode: python ; coding: utf-8 -*-
"""
Slim PyInstaller onedir spec for EPUB JP->ZH Translator (QML edition).

The default PyInstaller PySide6 hooks collect many Qt modules that this QML app
does not import, such as WebEngine, 3D, charts, multimedia, and PDF. This spec
keeps the regular onedir layout but filters those unused Qt components before
COLLECT so the Inno installer can be much smaller.
"""

import re
import sys
from pathlib import Path

experiment_root = Path(SPECPATH).resolve()
project_root = experiment_root.parent.parent
app_icon = experiment_root / "assets" / "app_icon.ico"
fallback_icon = project_root / "assets" / "app.ico"
sys.path.insert(0, str(experiment_root))

from backend.app_info import APP_NAME, APP_VERSION

APP_EXE_BASENAME = f"AI日译中(EPUB)V{APP_VERSION}"
APP_COLLECT_NAME = f"{APP_EXE_BASENAME}_slim"


def _file_version_tuple(version):
    nums = [int(part) for part in re.findall(r"\d+", str(version or ""))]
    return tuple((nums + [0, 0, 0, 0])[:4])


def _write_version_info():
    filevers = _file_version_tuple(APP_VERSION)
    version_info_path = experiment_root / "_build_version_info.txt"
    version_info_path.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'EPUB Translator'),
          StringStruct('FileDescription', '{APP_NAME}'),
          StringStruct('FileVersion', '{APP_VERSION}'),
          StringStruct('InternalName', '{APP_EXE_BASENAME}'),
          StringStruct('OriginalFilename', '{APP_EXE_BASENAME}.exe'),
          StringStruct('ProductName', '{APP_NAME}'),
          StringStruct('ProductVersion', '{APP_VERSION}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return version_info_path


version_info_file = _write_version_info()


DROP_QT_PATTERNS = (
    "Qt63D",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Graphs",
    "Qt6Location",
    "Qt6Multimedia",
    "Qt6Pdf",
    "Qt6Positioning",
    "Qt6Quick3D",
    "Qt6RemoteObjects",
    "Qt6Scxml",
    "Qt6Sensors",
    "Qt6TextToSpeech",
    "Qt6WebChannel",
    "Qt6WebEngine",
    "Qt6WebSockets",
    "Qt6WebView",
    r"PySide6\qml\Qt3D",
    r"PySide6\qml\QtCharts",
    r"PySide6\qml\QtDataVisualization",
    r"PySide6\qml\QtGraphs",
    r"PySide6\qml\QtLocation",
    r"PySide6\qml\QtMultimedia",
    r"PySide6\qml\QtPositioning",
    r"PySide6\qml\QtQuick3D",
    r"PySide6\qml\QtRemoteObjects",
    r"PySide6\qml\QtScxml",
    r"PySide6\qml\QtSensors",
    r"PySide6\qml\QtTextToSpeech",
    r"PySide6\qml\QtWebChannel",
    r"PySide6\qml\QtWebEngine",
    r"PySide6\qml\QtWebSockets",
    r"PySide6\qml\QtWebView",
)


def _drop_unused_qt(entry):
    joined = "|".join(str(part) for part in entry[:2]).replace("/", "\\")
    return any(pattern in joined for pattern in DROP_QT_PATTERNS)


def _filter_qt_entries(entries):
    return [entry for entry in entries if not _drop_unused_qt(entry)]


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
        "backend.pipeline",
        "backend.service_container",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "tkinterdnd2",
        "PyQt5",
        "qfluentwidgets",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaQuick",
        "PySide6.QtPdf",
        "PySide6.QtPdfQuick",
        "PySide6.QtPositioning",
        "PySide6.QtQuick3D",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtTextToSpeech",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtWebView",
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
    name=APP_EXE_BASENAME,
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
    version=str(version_info_file),
)

coll = COLLECT(
    exe,
    _filter_qt_entries(a.binaries),
    _filter_qt_entries(a.datas),
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_COLLECT_NAME,
)
