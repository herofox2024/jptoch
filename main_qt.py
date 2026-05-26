from PyQt5.QtWidgets import QApplication

from logging_config import setup_logging
from translator import get_dict_dir
from ui.qt_app import QtAppWindow


def main():
    setup_logging()
    get_dict_dir()
    app = QApplication([])
    window = QtAppWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()

