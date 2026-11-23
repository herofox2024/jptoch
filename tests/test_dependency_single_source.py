"""依赖声明的单一来源约束。

背景（真实缺陷）：
  仓库根 requirements.txt 曾长期是**归档版 Qt V3 的依赖**（PyQt5 + Fluent-Widgets
  + tkinterdnd2），而主力版本 QML/V4 用的是 PySide6。README 里两种安装方式并列，
  但只有一份是对的——照根目录那份装，会得到一套与主力版本完全不匹配的 Qt 绑定，
  且 PySide6 与 PyQt5 同时存在于同一环境时行为难以预测。

  更根本的问题是 pyproject.toml 当时没有 [project] 段，不声明任何依赖，
  于是「依赖到底在哪里」没有权威答案。

本测试固化修复后的约定：
  1. pyproject.toml [project].dependencies 是唯一权威来源
  2. 两份 requirements.txt 必须与它逐条一致（允许顺序无关、允许注释）
  3. PyQt5 绝不出现在默认依赖里，只能留在可选分组
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
ROOT_REQUIREMENTS = ROOT / "requirements.txt"
QML_REQUIREMENTS = ROOT / "experimental" / "qml_v4" / "requirements.txt"


def _normalize(requirement: str) -> str:
    """把依赖声明归一成可比较的形式（去空格、小写、去版本空白）。"""
    return re.sub(r"\s+", "", requirement).lower()


def _parse_requirements_file(path: Path) -> list[str]:
    """读取 requirements.txt 中的有效依赖条目，忽略注释与空行。"""
    assert path.is_file(), f"缺少依赖文件: {path}"
    entries: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # 允许行内注释
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        entries.append(line)
    return entries


def _project_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_declares_dependencies():
    """pyproject.toml 必须声明 [project].dependencies，否则依赖没有权威来源。"""
    project = _project_config().get("project")
    assert project, "pyproject.toml 缺少 [project] 段：依赖没有权威来源"
    assert project.get("dependencies"), "[project].dependencies 不能为空"
    assert project.get("requires-python"), "[project].requires-python 应当声明"


def test_requirements_files_match_pyproject():
    """两份 requirements.txt 必须与 pyproject.toml 声明的依赖逐条一致。"""
    authoritative = {
        _normalize(dep) for dep in _project_config()["project"]["dependencies"]
    }

    for path in (ROOT_REQUIREMENTS, QML_REQUIREMENTS):
        declared = {_normalize(entry) for entry in _parse_requirements_file(path)}
        assert declared == authoritative, (
            f"{path.relative_to(ROOT)} 与 pyproject.toml [project].dependencies 不一致：\n"
            f"  仅在 pyproject.toml: {sorted(authoritative - declared)}\n"
            f"  仅在 {path.name}: {sorted(declared - authoritative)}"
        )


def test_requirements_files_agree_with_each_other():
    """根目录与 QML 版的 requirements.txt 不能再各自维护出两套依赖。"""
    root_entries = {_normalize(e) for e in _parse_requirements_file(ROOT_REQUIREMENTS)}
    qml_entries = {_normalize(e) for e in _parse_requirements_file(QML_REQUIREMENTS)}
    assert root_entries == qml_entries, (
        "两份 requirements.txt 不一致：\n"
        f"  仅根目录: {sorted(root_entries - qml_entries)}\n"
        f"  仅 QML/V4: {sorted(qml_entries - root_entries)}"
    )


def test_legacy_qt_bindings_are_optional_only():
    """PyQt5 等归档版依赖不得混入默认依赖。

    回归点：根 requirements.txt 曾把 PyQt5 + PyQt-Fluent-Widgets 当作默认依赖，
    与主力版本的 PySide6 冲突。它们只能出现在 optional-dependencies 里。
    """
    config = _project_config()
    default_deps = {_normalize(d) for d in config["project"]["dependencies"]}

    legacy_markers = ("pyqt5", "pyqt-fluent-widgets", "tkinterdnd2")
    for marker in legacy_markers:
        assert not any(marker in dep for dep in default_deps), (
            f"归档版依赖 {marker} 不得出现在 [project].dependencies 中"
        )

    legacy_group = {
        _normalize(d)
        for d in config["project"]["optional-dependencies"].get("legacy-qt", [])
    }
    assert legacy_group, "缺少 [project.optional-dependencies].legacy-qt 分组"
    for marker in ("pyqt5", "pyqt-fluent-widgets", "tkinterdnd2"):
        assert any(marker in dep for dep in legacy_group), (
            f"legacy-qt 分组缺少 {marker}"
        )


def test_pyside6_is_the_declared_qt_binding():
    """主力版本用 PySide6，必须在默认依赖中声明。"""
    default_deps = {
        _normalize(d) for d in _project_config()["project"]["dependencies"]
    }
    assert any("pyside6" in dep for dep in default_deps), (
        "QML/V4 依赖 PySide6，应在 [project].dependencies 中声明"
    )
