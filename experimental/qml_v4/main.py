"""
EPUB 日译中工具 — PySide6 + QML 主入口
"""

import sys
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(EXPERIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_DIR))

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine

from logging_config import setup_logging
from translator import get_dict_dir
from backend.config_bridge import ConfigBridge
from backend.translate_bridge import TranslateBridge
from backend.glossary_bridge import GlossaryBridge


def _find_logo_path():
    for path in (
        EXPERIMENT_DIR / "assets" / "logo.png",
        EXPERIMENT_DIR / "assets" / "logo.jpg",
        PROJECT_ROOT / "assets" / "logo.png",
        PROJECT_ROOT / "assets" / "logo.jpg",
    ):
        if path.exists():
            return path
    return None


def _choose_font_family(candidates, fallback="Microsoft YaHei UI"):
    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return fallback


def main():
    setup_logging()
    get_dict_dir()

    app = QApplication(sys.argv)
    app.setApplicationName("EPUB 日译中")
    app.setApplicationDisplayName("EPUB 日译中 V4.0")
    app.setOrganizationName("epub-translator")

    sans_font = _choose_font_family(
        [
            "HarmonyOS Sans SC",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans SC",
            "Noto Sans CJK SC",
            "LXGW WenKai Screen",
            "霞鹜文楷屏幕阅读版",
        ]
    )
    title_font = _choose_font_family(
        [
            "HarmonyOS Sans SC",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans SC",
            "Noto Sans CJK SC",
        ],
        fallback=sans_font,
    )
    app.setFont(QFont(sans_font, 10))

    config_bridge = ConfigBridge()
    translate_bridge = TranslateBridge()
    glossary_bridge = GlossaryBridge()

    logo_path = _find_logo_path()
    if logo_path:
        app.setWindowIcon(QIcon(str(logo_path)))

    engine = QQmlApplicationEngine()

    engine.warnings.connect(lambda msgs: [print(f"QML WARN: {m.toString()}", file=sys.stderr) for m in msgs])
    engine.objectCreationFailed.connect(lambda obj: print(f"QML FAIL: {obj.toString()}", file=sys.stderr))

    ctx = engine.rootContext()
    ctx.setContextProperty("ConfigBridge", config_bridge)
    ctx.setContextProperty("TranslateBridge", translate_bridge)
    ctx.setContextProperty("GlossaryBridge", glossary_bridge)
    ctx.setContextProperty("AppDir", str(EXPERIMENT_DIR))
    ctx.setContextProperty("AppFontSans", sans_font)
    ctx.setContextProperty("AppFontTitle", title_font)
    # Keep the old QML property name for compatibility; this is now a stable title font.
    ctx.setContextProperty("AppFontSerif", title_font)

    qml_dir = EXPERIMENT_DIR / "qml"
    qml_file = qml_dir / "main.qml"
    if not qml_file.exists():
        print(f"FATAL: QML entry not found: {qml_file}", file=sys.stderr)
        sys.exit(1)

    engine.load(QUrl.fromLocalFile(str(qml_file)))

    if not engine.rootObjects():
        print("FATAL: Failed to load QML. See errors above.", file=sys.stderr)
        sys.exit(1)

    # Windows dark titlebar for the QML window.
    try:
        import ctypes
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        window = engine.rootObjects()[0]
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(window.winId()),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1 if config_bridge.theme == "dark" else 0)),
            ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
