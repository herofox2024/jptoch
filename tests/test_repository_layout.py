from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_ui_entry_points_are_archived():
    assert not (ROOT / "app.py").exists()
    assert not (ROOT / "main_qt.py").exists()
    assert (ROOT / "archived" / "tk_v1" / "app.py").is_file()
    assert (ROOT / "archived" / "qt_v3" / "main_qt.py").is_file()
    assert (ROOT / "archived" / "qt_v3" / "ui" / "qt_app.py").is_file()


def test_release_workflow_builds_only_qml_v4():
    workflow = (ROOT / ".github" / "workflows" / "release-qml-v4.yml").read_text(encoding="utf-8")
    assert "experimental\\qml_v4\\EPUBTranslator_onedir_slim.spec" in workflow
    assert "archived/" not in workflow
    assert "archived\\" not in workflow


def test_archived_entry_points_bootstrap_shared_project_root():
    for relative_path in (
        "archived/qt_v3/main_qt.py",
        "archived/tk_v1/app.py",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
        assert "Path(__file__).resolve().parents[2]" in source
        assert "sys.path.insert(0, str(PROJECT_ROOT))" in source
