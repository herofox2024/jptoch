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


def _find_app_icon_path():
    preferred_paths = [
        EXPERIMENT_DIR / "assets" / "logo.png",
        EXPERIMENT_DIR / "assets" / "logo.jpg",
        EXPERIMENT_DIR / "assets" / "app_icon.png",
        PROJECT_ROOT / "assets" / "640f4205-4cfe-4d03-b20e-7f32ea5a34c0.png",
        PROJECT_ROOT / "assets" / "logo.png",
        PROJECT_ROOT / "assets" / "logo.jpg",
    ]
    if sys.platform == "win32":
        preferred_paths.insert(0, EXPERIMENT_DIR / "assets" / "logo.ico")

    for path in preferred_paths:
        if path.exists():
            return path
    return None


def _set_windows_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        app_id = "EPUBTranslator.AIJPZH.V4"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _choose_font_family(candidates, fallback="Microsoft YaHei UI"):
    from PySide6.QtGui import QFontDatabase

    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return fallback


def _create_startup_splash(app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (
        QWidget,
        QVBoxLayout,
        QLabel,
        QProgressBar,
        QFrame,
        QGraphicsDropShadowEffect,
    )

    splash = QWidget()
    splash.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.resize(460, 190)

    layout = QVBoxLayout(splash)
    layout.setContentsMargins(18, 18, 18, 18)

    card = QFrame(splash)
    card.setObjectName("startupCard")
    card.setStyleSheet(
        """
        QFrame#startupCard {
            background: #fffaf1;
            border: 1px solid #ded1bd;
            border-radius: 24px;
        }
        QLabel#startupTitle {
            color: #1f302d;
            font-size: 20px;
            font-weight: 700;
        }
        QLabel#startupHint {
            color: #6a746f;
            font-size: 12px;
        }
        QProgressBar {
            min-height: 8px;
            max-height: 8px;
            border: 0;
            border-radius: 4px;
            background: #d7ece5;
        }
        QProgressBar::chunk {
            border-radius: 4px;
            background: #2f6f5f;
        }
        """
    )
    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(30)
    shadow.setOffset(0, 10)
    shadow.setColor(QColor(23, 48, 43, 48))
    card.setGraphicsEffect(shadow)

    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(28, 26, 28, 24)
    card_layout.setSpacing(12)

    title = QLabel("AI日译中软件正在启动中...")
    title.setObjectName("startupTitle")
    title.setAlignment(Qt.AlignCenter)

    hint = QLabel("正在加载界面与翻译组件")
    hint.setObjectName("startupHint")
    hint.setAlignment(Qt.AlignCenter)

    progress = QProgressBar()
    progress.setRange(0, 0)
    progress.setTextVisible(False)

    card_layout.addStretch(1)
    card_layout.addWidget(title)
    card_layout.addWidget(hint)
    card_layout.addWidget(progress)
    card_layout.addStretch(1)
    layout.addWidget(card)

    screen = app.primaryScreen()
    if screen:
        geometry = screen.availableGeometry()
        splash.move(
            geometry.center().x() - splash.width() // 2,
            geometry.center().y() - splash.height() // 2,
        )

    splash.status_label = hint
    splash.show()
    app.processEvents()
    return splash


def _set_startup_status(app, splash, text):
    if splash is None:
        return
    label = getattr(splash, "status_label", None)
    if label is not None:
        label.setText(text)
    app.processEvents()


def main():
    _set_windows_app_user_model_id()

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine

    icon_path = _find_app_icon_path()

    app = QApplication(sys.argv)
    app.setApplicationName("AI日译中（EPUB）")
    app.setApplicationDisplayName("AI日译中（EPUB）V4.1")
    app.setOrganizationName("epub-translator")
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))
    splash = _create_startup_splash(app)

    _set_startup_status(app, splash, "正在初始化字体")
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

    _set_startup_status(app, splash, "正在初始化日志")
    from logging_config import setup_logging
    setup_logging()

    _set_startup_status(app, splash, "正在加载数据目录")
    from translator import get_dict_dir
    get_dict_dir()

    _set_startup_status(app, splash, "正在加载配置与桥接器")
    from backend.service_container import get_container
    container = get_container()
    container.init_light()
    from backend.config_bridge import ConfigBridge
    from backend.translate_bridge import TranslateBridge
    from backend.glossary_bridge import GlossaryBridge
    from backend.toast_bridge import ToastBridge

    config_bridge = ConfigBridge()
    translate_bridge = TranslateBridge()
    glossary_bridge = GlossaryBridge()

    _set_startup_status(app, splash, "正在加载主界面")

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
    ctx.setContextProperty("ToastBridge", ToastBridge())

    qml_dir = EXPERIMENT_DIR / "qml"
    qml_file = qml_dir / "main.qml"
    if not qml_file.exists():
        print(f"FATAL: QML entry not found: {qml_file}", file=sys.stderr)
        sys.exit(1)

    engine.load(QUrl.fromLocalFile(str(qml_file)))

    if not engine.rootObjects():
        print("FATAL: Failed to load QML. See errors above.", file=sys.stderr)
        sys.exit(1)

    root_window = engine.rootObjects()[0]
    if icon_path:
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)
        root_window.setIcon(icon)

    _set_startup_status(app, splash, "启动完成")
    splash.close()
    splash.deleteLater()
    root_window.show()
    app.processEvents()

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
