"""Точка входа: python -m gogame"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("GoTrainer")
    app.setApplicationName("GoTrainer")
    app.setStyle("Fusion")
    app.setDesktopFileName("gotrainer")  # связывает окно со значком из gotrainer.desktop в Linux
    icon = Path(__file__).with_name("icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    app.aboutToQuit.connect(w.em.stop)
    w.show()
    shot = os.environ.get("GOTRAINER_SELFTEST")
    if shot:  # проверка собранной программы: снимок окна и выход (используется при сборке)
        def done() -> None:
            w.grab().save(shot)
            print(f"selftest ok: {len(w.problems_tab.problems)} задач, снимок {shot}", flush=True)
            app.quit()
        QTimer.singleShot(2000, done)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
