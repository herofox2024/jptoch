"""静态检查配置的回归保护。

背景：
  项目刻意只启用能发现**真实缺陷**的规则（架构文档里写明：一旦加入纯风格规则，
  上千条排版告警会淹没真正的问题）。`B`（flake8-bugbear）属于前者，它抓的是：
  - B905：`zip()` 不写 `strict=` 时，两边长度不一致会**静默截断**
  - B008：默认参数里直接调用函数，导致定义时就求值并被所有调用共享
  - B904：`except` 里 `raise` 不写 `from`，丢掉原始异常链

  这几类问题此前确实在本仓库出现过（`translate_batch` 重构时就有一批 zip），
  因此把配置本身也纳入测试，避免日后被误删。
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _lint_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]


def test_bugbear_rules_are_enabled():
    """B 规则必须保持启用，否则上述三类缺陷会重新变得不可见。"""
    selected = _lint_config()["select"]
    assert "B" in selected, f"B 规则集被移除了，当前 select={selected}"


def test_formatting_only_rules_stay_disabled():
    """排版类规则（E501 行宽、E702 分号）必须保持关闭。

    架构文档写明：启用它们会引入上千条告警，把真实缺陷埋掉。
    """
    selected = set(_lint_config()["select"])
    for noisy in ("E501", "E702", "W291", "W293"):
        assert noisy not in selected, f"排版规则 {noisy} 不应启用"


def test_ignore_list_stays_empty():
    """ignore 必须为空：逐个屏蔽规则会静默掉真实缺陷。

    确实需要豁免时应使用带原因说明的 per-file-ignores。
    """
    assert _lint_config().get("ignore") == []


@pytest.mark.skipif(shutil.which("ruff") is None and not (ROOT / ".venv" / "Scripts" / "ruff.exe").exists(),
                    reason="ruff 不可用")
def test_repository_is_clean_under_bugbear(tmp_path: Path):
    """全仓库在 B 规则下必须零告警，保证基线不被新增债务污染。"""
    ruff = ROOT / ".venv" / "Scripts" / "ruff.exe"
    exe = str(ruff) if ruff.exists() else "ruff"
    proc = subprocess.run(
        [exe, "check", ".", "--select", "B", "--output-format", "concise"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, (
        "B 规则发现告警，请修复而不是屏蔽：\n" + (proc.stdout or proc.stderr)
    )
