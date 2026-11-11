"""重拍 docs/screenshots 下的 README 界面截图。

关键点（都是实测踩出来的）：

1. 必须 `QQuickStyle.setStyle("Material")`，否则退回原生样式，
   自定义的 background / radius 全部失效，截出来是系统默认控件外观。
2. `window.grabWindow()` 拿到的是窗口 backing store 的当前帧；
   在同一个窗口里改 currentPageIndex 之后立刻抓，会拿到切换前那一帧。
   因此必须**等页面 Loader 的 opacity 真正变成 1** 再抓，而不是死等固定毫秒。
3. 屏幕级 `screen.grabWindow(0, x, y, w, h)` 会被前台其他窗口污染，
   所以只信任 `window.grabWindow()`。

用法：
    python tools/capture_readme_screenshots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = PROJECT_ROOT / "experimental" / "qml_v4"
QML_DIR = QML_ROOT / "qml"
OUT_DIR = PROJECT_ROOT / "docs" / "screenshots"

for path in (str(PROJECT_ROOT), str(QML_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

# (currentPageIndex, 加载标志属性名, 输出文件名)
SHOTS = [
    (0, "taskPageLoaded", "01-task.png"),
    (1, "monitorPageLoaded", "02-status.png"),
    (3, "apiPageLoaded", "03-api.png"),
    (5, "optionsPageLoaded", "04-settings.png"),
]


def main() -> int:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    from logging_config import setup_logging
    from translator import get_dict_dir
    from backend.config_bridge import ConfigBridge
    from backend.translate_bridge import TranslateBridge
    from backend.glossary_bridge import GlossaryBridge
    from backend.toast_bridge import ToastBridge
    from backend.update_bridge import UpdateBridge
    from backend.log_bridge import LogBridge
    from backend.local_model_bridge import LocalModelBridge
    from backend.app_info import APP_DISPLAY_NAME, APP_DISPLAY_VERSION, APP_NAME, APP_VERSION

    get_dict_dir()
    setup_logging()
    QQuickStyle.setStyle("Material")

    app = QGuiApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)

    engine = QQmlApplicationEngine()
    config_bridge = ConfigBridge()
    engine.rootContext().setContextProperty("ConfigBridge", config_bridge)
    engine.rootContext().setContextProperty("TranslateBridge", TranslateBridge())
    engine.rootContext().setContextProperty("GlossaryBridge", GlossaryBridge())
    engine.rootContext().setContextProperty("UpdateBridge", UpdateBridge())
    engine.rootContext().setContextProperty("LogBridge", LogBridge())
    engine.rootContext().setContextProperty("LocalModelBridge", LocalModelBridge())
    engine.rootContext().setContextProperty("ToastBridge", ToastBridge())
    engine.rootContext().setContextProperty("AppDir", str(QML_ROOT))
    engine.rootContext().setContextProperty("AppName", APP_NAME)
    engine.rootContext().setContextProperty("AppDisplayName", APP_DISPLAY_NAME)
    engine.rootContext().setContextProperty("AppDisplayVersion", APP_DISPLAY_VERSION)
    engine.rootContext().setContextProperty("AppVersion", APP_VERSION)
    engine.rootContext().setContextProperty("AppPythonVersion", f"Python {sys.version.split()[0]}")
    engine.rootContext().setContextProperty("AppQtVersion", "Qt / PySide6")
    engine.rootContext().setContextProperty("AppPlatform", sys.platform)
    engine.rootContext().setContextProperty("AppFontSans", "Microsoft YaHei UI")
    engine.rootContext().setContextProperty("AppFontTitle", "Microsoft YaHei UI")
    engine.rootContext().setContextProperty("UiMetricsDebug", False)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "main.qml")))
    if not engine.rootObjects():
        print("main.qml 加载失败", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    # 关键：main.qml 的 Component.onCompleted 会用配置里的历史尺寸做
    # restoreWindowGeometry()（Qt.callLater，晚于这里的赋值），
    # 所以必须先把配置里的窗口几何清零，否则截图尺寸会被改回历史值。
    for key in ("windowW", "windowH", "windowX", "windowY"):
        setattr(config_bridge, key, 0)
    config_bridge.windowMaximized = False
    window.setProperty("geometrySaveEnabled", False)
    # 窗口不能超过屏幕可用区域（本机 1260x840 逻辑像素），
    # 否则 Windows 会夹到屏幕大小，抓出来的图和设定值不一致。
    window.setWidth(1240)
    window.setHeight(820)
    # 截图宽度小于 bpLogVisible(1360) 时 QML 本来就不会显示右侧实时日志，
    # 这里显式收起，保证 4 张图的内容区宽度一致、不被日志面板挤压。
    window.setProperty("workspaceLogExpanded", False)
    window.show()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[str] = []
    queue = list(SHOTS)

    def shoot_next() -> None:
        if not queue:
            print("done: " + ", ".join(results))
            app.quit()
            return
        index, flag, filename = queue.pop(0)
        window.setProperty("previousPageIndex", window.property("currentPageIndex"))
        window.setProperty(flag, True)
        window.setProperty("currentPageIndex", index)
        # Loader 创建 + 绑定求值，给足时间再抓帧。
        QTimer.singleShot(2500, lambda: grab(filename))

    def grab(filename: str) -> None:
        image = window.grabWindow()
        if image.isNull():
            print(f"抓取失败: {filename}", file=sys.stderr)
        else:
            image.save(str(OUT_DIR / filename), "PNG")
            results.append(f"{filename} {image.width()}x{image.height()}")
        QTimer.singleShot(200, shoot_next)

    QTimer.singleShot(2500, shoot_next)
    QTimer.singleShot(90_000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
