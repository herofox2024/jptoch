"""
EPUB 日译中工具 — PySide6 + QML 主入口
"""

import os
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


def _apply_windows_titlebar_theme(window, theme):
    """Keep the native Windows caption in sync with the QML theme."""
    if sys.platform != "win32" or window is None:
        return

    try:
        import ctypes

        theme_name = str(theme or "light").strip().lower()
        # 与 AppPalette 的背景/文字色保持一致，避免标题栏和窗口正文出现色差。
        colors = {
            "dark": ("#1c1c1e", "#f5f5f7"),
            "glass": ("#e8ecf2", "#1d1d1f"),
            "light": ("#f2f2f7", "#1d1d1f"),
        }
        caption_hex, text_hex = colors.get(theme_name, colors["light"])

        def _colorref(value):
            value = value.lstrip("#")
            red, green, blue = (
                int(value[0:2], 16),
                int(value[2:4], 16),
                int(value[4:6], 16),
            )
            return red | (green << 8) | (blue << 16)

        hwnd = int(window.winId())
        dwmapi = ctypes.windll.dwmapi
        is_dark = ctypes.c_int(1 if theme_name == "dark" else 0)
        dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(is_dark), ctypes.sizeof(is_dark)
        )

        # Windows 11 supports explicit caption/text colors. Older Windows
        # versions simply reject these attributes and retain the dark-mode hint.
        caption_color = ctypes.c_uint32(_colorref(caption_hex))
        text_color = ctypes.c_uint32(_colorref(text_hex))
        dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color)
        )
        dwmapi.DwmSetWindowAttribute(
            hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color)
        )
    except Exception:
        pass


def _choose_font_family(candidates, fallback="Microsoft YaHei UI"):
    from PySide6.QtGui import QFontDatabase

    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return fallback


def _read_startup_theme() -> str:
    """Read the saved theme before the config bridge exists.

    The splash screen is created before ConfigBridge loads the config file, so
    it cannot query QML. Read the same JSON directly and fall back to "light".
    """
    try:
        import json
        from pathlib import Path

        path = Path.home() / ".epub_translator" / "config.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        theme = str(data.get("theme") or "light").strip().lower()
        return theme if theme in {"light", "dark", "glass"} else "light"
    except Exception:
        return "light"


# 与 AppPalette 保持一致的三套主题配色，供启动画面使用。
_STARTUP_THEME_COLORS = {
    "light": {
        "card": "#ffffff",
        "card_border": "rgba(0, 0, 0, 30)",
        "title": "#1d1d1f",
        "hint": "#86868b",
        "track": "rgba(0, 122, 255, 26)",
        "chunk_start": "#007aff",
        "chunk_end": "#5ac8fa",
        "shadow": (0, 0, 0, 28),
    },
    "dark": {
        "card": "#2c2c2e",
        "card_border": "rgba(255, 255, 255, 36)",
        "title": "#f5f5f7",
        "hint": "#98989d",
        "track": "rgba(10, 132, 255, 46)",
        "chunk_start": "#0a84ff",
        "chunk_end": "#64d2ff",
        "shadow": (0, 0, 0, 120),
    },
    "glass": {
        "card": "rgba(255, 255, 255, 216)",
        "card_border": "rgba(255, 255, 255, 184)",
        "title": "#1d1d1f",
        "hint": "#6e6e73",
        "track": "rgba(0, 122, 255, 34)",
        "chunk_start": "#007aff",
        "chunk_end": "#5ac8fa",
        "shadow": (16, 24, 40, 46),
    },
}


def _create_startup_splash(app, theme: str = "light"):
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

    palette = _STARTUP_THEME_COLORS.get(theme, _STARTUP_THEME_COLORS["light"])

    splash = QWidget()
    splash.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.resize(460, 190)

    layout = QVBoxLayout(splash)
    layout.setContentsMargins(18, 18, 18, 18)

    card = QFrame(splash)
    card.setObjectName("startupCard")
    card.setStyleSheet(
        f"""
        QFrame#startupCard {{
            background: {palette["card"]};
            border: 1px solid {palette["card_border"]};
            border-radius: 18px;
        }}
        QLabel#startupTitle {{
            color: {palette["title"]};
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel#startupHint {{
            color: {palette["hint"]};
            font-size: 12px;
        }}
        QProgressBar {{
            min-height: 6px;
            max-height: 6px;
            border: 0;
            border-radius: 3px;
            background: {palette["track"]};
        }}
        QProgressBar::chunk {{
            border-radius: 3px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 {palette["chunk_start"]},
                                        stop:1 {palette["chunk_end"]});
        }}
        """
    )
    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(36)
    shadow.setOffset(0, 12)
    s = palette["shadow"]
    shadow.setColor(QColor(s[0], s[1], s[2], s[3]))
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
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from backend.app_info import APP_DISPLAY_NAME, APP_DISPLAY_VERSION, APP_NAME, APP_VERSION

    icon_path = _find_app_icon_path()

    QQuickStyle.setStyle("Material")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("epub-translator")
    if icon_path:
        app.setWindowIcon(QIcon(str(icon_path)))
    # 启动画面在 ConfigBridge 加载配置前就要显示，所以先直接读盘取主题。
    splash = _create_startup_splash(app, _read_startup_theme())

    _set_startup_status(app, splash, "正在初始化字体")
    # Apple 风格使用无衬线系统字体（macOS 为 SF Pro / PingFang SC）。
    # Windows 上没有 SF Pro，依次回退到最接近的人机工程学无衬线字体。
    sans_font = _choose_font_family(
        [
            "SF Pro Text",
            "SF Pro Display",
            "PingFang SC",
            "HarmonyOS Sans SC",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans SC",
            "Noto Sans CJK SC",
        ]
    )
    # 标题同样走无衬线，靠字重拉开层级，而不是换成宋体。
    title_font = _choose_font_family(
        [
            "SF Pro Display",
            "PingFang SC",
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
    from backend.update_bridge import UpdateBridge
    from backend.log_bridge import LogBridge
    from backend.local_model_bridge import LocalModelBridge

    config_bridge = ConfigBridge()
    translate_bridge = TranslateBridge()
    app.aboutToQuit.connect(translate_bridge.shutdown)
    glossary_bridge = GlossaryBridge()
    toast_bridge = ToastBridge()
    update_bridge = UpdateBridge()
    log_bridge = LogBridge()
    local_model_bridge = LocalModelBridge()
    app.aboutToQuit.connect(local_model_bridge.stopServer)

    _set_startup_status(app, splash, "正在加载主界面")

    engine = QQmlApplicationEngine()

    engine.warnings.connect(lambda msgs: [print(f"QML WARN: {m.toString()}", file=sys.stderr) for m in msgs])
    engine.objectCreationFailed.connect(lambda obj: print(f"QML FAIL: {obj.toString()}", file=sys.stderr))

    ctx = engine.rootContext()
    ctx.setContextProperty("ConfigBridge", config_bridge)
    ctx.setContextProperty("TranslateBridge", translate_bridge)
    ctx.setContextProperty("GlossaryBridge", glossary_bridge)
    ctx.setContextProperty("UpdateBridge", update_bridge)
    ctx.setContextProperty("LogBridge", log_bridge)
    ctx.setContextProperty("LocalModelBridge", local_model_bridge)
    ctx.setContextProperty("AppDir", str(EXPERIMENT_DIR))
    # 版本信息统一来自 backend.app_info，QML 侧不要再硬编码。
    ctx.setContextProperty("AppDisplayName", APP_DISPLAY_NAME)
    ctx.setContextProperty("AppDisplayVersion", APP_DISPLAY_VERSION)
    ctx.setContextProperty("AppVersion", APP_VERSION)
    # 「关于」弹窗展示的运行环境信息。
    from PySide6.QtCore import qVersion as _qt_version
    ctx.setContextProperty("AppPythonVersion", f"Python {sys.version.split()[0]}")
    ctx.setContextProperty("AppQtVersion", f"Qt {_qt_version()} / PySide6")
    ctx.setContextProperty("AppPlatform", sys.platform)
    ctx.setContextProperty("AppFontSans", sans_font)
    ctx.setContextProperty("AppFontTitle", title_font)
    # Keep the old QML property name for compatibility; this is now a stable title font.
    ctx.setContextProperty("AppFontSerif", title_font)
    ctx.setContextProperty("ToastBridge", toast_bridge)
    ui_metrics_debug = os.environ.get("QML_UI_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    ctx.setContextProperty("UiMetricsDebug", ui_metrics_debug)

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

    _apply_windows_titlebar_theme(root_window, config_bridge.theme)
    config_bridge._themeChanged.connect(
        lambda: _apply_windows_titlebar_theme(root_window, config_bridge.theme)
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
