"""Диалоги: новая партия и настройки ИИ."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..board import BLACK, WHITE
from ..engine.bot import DEFAULT_LEVEL, LEVELS
from ..engine.katago import katago_install_dir, project_root


@dataclass
class GameSettings:
    size: int
    rules: str
    komi: float
    handicap: int
    human_color: int  # BLACK, WHITE или 0 — оба игрока люди
    level: int


DEFAULT_KOMI = {"chinese": 7.5, "japanese": 6.5}


class NewGameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая партия")
        s = QSettings()
        form = QFormLayout()

        self.size = QComboBox()
        for n in (9, 13, 19):
            self.size.addItem(f"{n}×{n}", n)
        self.size.setCurrentIndex([9, 13, 19].index(int(s.value("game/size", 9))))
        form.addRow("Размер доски:", self.size)

        self.rules = QComboBox()
        self.rules.addItem("Китайские (по площади)", "chinese")
        self.rules.addItem("Японские (по территории)", "japanese")
        self.rules.setCurrentIndex(0 if s.value("game/rules", "chinese") == "chinese" else 1)
        form.addRow("Правила подсчёта:", self.rules)
        rules_help = QLabel("Китайские: считаются свои камни на доске и окружённые пункты.\n"
                            "Японские: окружённые пункты и взятые в плен камни соперника.\n"
                            "Результат почти всегда совпадает, отличие — в тонкостях конца партии.")
        rules_help.setWordWrap(True)
        rules_help.setStyleSheet("color: gray;")
        form.addRow(rules_help)

        self.komi = QDoubleSpinBox()
        self.komi.setRange(-50, 50)
        self.komi.setSingleStep(0.5)
        self.komi.setDecimals(1)
        self.komi.setValue(float(s.value("game/komi", DEFAULT_KOMI[self.rules.currentData()])))
        form.addRow("Коми (очки белым):", self.komi)
        self.rules.currentIndexChanged.connect(lambda: self.komi.setValue(DEFAULT_KOMI[self.rules.currentData()]))

        self.handicap = QSpinBox()
        self.handicap.setRange(0, 9)
        self.handicap.setValue(int(s.value("game/handicap", 0)))
        self.handicap.setSpecialValueText("нет")
        form.addRow("Фора (камни чёрным):", self.handicap)

        self.color = QComboBox()
        self.color.addItem("Чёрными (хожу первым)", BLACK)
        self.color.addItem("Белыми", WHITE)
        self.color.addItem("Вдвоём на одном компьютере", 0)
        self.color.setCurrentIndex(int(s.value("game/color_idx", 0)))
        form.addRow("Я играю:", self.color)

        self.level = QComboBox()
        for i, lv in enumerate(LEVELS):
            self.level.addItem(lv.name, i)
            self.level.setItemData(i, lv.description, Qt.ToolTipRole)
        self.level.setCurrentIndex(int(s.value("game/level", DEFAULT_LEVEL)))
        self.level_desc = QLabel()
        self.level_desc.setWordWrap(True)
        self.level_desc.setStyleSheet("color: gray;")
        self.level.currentIndexChanged.connect(lambda i: self.level_desc.setText(LEVELS[i].description))
        self.level_desc.setText(LEVELS[self.level.currentIndex()].description)
        form.addRow("Сила бота:", self.level)
        form.addRow(self.level_desc)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Начать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def result_settings(self) -> GameSettings:
        s = QSettings()
        s.setValue("game/size", self.size.currentData())
        s.setValue("game/rules", self.rules.currentData())
        s.setValue("game/komi", self.komi.value())
        s.setValue("game/handicap", self.handicap.value())
        s.setValue("game/color_idx", self.color.currentIndex())
        s.setValue("game/level", self.level.currentIndex())
        return GameSettings(self.size.currentData(), self.rules.currentData(), self.komi.value(),
                            self.handicap.value(), self.color.currentData(), self.level.currentIndex())


class SettingsDialog(QDialog):
    _progress = Signal(str, int, int)
    _finished = Signal(str)

    def __init__(self, engine_manager, parent=None):
        super().__init__(parent)
        self.em = engine_manager
        self.setWindowTitle("Настройки ИИ (KataGo)")
        self.setMinimumWidth(560)
        s = QSettings()
        exe, model = self.em.paths()

        intro = QLabel(
            "KataGo — сильный открытый движок го. Он играет за бота и разбирает ходы. "
            "Работает прямо на вашем компьютере, без интернета и без платных запросов.\n"
            "Нажмите «Скачать KataGo» — один раз загрузится около 120 МБ.")
        intro.setWordWrap(True)

        self.exe = QLineEdit(str(exe or ""))
        self.model = QLineEdit(str(model or ""))
        b1 = QPushButton("Выбрать…")
        b1.clicked.connect(lambda: self._pick(self.exe, "Программа KataGo (katago*)"))
        b2 = QPushButton("Выбрать…")
        b2.clicked.connect(lambda: self._pick(self.model, "Нейросеть (*.bin.gz *.txt.gz)"))

        self.threads = QSpinBox()
        self.threads.setRange(0, 64)
        self.threads.setSpecialValueText("авто")
        self.threads.setValue(int(s.value("katago/threads", 0) or 0))

        self.review_visits = QSpinBox()
        self.review_visits.setRange(10, 5000)
        self.review_visits.setValue(int(s.value("katago/review_visits", 100)))
        self.review_visits.setToolTip("Больше — точнее разбор, но дольше. На слабом компьютере ставьте 30–60.")

        self.variant = QComboBox()
        from ..engine.download import VARIANTS
        for k, v in VARIANTS.items():
            self.variant.addItem(v, k)
        self.download_btn = QPushButton("Скачать KataGo")
        self.download_btn.clicked.connect(self._download)
        self.bar = QProgressBar()
        self.bar.hide()
        self.dl_status = QLabel()
        self.dl_status.setWordWrap(True)

        form = QFormLayout()
        row1 = QHBoxLayout(); row1.addWidget(self.exe); row1.addWidget(b1)
        row2 = QHBoxLayout(); row2.addWidget(self.model); row2.addWidget(b2)
        w1 = QWidget(); w1.setLayout(row1)
        w2 = QWidget(); w2.setLayout(row2)
        form.addRow("Программа KataGo:", w1)
        form.addRow("Нейросеть:", w2)
        form.addRow("Потоков процессора:", self.threads)
        form.addRow("Глубина разбора партии:", self.review_visits)
        dl = QHBoxLayout(); dl.addWidget(self.variant, 1); dl.addWidget(self.download_btn)
        w3 = QWidget(); w3.setLayout(dl)
        form.addRow("Автоустановка:", w3)
        form.addRow(self.bar)
        form.addRow(self.dl_status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить и перезапустить ИИ")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(form)
        lay.addWidget(buttons)

        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    def _pick(self, edit: QLineEdit, flt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выбор файла", edit.text() or str(project_root()), flt + ";;Все файлы (*)")
        if path:
            edit.setText(path)

    def _download(self) -> None:
        from ..engine.download import install
        self.download_btn.setEnabled(False)
        self.bar.show()
        variant = self.variant.currentData()
        target = katago_install_dir()

        def run():
            try:
                exe, model = install(target, variant, lambda w, d, t: self._progress.emit(w, d, t))
                self._finished.emit(f"ok|{exe}|{model}")
            except Exception as e:
                self._finished.emit(f"err|{e}")

        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, what: str, done: int, total: int) -> None:
        self.dl_status.setText(f"Скачиваю {what}: {done // (1 << 20)} МБ" + (f" из {total // (1 << 20)} МБ" if total else ""))
        if total:
            self.bar.setRange(0, 100)
            self.bar.setValue(done * 100 // total)
        else:
            self.bar.setRange(0, 0)

    def _on_finished(self, msg: str) -> None:
        self.download_btn.setEnabled(True)
        self.bar.hide()
        parts = msg.split("|")
        if parts[0] == "ok":
            self.exe.setText(parts[1])
            self.model.setText(parts[2])
            self.dl_status.setText("Готово! Нажмите «Сохранить и перезапустить ИИ».")
        else:
            self.dl_status.setText(f"Не получилось скачать: {parts[1]}\n"
                                   "Можно скачать вручную: https://github.com/lightvector/KataGo/releases "
                                   "и указать файлы выше.")

    def _save(self) -> None:
        s = QSettings()
        s.setValue("katago/exe", self.exe.text().strip())
        s.setValue("katago/model", self.model.text().strip())
        s.setValue("katago/threads", self.threads.value())
        s.setValue("katago/review_visits", self.review_visits.value())
        if self.exe.text().strip() and not Path(self.exe.text().strip()).exists():
            QMessageBox.warning(self, "KataGo", "Файл программы не найден.")
            return
        self.accept()
        self.em.start()
