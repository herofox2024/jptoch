"""QML 界面行为回归测试。

`qml_smoke_test.py` 只验证「文件能否加载」，无法捕捉界面逻辑缺陷。
本文件在 offscreen 模式下实例化真实的 QML 组件，覆盖已修复的界面行为：

1. 任务页输入框在 cfg.inp / cfg.out 被外部改写后必须同步（P0-1）
2. 状态页 TabBar 与 SwipeView 必须双向同步（P0-2）
3. Toast 必须挂在 Overlay 上，否则会被模态弹窗遮挡（P0-3）
4. 「停止」必须经过确认弹窗，且快捷键与按钮共用同一路径（P1-11）

实现说明：`test_model_prompt_presets.py` 与 `test_qml_config_schema.py` 会在
模块导入时创建 `QCoreApplication`。QML 引擎需要真正的 `QGuiApplication`，
复用 `QCoreApplication` 实例在创建窗口时会触发 access violation（已实测）。
因此涉及真实组件实例化的用例统一在**子进程**里执行，既保证在完整测试套件
中不被跳过，也不会污染主进程的 Qt 应用对象。

运行：
    python -m pytest tests/test_qml_ui_behavior.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = PROJECT_ROOT / "experimental" / "qml_v4"
QML_DIR = QML_ROOT / "qml"
RUNNER = Path(__file__).resolve().with_name("_qml_ui_probe_runner.py")


def _run_probe(case: str, timeout: int = 120) -> dict:
    """在独立进程里运行一个 QML 行为探针，返回其 JSON 结果。"""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), case],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    payload = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("PROBE_RESULT_JSON:"):
            payload = json.loads(line.split("PROBE_RESULT_JSON:", 1)[1])
            break
    assert payload is not None, (
        f"探针未返回结果 (case={case}, rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}"
    )
    return payload


# ---------------------------------------------------------------- 运行时行为


def test_task_page_fields_follow_external_config_changes():
    """外部改写 cfg.inp / cfg.out 后，输入框必须显示新值。

    回归点：修复前 TextField 使用 `text: cfg.inp` + `onTextChanged` 写回，
    用户输入一次后 Qt 会断开该绑定，之后拖放文件、载入任务历史等
    外部赋值再也刷不到界面，界面显示路径与实际翻译路径不一致。
    """
    result = _run_probe("task_page_path_sync")
    assert result["ok"], result.get("error")
    assert result["after_first_sync"] == ["E:/books/first.epub", "E:/books/first_zh.epub"]
    assert result["after_external_rewrite"] == [
        "E:/books/dropped.epub",
        "E:/books/dropped_zh.epub",
    ], "外部改写 cfg.inp/cfg.out 后输入框没有同步，说明绑定已失效"
    assert result["typed_writes_back"] == "E:/books/typed.epub"


def test_monitor_page_tab_and_swipe_stay_in_sync():
    """TabBar 点击与 SwipeView 滑动必须双向同步。

    回归点：修复前只有 `SwipeView.currentIndex: statusTabs.currentIndex`
    单向绑定。手势滑动会改写 SwipeView 索引并断开绑定，
    之后页签高亮不再跟随，点击页签也可能失效。
    """
    result = _run_probe("monitor_tab_swipe_sync")
    assert result["ok"], result.get("error")
    assert result["after_swipe"] == [3, 3], "滑动切换后页签高亮未跟随"
    assert result["after_tab_click"] == [1, 1], "点击页签后页面未切换"
    assert result["after_second_swipe"] == [4, 4], "第二次滑动后同步失效（绑定被断开）"


def test_stop_confirm_dialog_opens_and_blocks_direct_stop():
    """运行时验证：requestStop() 打开确认框，且不会立刻发出 stopRequested。"""
    result = _run_probe("stop_confirm")
    assert result["ok"], result.get("error")
    assert result["visible_before"] is False
    assert result["visible_after_request"] is True, "requestStop 应打开确认弹窗"
    assert result["stop_signals_while_confirming"] == 0, "确认弹窗打开时不应直接触发停止"
    assert result["visible_when_idle"] is False, "空闲状态不应弹出停止确认"


# ---------------------------------------------------------------- 静态断言


def test_toast_is_parented_to_overlay():
    """Toast 必须挂在 Overlay 上，否则会被模态 Dialog 遮挡。

    QtQuick.Controls 的 Overlay.overlay.z 约为 1000001，模态 Dialog 会被
    重新挂进 Overlay；Toast 若留在 contentItem 里（z 上限 9999）就永远被盖住。
    """
    source = (QML_DIR / "main.qml").read_text(encoding="utf-8")
    assert "parent: Overlay.overlay" in source, (
        "Toast 必须 parent 到 Overlay.overlay，否则弹窗内的提示会被遮罩层盖住"
    )
    assert "sourceComponent: Toast" not in source, (
        "不要再用 Loader 包裹 Toast：Loader 自身 z=0，会把 Toast 重新压到遮罩层下面"
    )


def test_stop_requires_confirmation_everywhere():
    """「停止」按钮与 Ctrl+Shift+X 快捷键都必须经过确认弹窗。"""
    panel = (QML_DIR / "components" / "TaskControlPanel.qml").read_text(encoding="utf-8")
    page = (QML_DIR / "pages" / "TaskPage.qml").read_text(encoding="utf-8")

    assert "stopConfirmDialog" in panel, "TaskControlPanel 缺少停止确认弹窗"
    assert "function requestStop()" in panel, "TaskControlPanel 缺少 requestStop() 统一入口"

    stop_button = panel.split('label: "停止"', 1)[1][:500]
    assert "stopConfirmDialog.open()" in stop_button, "停止按钮必须打开确认弹窗"
    assert "root.stopRequested()" not in stop_button, "停止按钮不得直接触发停止"

    trigger_stop = page.split("function triggerStop()", 1)[1][:500]
    assert "requestStop()" in trigger_stop, "快捷键 triggerStop 必须走确认流程"
    assert "stopTranslation()" not in trigger_stop, "快捷键不得绕过确认直接停止"
