"""Вкладка «Партия»: игра с ботом, подсказки, подсчёт и разбор партии."""

from __future__ import annotations

import html
import random
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

from ..board import BLACK, WHITE, Game, IllegalMove, from_gtp, to_gtp
from ..engine.bot import LEVELS, choose_from_analysis
from ..engine.katago import Analysis
from ..engine.simple_bot import choose_move
from ..explain import MoveReview, offline_explanation, review_move, tactical_facts, pv_text, points_word, points_gen
from ..scoring import dead_from_ownership, score, toggle_dead_group
from ..sgf import load_sgf, save_sgf
from .board_widget import BoardWidget
from .dialogs import GameSettings, NewGameDialog
from .graph import WinrateGraph

GREEN = QColor("#1aa34a")
RED = QColor("#d93025")
BLUE = QColor("#1a5fd0")


def text_to_html(text: str) -> str:
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return ""
    out = [f"<p><b>{html.escape(lines[0])}</b></p>"]
    for l in lines[1:]:
        if ": " in l and l.index(": ") < 30:
            head, rest = l.split(": ", 1)
            out.append(f"<p><b>{html.escape(head)}:</b> {html.escape(rest)}</p>")
        else:
            out.append(f"<p>{html.escape(l)}</p>")
    return "".join(out)


class GameTab(QWidget):
    def __init__(self, engine_manager, parent=None):
        super().__init__(parent)
        self.em = engine_manager
        self.settings = GameSettings(9, "chinese", 7.5, 0, BLACK, 2)
        self.game = Game(9, 7.5, "chinese")
        self.view = 0
        self.scoring = False
        self.dead: set = set()
        self.result: Optional[str] = None
        self.bot_thinking = False
        self.bot_query: Optional[str] = None
        self.analyses: dict[int, Analysis] = {}
        self.reviews: dict[int, MoveReview] = {}
        self.review_query: Optional[str] = None
        self.rng = random.Random()

        self.board = BoardWidget()
        self.board.clicked.connect(self.on_click)

        # --- правая панель
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.engine_status = QLabel(self.em.status)
        self.engine_status.setWordWrap(True)
        self.engine_status.setStyleSheet("color: gray; font-size: 11px;")
        self.em.status_changed.connect(self.engine_status.setText)
        self.em.ready_changed.connect(lambda _: self.refresh())

        self.btn_new = QPushButton("Новая партия")
        self.btn_pass = QPushButton("Пас")
        self.btn_undo = QPushButton("Отменить ход")
        self.btn_resign = QPushButton("Сдаться")
        self.btn_hint = QPushButton("Подсказка")
        self.btn_explain = QPushButton("Объяснить ход")
        self.btn_review = QPushButton("Разобрать партию")
        self.btn_score = QPushButton("Подсчитать очки")
        self.btn_new.clicked.connect(self.new_game_dialog)
        self.btn_pass.clicked.connect(self.human_pass)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_resign.clicked.connect(self.resign)
        self.btn_hint.clicked.connect(self.hint)
        self.btn_explain.clicked.connect(self.explain_current)
        self.btn_review.clicked.connect(self.review_game)
        self.btn_score.clicked.connect(self.score_button)
        self.btn_hint.setToolTip("ИИ покажет лучший ход и объяснит, почему он хорош")
        self.btn_explain.setToolTip("Разбор показанного на доске хода: хорош ли он, что было лучше и почему")
        self.btn_review.setToolTip("ИИ проверит все ходы партии и найдёт ошибки")

        grid = QGridLayout()
        grid.addWidget(self.btn_new, 0, 0)
        grid.addWidget(self.btn_pass, 0, 1)
        grid.addWidget(self.btn_undo, 1, 0)
        grid.addWidget(self.btn_resign, 1, 1)
        grid.addWidget(self.btn_hint, 2, 0)
        grid.addWidget(self.btn_explain, 2, 1)
        grid.addWidget(self.btn_review, 3, 0)
        grid.addWidget(self.btn_score, 3, 1)

        nav = QHBoxLayout()
        for text, fn, tip in (("⏮", lambda: self.goto(0), "В начало"),
                              ("◀", lambda: self.goto(self.view - 1), "Назад (←)"),
                              ("▶", lambda: self.goto(self.view + 1), "Вперёд (→)"),
                              ("⏭", lambda: self.goto(len(self.game.moves)), "К последнему ходу")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            nav.addWidget(b)
        self.move_label = QLabel()
        self.show_owner = QCheckBox("Карта территории")
        self.show_owner.setToolTip("Показать, чьи области на доске по оценке ИИ")
        self.show_owner.toggled.connect(self.toggle_ownership)
        nav2 = QHBoxLayout()
        nav2.addWidget(self.move_label, 1)
        nav2.addWidget(self.show_owner)

        self.progress = QProgressBar()
        self.progress.hide()
        self.graph = WinrateGraph()
        self.graph.move_selected.connect(self.goto_review)
        self.mistakes = QListWidget()
        self.mistakes.setMaximumHeight(120)
        self.mistakes.itemClicked.connect(lambda it: self.goto_review(it.data(Qt.UserRole)))
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)

        right = QVBoxLayout()
        right.addWidget(self.info)
        right.addWidget(self.engine_status)
        right.addLayout(grid)
        right.addLayout(nav)
        right.addLayout(nav2)
        right.addWidget(self.progress)
        right.addWidget(self.graph)
        lbl = QLabel("Ошибки партии (после разбора):")
        right.addWidget(lbl)
        right.addWidget(self.mistakes)
        right.addWidget(QLabel("Объяснение:"))
        right.addWidget(self.text, 1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(340)

        split = QSplitter()
        split.addWidget(self.board)
        split.addWidget(rw)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.goto(self.view - 1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.goto(self.view + 1))

        self.start_game(GameSettings(int(QSettings().value("game/size", 9)),
                                     QSettings().value("game/rules", "chinese"),
                                     float(QSettings().value("game/komi", 7.5)), 0, BLACK,
                                     int(QSettings().value("game/level", 2))))
        self.set_text("Добро пожаловать! Вы играете чёрными. Щёлкните по пересечению линий, чтобы сделать ход.\n"
                      "Подсказка — ИИ покажет лучший ход и объяснит его. "
                      "Объяснить ход — разбор хода, который сейчас на доске. "
                      "Разобрать партию — поиск всех ошибок после игры.")

    # ------------------------------------------------------------------ состояние
    @property
    def live(self) -> bool:
        return self.view == len(self.game.moves)

    def is_human_turn(self) -> bool:
        if self.settings.human_color == 0:
            return True
        return self.game.to_play == self.settings.human_color

    def set_text(self, text: str) -> None:
        self.text.setHtml(text_to_html(text))

    def start_game(self, gs: GameSettings, game: Optional[Game] = None) -> None:
        self.cancel_queries()
        self.settings = gs
        self.game = game or Game(gs.size, gs.komi, gs.rules, gs.handicap)
        self.view = len(self.game.moves)
        self.scoring = False
        self.dead = set()
        self.result = None
        self.analyses.clear()
        self.reviews.clear()
        self.mistakes.clear()
        self.graph.set_data({}, 0, {})
        self.board.clear_marks()
        self.refresh()
        self.maybe_bot()

    def new_game_dialog(self) -> None:
        d = NewGameDialog(self)
        if d.exec():
            gs = d.result_settings()
            self.start_game(gs)
            lv = LEVELS[gs.level]
            if lv.needs_engine and not self.em.available():
                self.set_text("ИИ KataGo не запущен, поэтому пока играет встроенный бот (уровень «Новичок»). "
                              "Установить KataGo можно в меню «Настройки».")
            else:
                self.set_text("Новая партия началась. Удачи!")

    def cancel_queries(self) -> None:
        if self.em.engine:
            for q in (self.bot_query, self.review_query):
                if q:
                    self.em.engine.cancel(q)
        self.bot_query = None
        self.review_query = None
        self.bot_thinking = False
        self.progress.hide()

    def refresh(self) -> None:
        g = self.game
        b = g.boards[self.view]
        last = g.moves[self.view - 1].point if self.view > 0 else None
        self.board.set_board(b, last)
        self.board.ghost_color = g.to_play if (self.live and not self.scoring and not self.result) else None
        self.board.interactive = self.live and not self.bot_thinking
        caps = g.captures(self.view)
        rules = "китайские" if g.rules == "chinese" else "японские"
        who = {BLACK: "Вы", WHITE: "Бот"} if self.settings.human_color == BLACK else (
            {BLACK: "Бот", WHITE: "Вы"} if self.settings.human_color == WHITE else {BLACK: "Игрок 1", WHITE: "Игрок 2"})
        lines = [f"<b>Доска {g.size}×{g.size}</b>, правила: {rules}, коми {g.komi:g}",
                 f"⚫ Чёрные ({who[BLACK]}) — пленников: {caps[BLACK]}",
                 f"⚪ Белые ({who[WHITE]}) — пленников: {caps[WHITE]}"]
        if self.settings.human_color != 0:
            lines.append(f"Бот: {LEVELS[self.effective_level()].name}")
        if self.result:
            lines.append(f"<b>Итог: {html.escape(self.result)}</b>")
        elif self.scoring:
            lines.append("<b>Подсчёт очков:</b> щёлкайте по группам, чтобы отметить мёртвые камни, затем «Подтвердить подсчёт».")
        elif self.bot_thinking:
            lines.append("Бот думает…")
        else:
            lines.append(f"Ход: {'чёрных' if g.to_play == BLACK else 'белых'}")
        self.info.setText("<br>".join(lines))
        self.move_label.setText(f"Ход {self.view} из {len(g.moves)}")
        self.graph.set_current(self.view)
        playing = not self.result and not self.scoring
        self.btn_pass.setEnabled(playing and self.live and self.is_human_turn() and not self.bot_thinking)
        self.btn_resign.setEnabled(playing and self.settings.human_color != 0)
        self.btn_undo.setEnabled(bool(g.moves) and not self.bot_thinking and not self.scoring)
        self.btn_score.setText("Подтвердить подсчёт" if self.scoring else "Подсчитать очки")
        self.btn_score.setEnabled(not self.result)
        self.btn_review.setEnabled(bool(g.moves) and self.em.available() and self.review_query is None)
        self.btn_hint.setEnabled(playing)
        self.btn_explain.setEnabled(self.view > 0)
        self.toggle_ownership(self.show_owner.isChecked())

    def effective_level(self) -> int:
        lv = LEVELS[self.settings.level]
        if lv.needs_engine and not self.em.available():
            return 0
        return self.settings.level

    # ------------------------------------------------------------------ ходы
    def on_click(self, x: int, y: int) -> None:
        if self.scoring:
            self.dead = toggle_dead_group(self.game.board, self.dead, (x, y))
            self.show_scoring()
            return
        if self.result or self.bot_thinking:
            return
        if not self.live:
            ans = QMessageBox.question(self, "Продолжить отсюда?",
                                       "Вы смотрите старую позицию. Продолжить партию с неё? Последующие ходы будут удалены.")
            if ans != QMessageBox.Yes:
                return
            while len(self.game.moves) > self.view:
                self.game.undo()
            self.drop_reviews_after(self.view)
        if not self.is_human_turn():
            return
        try:
            self.game.play((x, y))
        except IllegalMove as e:
            self.set_text(f"Так ходить нельзя: {e}.")
            return
        self.after_move()

    def human_pass(self) -> None:
        if not self.live or self.result:
            return
        self.game.play(None)
        self.after_move()

    def after_move(self) -> None:
        self.view = len(self.game.moves)
        self.board.clear_marks()
        self.drop_reviews_after(self.view - 1)
        if self.game.consecutive_passes() >= 2:
            self.refresh()
            self.start_scoring()
            return
        last = self.game.moves[-1]
        if last.point is None and self.settings.human_color != 0 and last.color != self.settings.human_color:
            self.set_text("Бот пасует: он считает, что ценных ходов не осталось. "
                          "Если вы согласны — тоже нажмите «Пас», и начнётся подсчёт очков.")
        self.refresh()
        self.maybe_bot()

    def drop_reviews_after(self, n: int) -> None:
        for k in [k for k in self.reviews if k > n]:
            del self.reviews[k]
        for k in [k for k in self.analyses if k > n]:
            del self.analyses[k]

    def undo(self) -> None:
        if self.bot_thinking or not self.game.moves:
            return
        self.result = None
        self.game.resigned = None
        self.game.undo()
        # отменяем и ход бота, чтобы снова был ход человека
        if self.settings.human_color != 0 and self.game.moves and not self.is_human_turn():
            self.game.undo()
        self.view = len(self.game.moves)
        self.drop_reviews_after(self.view)
        self.board.clear_marks()
        self.refresh()
        self.maybe_bot()

    def resign(self) -> None:
        if QMessageBox.question(self, "Сдаться", "Вы уверены, что хотите сдаться?") != QMessageBox.Yes:
            return
        human = self.settings.human_color
        self.game.resigned = human
        self.result = f"{'Белые' if human == BLACK else 'Чёрные'} побеждают (сдача)"
        self.cancel_queries()
        self.refresh()
        self.set_text(self.result + "\nНажмите «Разобрать партию», чтобы найти ошибки.")

    # ------------------------------------------------------------------ бот
    def maybe_bot(self) -> None:
        if self.result or self.scoring or not self.live or self.is_human_turn() or self.bot_thinking:
            return
        self.bot_thinking = True
        self.refresh()
        lv = LEVELS[self.effective_level()]
        opp_passed = bool(self.game.moves) and self.game.moves[-1].point is None
        if lv.mode == "simple":
            QTimer.singleShot(250, self.simple_bot_move)
            return
        visits = lv.visits if lv.mode == "search" else (40 if opp_passed else 2)
        gen = len(self.game.moves)

        def done(a: Optional[Analysis]):
            self.bot_query = None
            if not self.bot_thinking or len(self.game.moves) != gen:
                return
            if a is None:
                self.simple_bot_move()
                return
            self.analyses.setdefault(gen, a)
            p = choose_from_analysis(lv, a, self.game.size, opp_passed, self.rng)
            self.bot_play(p)

        try:
            self.bot_query = self.em.engine.analyze_position(self.game, self.em.in_ui(done), visits=visits,
                                                             ownership=False, policy=(lv.mode == "policy"))
        except Exception:
            QTimer.singleShot(250, self.simple_bot_move)

    def simple_bot_move(self) -> None:
        if not self.bot_thinking:
            return
        last = self.game.moves[-1].point if self.game.moves else None
        p = choose_move(self.game.board, self.game.to_play, last)
        self.bot_play(p)

    def bot_play(self, p) -> None:
        self.bot_thinking = False
        try:
            self.game.play(p)
        except IllegalMove:
            self.game.play(None)
        self.after_move()

    # ------------------------------------------------------------------ подсчёт
    def score_button(self) -> None:
        if self.scoring:
            self.confirm_score()
        else:
            if self.bot_thinking:
                return
            self.start_scoring()

    def start_scoring(self) -> None:
        self.scoring = True
        self.dead = set()
        self.view = len(self.game.moves)
        self.refresh()
        if self.em.available():
            self.set_text("ИИ определяет мёртвые камни…")

            def done(a: Optional[Analysis]):
                if a is not None and a.ownership and self.scoring:
                    self.dead = dead_from_ownership(self.game.board, a.ownership)
                    self.analyses[len(self.game.moves)] = a
                self.show_scoring()
                self.set_text("Подсчёт очков. ИИ отметил мёртвые камни (полупрозрачные). "
                              "Если вы не согласны, щёлкните по группе, чтобы изменить её статус. "
                              "Затем нажмите «Подтвердить подсчёт».")
            self.em.engine.analyze_position(self.game, self.em.in_ui(done), visits=200)
        else:
            self.show_scoring()
            self.set_text("Подсчёт очков. Щёлкните по группам, которые считаются мёртвыми (они не смогут "
                          "выжить), затем нажмите «Подтвердить подсчёт».")

    def show_scoring(self) -> None:
        g = self.game
        r = score(g.board, g.rules, g.komi, g.captures(), self.dead)
        self.board.dead = set(self.dead)
        self.board.territory = dict(r.owner)
        self.board.update()
        self.info.setText(self.info.text().split("<br><b>Подсчёт")[0] + "<br>" + html.escape(r.details()).replace("\n", "<br>"))

    def confirm_score(self) -> None:
        g = self.game
        r = score(g.board, g.rules, g.komi, g.captures(), self.dead)
        self.scoring = False
        self.result = r.result_string()
        self.board.dead = set(self.dead)
        self.board.territory = dict(r.owner)
        self.refresh()
        self.set_text("Партия окончена\n" + r.details() + "\nНажмите «Разобрать партию», чтобы ИИ нашёл ошибки и объяснил их.")

    # ------------------------------------------------------------------ навигация
    def goto(self, n: int) -> None:
        n = max(0, min(len(self.game.moves), n))
        if n == self.view:
            return
        self.view = n
        self.board.clear_marks()
        if self.scoring and n != len(self.game.moves):
            self.scoring = False
        self.refresh()
        if n in self.reviews:
            self.show_review(n)

    def goto_review(self, n: int) -> None:
        self.goto(n)
        if n in self.reviews:
            self.show_review(n)

    def show_review(self, n: int) -> None:
        r = self.reviews[n]
        self.set_text(r.text)
        self.board.circles.clear()
        self.board.labels.clear()
        if r.best_move and r.best_move.lower() != "pass" and r.loss >= 0.5:
            bp = from_gtp(r.best_move, self.game.size)
            # показываем позицию до хода: лучший ход — зелёным, сыгранный — красным
            self.board.set_board(self.game.boards[n - 1], None)
            self.board.circles[bp] = GREEN
            if r.point is not None:
                self.board.circles[r.point] = RED
            for i, mv in enumerate(r.best_pv[:6]):
                pt = from_gtp(mv, self.game.size)
                if pt is not None and pt != bp and self.game.boards[n - 1].get(pt) == 0 and pt not in self.board.labels:
                    self.board.labels[pt] = (str(i + 1), BLUE)
            self.board.labels[bp] = ("1", GREEN)
        self.board.update()

    def toggle_ownership(self, on: bool) -> None:
        a = self.analyses.get(self.view)
        self.board.ownership = a.ownership if (on and a and a.ownership) else None
        self.board.update()
        if on and not a and self.em.available():
            n = self.view

            def done(res: Optional[Analysis]):
                if res is not None:
                    self.analyses.setdefault(n, res)
                    if self.view == n and self.show_owner.isChecked():
                        self.board.ownership = res.ownership
                        self.board.update()
            self.em.engine.analyze_position(self.game, self.em.in_ui(done), upto=n, visits=100)
        elif on and not self.em.available():
            self.set_text("Карта территории доступна, когда запущен ИИ KataGo (меню «Настройки»).")

    # ------------------------------------------------------------------ подсказка и объяснение
    def hint(self) -> None:
        if not self.live:
            self.goto(len(self.game.moves))
        g = self.game
        if not self.em.available():
            p = choose_move(g.board, g.to_play, g.moves[-1].point if g.moves else None, seed=1)
            self.board.circles = {p: GREEN} if p else {}
            self.board.update()
            if p:
                self.set_text(f"Подсказка встроенного бота: {to_gtp(p, g.size)}\n"
                              + " ".join(tactical_facts(g.board, g.to_play, p).sentences)
                              + "\nТочную оценку и объяснения даёт ИИ KataGo (меню «Настройки»).")
            return
        self.set_text("ИИ ищет лучший ход…")
        n = len(g.moves)
        color = g.to_play

        def done(a: Optional[Analysis]):
            if a is None or len(self.game.moves) != n:
                return
            self.analyses[n] = a
            self.board.circles.clear()
            self.board.labels.clear()
            s = 1 if color == BLACK else -1
            lines = ["Подсказка ИИ"]
            top = [m for m in a.moves[:3]]
            if not top:
                return
            best_val = s * top[0].score_lead
            for i, m in enumerate(top):
                p = from_gtp(m.move, g.size)
                diff = best_val - s * m.score_lead
                if p is not None:
                    self.board.labels[p] = (str(i + 1), GREEN if i == 0 else BLUE)
                tf = tactical_facts(g.board, color, p) if p is not None else None
                desc = " ".join(tf.sentences) if tf and tf.sentences else ""
                extra = "" if i == 0 else f" (хуже на {points_word(diff)})" if diff >= 0.3 else " (почти так же хорошо)"
                lines.append(f"{i + 1}. {m.move}{extra}: {desc or 'ход укрепляет позицию.'}")
            b = top[0]
            if b.pv:
                lines.append("Ожидаемое продолжение: " + pv_text(b.pv, color) + ".")
            wr = b.winrate if color == BLACK else 1 - b.winrate
            lead = s * b.score_lead
            lines.append(f"Оценка позиции: шансы {'чёрных' if color == BLACK else 'белых'} {wr * 100:.0f}%, "
                         f"{'перевес' if lead >= 0 else 'отставание'} около {points_gen(abs(lead))}.")
            self.set_text("\n".join(lines))
            self.board.update()

        self.em.engine.analyze_position(g, self.em.in_ui(done), visits=300)

    def explain_current(self) -> None:
        n = self.view
        if n == 0:
            return
        if n in self.reviews:
            self.show_review(n)
            return
        g = self.game
        m = g.moves[n - 1]
        before_board = g.boards[n - 1]
        if not self.em.available():
            self.set_text(offline_explanation(before_board, m.color, m.point, n))
            return
        self.set_text("ИИ разбирает ход…")
        got: dict[int, Analysis] = {}

        def make_cb(k):
            def cb(a: Optional[Analysis]):
                if a is None:
                    return
                got[k] = a
                self.analyses.setdefault(k, a)
                if len(got) == 2 and len(self.game.moves) >= n:
                    self.reviews[n] = review_move(before_board, m.color, m.point, n, got[n - 1], got[n])
                    if self.view == n:
                        self.show_review(n)
            return cb
        for k in (n - 1, n):
            self.em.engine.analyze_position(g, self.em.in_ui(make_cb(k)), upto=k, visits=300)

    # ------------------------------------------------------------------ разбор партии
    def review_game(self) -> None:
        if not self.em.available() or not self.game.moves:
            return
        g = self.game
        total = len(g.moves) + 1
        visits = int(QSettings().value("katago/review_visits", 100))
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress.setFormat("Разбор партии: %v из %m позиций")
        self.progress.show()
        got: dict[int, Analysis] = {}
        moves_snapshot = len(g.moves)

        def on_turn(a: Analysis):
            if len(self.game.moves) != moves_snapshot:
                return
            got[a.turn] = a
            self.progress.setValue(len(got))
            if len(got) == total:
                self.review_query = None
                self.progress.hide()
                self.finish_review(got)

        self.review_query = self.em.engine.analyze_game(g, self.em.in_ui(on_turn), visits=visits)
        self.refresh()

    def finish_review(self, got: dict[int, Analysis]) -> None:
        g = self.game
        self.analyses.update(got)
        self.mistakes.clear()
        marks = {}
        for n in range(1, len(g.moves) + 1):
            m = g.moves[n - 1]
            r = review_move(g.boards[n - 1], m.color, m.point, n, got[n - 1], got[n])
            self.reviews[n] = r
            marks[n] = r.mark
        values = {n: a.winrate for n, a in got.items()}
        self.graph.set_data(values, len(g.moves), marks)
        human = self.settings.human_color
        bad = [r for r in self.reviews.values() if r.loss >= 1.5]
        bad.sort(key=lambda r: r.move_number)
        counts = {BLACK: [0, 0, 0], WHITE: [0, 0, 0]}
        for r in self.reviews.values():
            if r.mark == "?!":
                counts[r.color][0] += 1
            elif r.mark == "?":
                counts[r.color][1] += 1
            elif r.mark == "??":
                counts[r.color][2] += 1
        for r in bad:
            who = "Ч" if r.color == BLACK else "Б"
            pt = to_gtp(r.point, g.size) if r.point else "пас"
            it = QListWidgetItem(f"Ход {r.move_number} ({who} {pt}) {r.mark} {r.label}: −{points_word(r.loss)}, лучше {r.best_move}")
            it.setData(Qt.UserRole, r.move_number)
            if r.mark == "??":
                it.setForeground(RED)
            elif r.mark == "?":
                it.setForeground(QColor("#c66a00"))
            if human and r.color != human:
                it.setForeground(QColor("#888"))
            self.mistakes.addItem(it)
        lines = ["Разбор партии готов"]
        for c, name in ((BLACK, "Чёрные"), (WHITE, "Белые")):
            a, b, cc = counts[c]
            lines.append(f"{name}: неточностей {a}, ошибок {b}, грубых ошибок {cc}.")
        if bad:
            worst = max(bad, key=lambda r: r.loss if (not human or r.color == human) else -1)
            lines.append(f"Самый важный момент: ход {worst.move_number}. Щёлкните по нему в списке ошибок или на графике, "
                         f"чтобы увидеть объяснение. Зелёный кружок — лучший ход, красный — сыгранный, "
                         f"цифры — ожидаемое продолжение.")
        self.set_text("\n".join(lines))
        self.refresh()

    # ------------------------------------------------------------------ файлы
    def save_sgf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить партию", "партия.sgf", "SGF (*.sgf)")
        if not path:
            return
        comments = {n: r.text for n, r in self.reviews.items()}
        with open(path, "w", encoding="utf-8") as f:
            f.write(save_sgf(self.game, "", comments))

    def open_sgf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть партию", "", "SGF (*.sgf);;Все файлы (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                game = load_sgf(f.read())
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать файл: {e}")
            return
        gs = GameSettings(game.size, game.rules, game.komi, game.handicap, 0, self.settings.level)
        self.start_game(gs, game)
        self.set_text(f"Партия загружена: {len(game.moves)} ходов. Нажмите «Разобрать партию», чтобы ИИ нашёл ошибки. "
                      f"Партия открыта в режиме «вдвоём», её можно продолжить с любого хода.")
