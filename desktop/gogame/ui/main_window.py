"""Главное окно приложения."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QTextBrowser

from .dialogs import SettingsDialog
from .engine_manager import EngineManager
from .game_tab import GameTab
from .problems_tab import ProblemsTab

RULES_HTML = """
<h2>Правила го за 5 минут</h2>
<p><b>Цель игры</b> — окружить больше территории, чем соперник. Чёрные и белые ходят по очереди,
ставя по одному камню на пересечения линий. Первыми ходят чёрные. Камни не двигаются.</p>
<p><b>Дамэ</b> — свободные пункты рядом с камнем по линиям. Камни, стоящие рядом по линиям, образуют группу
с общими дамэ. Если занять все дамэ группы соперника, она снимается с доски, а камни становятся пленниками.</p>
<p><b>Запрещённые ходы.</b> Нельзя ставить камень туда, где у него (и его группы) не будет дамэ, если только
этот ход не снимает камни соперника. <b>Ко:</b> нельзя сразу отбить один камень, который только что снял один ваш
камень, — сначала нужно сходить в другом месте.</p>
<p><b>Жизнь и смерть.</b> Группа с двумя отдельными «глазами» (пустыми пунктами внутри) не может быть снята никогда.
Группа, которая не может сделать два глаза, считается мёртвой и в конце партии снимается при подсчёте.</p>
<p><b>Конец партии.</b> Когда оба игрока подряд пасуют, партия заканчивается. Мёртвые камни убираются,
затем считаются очки.</p>
<h3>Подсчёт очков</h3>
<p><b>Китайские правила (по площади):</b> очки = ваши камни на доске + пустые пункты, окружённые только вашими камнями.</p>
<p><b>Японские правила (по территории):</b> очки = окружённые пустые пункты + пленники (снятые и мёртвые камни
соперника). Камни на доске не считаются.</p>
<p><b>Коми</b> — очки, которые белые получают за то, что ходят вторыми: обычно 7,5 по китайским правилам
и 6,5 по японским. Половинка исключает ничью.</p>
<h3>Как учиться с этой программой</h3>
<ol>
<li>Пройдите задачи по порядку уровней: каждая объясняет, почему ход правильный и почему ошибки не работают.</li>
<li>Играйте на доске 9×9 с ботом «Новичок» или «Начинающий». Нажимайте «Подсказка», если не знаете, куда ходить.</li>
<li>После партии нажмите «Разобрать партию»: ИИ найдёт ошибки, покажет лучший ход и объяснит, что было не так.</li>
</ol>
<p>Всё работает на вашем компьютере, без интернета. ИИ KataGo — открытый движок го, скачивается один раз
в меню «Настройки».</p>
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Го — тренер")
        self.resize(1280, 820)
        self.em = EngineManager(self)

        self.tabs = QTabWidget()
        self.game_tab = GameTab(self.em)
        self.problems_tab = ProblemsTab(self.em)
        rules = QTextBrowser()
        rules.setHtml(RULES_HTML)
        self.tabs.addTab(self.game_tab, "Партия")
        self.tabs.addTab(self.problems_tab, "Задачи")
        self.tabs.addTab(rules, "Правила")
        self.setCentralWidget(self.tabs)
        self.em.ready_changed.connect(lambda _: self.problems_tab.refresh())

        m = self.menuBar().addMenu("Файл")
        a = QAction("Новая партия…", self, shortcut=QKeySequence.New, triggered=self.game_tab.new_game_dialog)
        m.addAction(a)
        m.addAction(QAction("Открыть партию (SGF)…", self, shortcut=QKeySequence.Open, triggered=self.open_sgf))
        m.addAction(QAction("Сохранить партию (SGF)…", self, shortcut=QKeySequence.Save, triggered=self.game_tab.save_sgf))
        m.addAction(QAction("Импорт задач из SGF…", self, triggered=self.import_problems))
        m.addSeparator()
        m.addAction(QAction("Выход", self, shortcut=QKeySequence.Quit, triggered=self.close))
        s = self.menuBar().addMenu("Настройки")
        s.addAction(QAction("ИИ KataGo…", self, triggered=self.open_settings))
        s.addAction(QAction("Перезапустить ИИ", self, triggered=self.em.start))
        h = self.menuBar().addMenu("Справка")
        h.addAction(QAction("О программе", self, triggered=self.about))

        self.statusBar().showMessage(self.em.status)
        self.em.status_changed.connect(self.statusBar().showMessage)
        self.em.start()

    def open_sgf(self) -> None:
        self.tabs.setCurrentWidget(self.game_tab)
        self.game_tab.open_sgf()

    def import_problems(self) -> None:
        self.tabs.setCurrentWidget(self.problems_tab)
        self.problems_tab.import_sgf()

    def open_settings(self) -> None:
        SettingsDialog(self.em, self).exec()

    def about(self) -> None:
        QMessageBox.about(self, "О программе",
                          "Го — тренер\n\nИгра в го с ботом, задачи по уровням и разбор ходов.\n"
                          "Бот и анализ: KataGo (https://github.com/lightvector/KataGo), лицензия MIT.\n"
                          "Работает без интернета.")

    def closeEvent(self, e):
        self.em.stop()
        super().closeEvent(e)
