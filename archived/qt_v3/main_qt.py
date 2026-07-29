"""Archived Qt V3.2.1 fallback entry point.

Run from the repository root with:
    python archived/qt_v3/main_qt.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtWidgets import QApplication

from logging_config import setup_logging
from translator import get_dict_dir
from archived.qt_v3.ui.qt_app import QtAppWindow


def main():
    setup_logging()
    get_dict_dir()
    app = QApplication([])
    window = QtAppWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
