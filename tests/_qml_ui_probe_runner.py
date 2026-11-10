"""QML 界面行为探针运行器（由 tests/test_qml_ui_behavior.py 以子进程方式调用）。

每个用例创建一个独立的 QGuiApplication + QQmlEngine，实例化真实 QML 组件，
执行断言所需的最小交互，最后把结果以 `PROBE_RESULT_JSON:` 行输出。

独立进程的意义：其他测试模块会提前创建 QCoreApplication，而 QML 引擎需要
真正的 QGuiApplication；复用前者会在创建窗口时 access violation。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = PROJECT_ROOT / "experimental" / "qml_v4"
QML_DIR = QML_ROOT / "qml"


def _bootstrap_app():
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlEngine

    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    engine.addImportPath(str(QML_DIR / "components"))
    engine.rootContext().setContextProperty("AppDir", str(QML_ROOT))
    for name in (
        "TranslateBridge",
        "GlossaryBridge",
        "UpdateBridge",
        "LogBridge",
        "LocalModelBridge",
        "ToastBridge",
    ):
        engine.rootContext().setContextProperty(name, None)
    return app, engine


def _make_config():
    for path in (str(PROJECT_ROOT), str(QML_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    from backend.config_bridge import ConfigBridge

    return ConfigBridge()


# 必须保持 QQmlComponent 存活：组件被回收时，它 create() 出来的对象会一起销毁。
_LIVE_COMPONENTS = []


def _component(engine, relative_path: str):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / relative_path)))
    if component.status() != QQmlComponent.Ready:
        raise RuntimeError("; ".join(err.toString() for err in component.errors()))
    _LIVE_COMPONENTS.append(component)
    return component


def case_task_page_path_sync(app, engine):
    cfg = _make_config()
    cfg.inp = ""
    cfg.out = ""
    engine.rootContext().setContextProperty("ConfigBridge", cfg)

    page = _component(engine, "pages/TaskPage.qml").create()
    if page is None:
        raise RuntimeError("TaskPage 创建失败")
    result = {"ok": True}
    try:
        page.setProperty("cfg", cfg)
        app.processEvents()

        inp = page.findChild(object, "inpField")
        out = page.findChild(object, "outField")
        if inp is None or out is None:
            raise RuntimeError("TaskPage 未暴露 inpField/outField")

        cfg.inp = "E:/books/first.epub"
        cfg.out = "E:/books/first_zh.epub"
        app.processEvents()
        result["after_first_sync"] = [inp.property("text"), out.property("text")]

        cfg.inp = "E:/books/dropped.epub"
        cfg.out = "E:/books/dropped_zh.epub"
        app.processEvents()
        result["after_external_rewrite"] = [inp.property("text"), out.property("text")]

        inp.setProperty("text", "E:/books/typed.epub")
        app.processEvents()
        result["typed_writes_back"] = cfg.inp
    finally:
        page.deleteLater()
    return result


def case_monitor_tab_swipe_sync(app, engine):
    page = _component(engine, "pages/MonitorPage.qml").create()
    if page is None:
        raise RuntimeError("MonitorPage 创建失败")
    result = {"ok": True}
    try:
        tabs = page.findChild(object, "statusTabs")
        swipe = page.findChild(object, "statusSwipe")
        if tabs is None or swipe is None:
            raise RuntimeError("MonitorPage 未暴露 statusTabs/statusSwipe")

        swipe.setProperty("currentIndex", 3)
        app.processEvents()
        result["after_swipe"] = [tabs.property("currentIndex"), swipe.property("currentIndex")]

        tabs.setProperty("currentIndex", 1)
        app.processEvents()
        result["after_tab_click"] = [tabs.property("currentIndex"), swipe.property("currentIndex")]

        swipe.setProperty("currentIndex", 4)
        app.processEvents()
        result["after_second_swipe"] = [tabs.property("currentIndex"), swipe.property("currentIndex")]
    finally:
        page.deleteLater()
    return result


def case_stop_confirm(app, engine):
    from PySide6.QtCore import QMetaObject, QUrl, Qt
    from PySide6.QtQml import QQmlComponent

    cfg = _make_config()
    engine.rootContext().setContextProperty("ConfigBridge", cfg)

    wrapper = b"""
import QtQuick
import QtQuick.Controls
import "components"

ApplicationWindow {
    id: host
    visible: true
    width: 1000
    height: 700

    TaskControlPanel {
        objectName: "panelUnderTest"
        anchors.fill: parent
        busy: true
        readyToStart: true
    }
}
"""
    component = QQmlComponent(engine)
    component.setData(wrapper, QUrl.fromLocalFile(str(QML_DIR / "probe_wrapper.qml")))
    _LIVE_COMPONENTS.append(component)
    host = component.create()
    if host is None:
        raise RuntimeError("; ".join(err.toString() for err in component.errors()))

    result = {"ok": True}
    try:
        panel = host.findChild(object, "panelUnderTest")
        if panel is None:
            raise RuntimeError("未找到 TaskControlPanel")
        app.processEvents()

        result["visible_before"] = bool(panel.property("stopConfirmVisible"))

        fired = []
        panel.stopRequested.connect(lambda: fired.append(True))

        QMetaObject.invokeMethod(panel, "requestStop", Qt.DirectConnection)
        app.processEvents()

        result["visible_after_request"] = bool(panel.property("stopConfirmVisible"))
        result["stop_signals_while_confirming"] = len(fired)

        panel.setProperty("stopConfirmVisible", False)
        panel.setProperty("busy", False)
        QMetaObject.invokeMethod(panel, "requestStop", Qt.DirectConnection)
        app.processEvents()
        result["visible_when_idle"] = bool(panel.property("stopConfirmVisible"))
    finally:
        host.deleteLater()
    return result


CASES = {
    "task_page_path_sync": case_task_page_path_sync,
    "monitor_tab_swipe_sync": case_monitor_tab_swipe_sync,
    "stop_confirm": case_stop_confirm,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in CASES:
        print(f"usage: {argv[0]} <{'|'.join(CASES)}>", file=sys.stderr)
        return 2
    case = argv[1]
    try:
        app, engine = _bootstrap_app()
        result = CASES[case](app, engine)
    except Exception:
        result = {"ok": False, "error": traceback.format_exc(limit=6)}
    print("PROBE_RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
