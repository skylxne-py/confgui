#!/usr/bin/env python3
import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Config GUI")
    window = MainWindow()
    window.show()

    if len(sys.argv) > 1:
        window.load_file(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
