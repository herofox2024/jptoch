"""Headless QML load smoke test for QML/V4.

Run from the repository root:
    python experimental/qml_v4/qml_smoke_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    app = QGuiApplication.instance() or QGuiApplication([])
    _ = app

    root = Path(__file__).resolve().parent / "qml"
    engine = QQmlEngine()
    engine.addImportPath(str(root))
    engine.addImportPath(str(root / "components"))

    files = sorted(path for path in root.rglob("*.qml") if path.is_file())
    failed = False

    for path in files:
        rel = path.relative_to(root).as_posix()
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        if component.status() == QQmlComponent.Error:
            failed = True
            print(f"ERROR {rel}")
            for err in component.errors():
                print(f"  {err.toString()}")
        else:
            print(f"OK {rel}")

    if failed:
        print("qml-smoke-failed")
        return 1

    print(f"qml-smoke-ok ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
