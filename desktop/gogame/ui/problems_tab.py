"""Вкладка «Задачи»: курс от правил до дебюта и ёсэ, разбор каждого хода, импорт сборников SGF."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..board import BLACK, EMPTY, from_gtp, to_gtp
from ..engine.katago import Analysis
from ..explain import pv_text, tactical_facts
from ..problems import Level, Problem, ProblemSession, load, local_region
from .board_widget import BoardWidget
from .game_tab import GREEN, RED, BLUE

STAGE_ORDER = ["Основы", "Тактика", "Жизнь и смерть", "Форма", "Дебют", "Середина игры", "Ёсэ (конец игры)",
               "Библиотека: 25–16 кю", "Библиотека: 15–10 кю", "Библиотека: 9–4 кю", "Библиотека: 3 кю – 2 дан",
               "Библиотека: 3–5 дан и сильнее", "Библиотека: тематические сборники", "Мои сборники"]


def is_course(stage: str) -> bool:
    return not stage.startswith("Библиотека") and stage != "Мои сборники"


def esc(t: str) -> str:
    return html.escape(t)


class ProblemsTab(QWidget):
    def __init__(self, engine_manager, parent=None):
        super().__init__(parent)
        self.em = engine_manager
        self.session: Optional[ProblemSession] = None
        self.index = -1

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(250)
        self.tree.itemClicked.connect(self.on_tree_click)
        self.tree.itemExpanded.connect(self.fill_level)
        self.items: dict[str, QTreeWidgetItem] = {}
        self.level_items: dict[int, QTreeWidgetItem] = {}
        self.by_level: dict[int, list[int]] = {}
        self.progress_label = QLabel()
        self.btn_import = QPushButton("Импорт задач (SGF)…")
        self.btn_import.setToolTip("Добавить сборник задач из SGF-файлов (например, скачанных с сайтов библиотек го)")
        self.btn_import.clicked.connect(self.import_sgf)
        left = QVBoxLayout()
        left.addWidget(self.progress_label)
        left.addWidget(self.tree, 1)
        left.addWidget(self.btn_import)
        lw = QWidget()
        lw.setLayout(left)

        self.board = BoardWidget()
        self.board.clicked.connect(self.on_click)

        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.task = QLabel()
        self.task.setWordWrap(True)
        self.task.setStyleSheet("font-size: 14px;")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.text = QTextBrowser()

        self.btn_reset = QPushButton("Заново")
        self.btn_hint = QPushButton("Подсказка")
        self.btn_solution = QPushButton("Показать решение")
        self.btn_ai = QPushButton("Разбор с ИИ")
        self.btn_next = QPushButton("Следующая ▶")
        self.btn_ai.setToolTip("KataGo разберёт позицию: покажет лучший ход, а после ошибки — как соперник её наказывает")
        self.btn_reset.clicked.connect(self.reset)
        self.btn_hint.clicked.connect(self.hint)
        self.btn_solution.clicked.connect(self.show_solution)
        self.btn_ai.clicked.connect(self.ai_review)
        self.btn_next.clicked.connect(self.next_problem)
        row1 = QHBoxLayout()
        for b in (self.btn_reset, self.btn_hint, self.btn_solution):
            row1.addWidget(b)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn_ai)
        row2.addWidget(self.btn_next)

        right = QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(self.task)
        right.addWidget(self.status)
        right.addLayout(row1)
        right.addLayout(row2)
        right.addWidget(self.text, 1)
        rw = QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(340)

        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(self.board)
        split.addWidget(rw)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)
        lay = QHBoxLayout(self)
        lay.addWidget(split)

        self.reload()

    # ------------------------------------------------------------------ список задач
    def reload(self, open_id: Optional[str] = None) -> None:
        self.levels, self.problems = load()
        self.tree.clear()
        self.items.clear()
        self.level_items.clear()
        self.by_level = {}
        for i, p in enumerate(self.problems):
            self.by_level.setdefault(p.level, []).append(i)
        stages: dict[str, QTreeWidgetItem] = {}
        order = {s: i for i, s in enumerate(STAGE_ORDER)}
        for lv in sorted(self.levels, key=lambda l: (order.get(l.stage or "Основы", 50), l.level)):
            stage = lv.stage or "Основы"
            if not self.by_level.get(lv.level):
                continue
            if stage not in stages:
                st = QTreeWidgetItem([stage])
                st.setData(0, Qt.UserRole, ("stage", stage))
                f = st.font(0)
                f.setBold(True)
                f.setPointSize(f.pointSize() + 1)
                st.setFont(0, f)
                self.tree.addTopLevelItem(st)
                stages[stage] = st
                st.setExpanded(is_course(stage))
            n = len(self.by_level[lv.level])
            top = QTreeWidgetItem([lv.title if is_course(stage) else f"{lv.title} — {n}"])
            top.setData(0, Qt.UserRole, ("level", lv.level))
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            stages[stage].addChild(top)
            self.level_items[lv.level] = top
            if is_course(stage):
                self.fill_level(top)
            else:
                # задачи большой библиотеки добавляются в список, только когда раздел раскрывают
                top.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        self.update_progress()
        solved = self.solved_set()
        if open_id is not None:
            idx = next((i for i, p in enumerate(self.problems) if p.id == open_id), 0)
        else:
            idx = next((i for i, p in enumerate(self.problems) if p.id not in solved), 0)
        if self.problems:
            self.open_problem(idx)

    def fill_level(self, top: QTreeWidgetItem) -> None:
        kind, lvl = top.data(0, Qt.UserRole)
        if kind != "level" or top.childCount():
            return
        solved = self.solved_set()
        for i in self.by_level.get(lvl, []):
            p = self.problems[i]
            it = QTreeWidgetItem([self.item_text(p, p.id in solved)])
            it.setData(0, Qt.UserRole, ("problem", i))
            top.addChild(it)
            self.items[p.id] = it

    def item_for(self, p: Problem) -> QTreeWidgetItem:
        if p.id not in self.items:
            self.fill_level(self.level_items[p.level])
        return self.items[p.id]

    def update_progress(self) -> None:
        solved = self.solved_set()
        lib = {l.level for l in self.levels if not is_course(l.stage or "Основы")}
        course = [p for p in self.problems if p.level not in lib]
        extra = [p for p in self.problems if p.level in lib]
        done_c = sum(1 for p in course if p.id in solved)
        text = f"Курс: решено {done_c} из {len(course)}"
        if extra:
            done_e = sum(1 for p in extra if p.id in solved)
            text += f"\nБиблиотека: решено {done_e} из {len(extra):,}".replace(",", " ")
        self.progress_label.setText(text)

    @staticmethod
    def solved_set() -> set[str]:
        v = QSettings().value("problems/solved", "")
        return set(x for x in str(v).split(",") if x)

    def mark_solved(self, pid: str) -> None:
        s = self.solved_set()
        s.add(pid)
        QSettings().setValue("problems/solved", ",".join(sorted(s)))
        p = next(p for p in self.problems if p.id == pid)
        if pid in self.items:
            self.items[pid].setText(0, self.item_text(p, True))
        self.update_progress()

    @staticmethod
    def item_text(p: Problem, solved: bool) -> str:
        if p.id.startswith("lib-"):
            return f"{'✓' if solved else '○'} {p.title}"
        num = p.id if not p.id.startswith("imp") else p.id.split("-")[-1]
        return f"{'✓' if solved else '○'} {num}. {p.title}"

    def level_of(self, p: Problem) -> Level:
        return next(l for l in self.levels if l.level == p.level)

    def on_tree_click(self, item: QTreeWidgetItem) -> None:
        kind, val = item.data(0, Qt.UserRole)
        if kind == "problem":
            self.open_problem(val)
        elif kind == "level":
            lv = next(l for l in self.levels if l.level == val)
            self.show_lesson(lv)

    def show_lesson(self, lv: Level) -> None:
        parts = [f"<h3>{esc(lv.title)}</h3>", f"<p>{esc(lv.lesson)}</p>"]
        if lv.books:
            parts.append(f"<p><i>Что почитать: {esc(lv.books)}</i></p>")
        self.text.setHtml("".join(parts))

    # ------------------------------------------------------------------ открыть задачу
    def open_problem(self, i: int) -> None:
        self.index = i
        p = self.problems[i]
        self.session = ProblemSession(p)
        self.tree.setCurrentItem(self.item_for(p))
        lv = self.level_of(p)
        self.title.setText(f"{lv.title} — {p.title}")
        self.task.setText(p.task)
        self.set_status("Ваш ход.", None)
        self.text.setHtml(self.intro_html(p, lv))
        self.set_view()
        self.refresh()

    def intro_html(self, p: Problem, lv: Level) -> str:
        parts = []
        if p.concept:
            parts.append(f"<p><b>Что изучаем.</b> {esc(p.concept)}</p>")
        if p.why:
            parts.append(f"<p><b>Зачем это в партии.</b> {esc(p.why)}</p>")
        if not parts:
            parts.append(f"<p><b>Теория раздела.</b> {esc(lv.lesson)}</p>")
        if p.source:
            parts.append(f"<p style='color:gray'><i>По мотивам: {esc(p.source)}</i></p>")
        if p.kind == "whole":
            parts.append("<p style='color:gray'>Здесь нет единственного ответа: правильными считаются ходы, "
                         "которые сильный ИИ оценивает почти одинаково с лучшим. Важно понять идею.</p>")
        return "".join(parts)

    def set_view(self) -> None:
        """Для угловых задач на большой доске показываем только нужную часть."""
        p = self.problems[self.index]
        b = p.initial_board()
        if b.size <= 9 or p.kind == "whole":
            self.board.view = None
            return
        pts = [q for q in b.points() if b.get(q) != EMPTY]
        if not pts:
            self.board.view = None
            return
        m = 2
        x0 = max(0, min(q[0] for q in pts) - m)
        x1 = min(b.size - 1, max(q[0] for q in pts) + m)
        y0 = max(0, min(q[1] for q in pts) - m)
        y1 = min(b.size - 1, max(q[1] for q in pts) + m)
        # не меньше 9 линий, чтобы было видно окружение
        while x1 - x0 < 8:
            if x0 > 0:
                x0 -= 1
            if x1 - x0 < 8 and x1 < b.size - 1:
                x1 += 1
        while y1 - y0 < 8:
            if y0 > 0:
                y0 -= 1
            if y1 - y0 < 8 and y1 < b.size - 1:
                y1 += 1
        if x1 - x0 >= b.size - 3 and y1 - y0 >= b.size - 3:
            self.board.view = None
        else:
            self.board.view = (x0, y0, x1, y1)

    def refresh(self) -> None:
        s = self.session
        last = s.game.moves[-1].point if s.game.moves else None
        self.board.clear_marks()
        self.board.set_board(s.board, last)
        p = s.problem
        self.board.marked = {from_gtp(m, p.size) for m in p.marked if s.board.get(from_gtp(m, p.size)) != 0}
        self.board.ghost_color = s.game.to_play if not (s.solved or s.failed) else None
        self.btn_ai.setEnabled(self.em.available())
        self.board.update()

    def set_status(self, text: str, color: Optional[str]) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color or 'palette(text)'};")

    def reset(self) -> None:
        self.open_problem(self.index)

    def next_problem(self) -> None:
        self.open_problem((self.index + 1) % len(self.problems))

    def opp_name(self) -> str:
        return "Белые" if self.session.problem.to_play == BLACK else "Чёрные"

    # ------------------------------------------------------------------ ходы
    def on_click(self, x: int, y: int) -> None:
        s = self.session
        if s is None or s.solved or s.failed:
            return
        before = s.board.copy()
        color = s.game.to_play
        ans = s.play((x, y))
        if ans.kind == "illegal":
            self.set_status(ans.comment, "#c66a00")
            return
        size = s.problem.size
        mv = to_gtp((x, y), size)
        facts = tactical_facts(before, color, (x, y), opening=False)
        tactic = " ".join(facts.sentences)
        opp = self.opp_name()
        if ans.kind in ("correct", "solved"):
            parts = [f"<p><b>{mv} — {'задача решена!' if ans.kind == 'solved' else 'правильно.'}</b></p>",
                     f"<p>{esc(ans.comment)}</p>"]
            if ans.reply is not None:
                rc = esc(ans.reply_comment)
                if ans.kind == "correct":
                    parts.append(f"<p>{opp} отвечают {to_gtp(ans.reply, size)}. {rc} Ваш ход.</p>")
                else:
                    parts.append(f"<p>{opp} отвечают {to_gtp(ans.reply, size)}. {rc}</p>")
            if ans.kind == "solved" and s.problem.concept:
                parts.append(f"<p style='color:#1a7f3c'><b>Запомните:</b> {esc(s.problem.concept)}</p>")
            self.text.setHtml("".join(parts))
            if ans.kind == "solved":
                self.set_status("✓ Решено!", "#1aa34a")
                self.mark_solved(s.problem.id)
            else:
                self.set_status("Правильно! Продолжайте.", "#1aa34a")
        elif ans.kind == "wrong":
            parts = [f"<p><b>{mv} — не получается.</b></p>", f"<p>{esc(ans.comment)}</p>"]
            if ans.reply is not None:
                parts.append(f"<p>Ответ соперника: {to_gtp(ans.reply, size)} (последний ход на доске).</p>")
            parts.append("<p>Нажмите «Заново», чтобы попробовать ещё раз, или «Показать решение».</p>")
            self.text.setHtml("".join(parts))
            self.set_status("✗ Неверно", "#d93025")
        else:
            parts = [f"<p><b>{mv} — это не решение задачи.</b></p>"]
            if tactic:
                parts.append(f"<p>Что делает ваш ход: {esc(tactic)}</p>")
            parts.append(f"<p>Подсказка: {esc(s.problem.hint)}</p>")
            if self.em.available():
                parts.append("<p>Нажмите «Разбор с ИИ», и KataGo покажет, как соперник опровергает этот ход.</p>")
            parts.append("<p>Нажмите «Заново», чтобы попробовать ещё раз.</p>")
            self.text.setHtml("".join(parts))
            self.set_status("✗ Неверно", "#d93025")
        self.refresh()

    def hint(self) -> None:
        s = self.session
        if s is None:
            return
        txt = f"<p><b>Подсказка</b></p><p>{esc(s.problem.hint)}</p>"
        if s.problem.concept:
            txt += f"<p>Вспомните идею: {esc(s.problem.concept)}</p>"
        exp = s.expected_moves()
        if exp and not (s.solved or s.failed):
            p = from_gtp(exp[0], s.problem.size)
            txt += f"<p>Ищите ход {self.region_hint(p, s.problem.size)}.</p>"
        self.text.setHtml(txt)

    @staticmethod
    def region_hint(p, size) -> str:
        x, y = p
        horiz = "слева" if x < size / 3 else ("справа" if x >= 2 * size / 3 else "")
        vert = "вверху" if y < size / 3 else ("внизу" if y >= 2 * size / 3 else "")
        if not horiz and not vert:
            return "в центральной части доски"
        return ", ".join(t for t in (vert, horiz) if t)

    def show_solution(self) -> None:
        if self.session is None:
            return
        self.reset()
        s = self.session
        line = s.problem.solution_line()
        if not line:
            return
        size = s.problem.size
        for i, (mv, _) in enumerate(line):
            p = from_gtp(mv, size)
            if p is not None and p not in self.board.labels:
                self.board.labels[p] = (str(i + 1), GREEN if i % 2 == 0 else BLUE)
        self.board.update()
        me = "Чёрные" if s.problem.to_play == BLACK else "Белые"
        opp = self.opp_name()
        parts = ["<p><b>Решение</b> (зелёные цифры — ваши ходы, синие — ответы соперника)</p>"]
        for i, (mv, c) in enumerate(line):
            who = me if i % 2 == 0 else opp
            parts.append(f"<p><b>{i + 1}. {who} {mv}.</b> {esc(c)}</p>")
        others = [n["move"] for n in s.problem.tree.get("next", [])[1:]]
        if others:
            parts.append(f"<p>Тоже правильно: {', '.join(others)}.</p>")
        if s.problem.concept:
            parts.append(f"<p><b>Идея:</b> {esc(s.problem.concept)}</p>")
        self.text.setHtml("".join(parts))
        self.set_status("Посмотрите решение и попробуйте сами (кнопка «Заново»).", None)
        self.board.ghost_color = None
        s.failed = True

    # ------------------------------------------------------------------ импорт
    def import_sgf(self) -> None:
        from ..problems.sgf_import import clear_imported, import_files
        box = QMessageBox(self)
        box.setWindowTitle("Импорт задач")
        box.setText("Выберите SGF-файлы со сборником задач (цумэго). Правильные варианты в файле обычно "
                    "помечены словом RIGHT или «правильно»; если пометок нет, правильным считается главный вариант.")
        add = box.addButton("Выбрать файлы…", QMessageBox.AcceptRole)
        add_dir = box.addButton("Выбрать папку…", QMessageBox.AcceptRole)
        clear = box.addButton("Удалить все импортированные", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == clear:
            clear_imported()
            self.reload()
            return
        if box.clickedButton() == add_dir:
            folder = QFileDialog.getExistingDirectory(self, "Папка со сборником SGF (вложенные папки тоже)")
            files = sorted(str(p) for p in Path(folder).rglob("*") if p.suffix.lower() == ".sgf") if folder else []
        elif box.clickedButton() == add:
            files, _ = QFileDialog.getOpenFileNames(self, "SGF-файлы с задачами", "", "SGF (*.sgf);;Все файлы (*)")
        else:
            return
        if not files:
            return
        try:
            added, skipped = import_files([Path(f) for f in files])
        except Exception as e:
            QMessageBox.warning(self, "Импорт", f"Не удалось прочитать файлы: {e}")
            return
        msg = f"Добавлено задач: {added}."
        if skipped:
            msg += f" Пропущено файлов (нет решения или это лекция без вопроса): {skipped}."
        QMessageBox.information(self, "Импорт", msg + "\nОни в разделе «Мои сборники».")
        self.reload()

    # ------------------------------------------------------------------ ИИ
    def ai_review(self) -> None:
        """Разбор позиции задачи с ИИ: лучший ход или опровержение хода ученика."""
        if not self.em.available() or self.session is None:
            return
        s = self.session
        game = s.game
        color = game.to_play
        board = game.board.copy()
        refuting = bool(game.moves) and color != s.problem.to_play
        allow = None if s.problem.kind == "whole" else local_region(board)
        self.text.setHtml("<p>ИИ анализирует позицию…</p>")
        n_moves = len(game.moves)

        def done(a: Optional[Analysis]):
            if a is None or not a.moves or len(self.session.game.moves) != n_moves:
                return
            who = "белых" if color != BLACK else "чёрных"
            best = a.best
            bp = from_gtp(best.move, board.size)
            self.board.clear_marks()
            self.board.set_board(board, game.moves[-1].point if game.moves else None)
            if refuting:
                parts = ["<p><b>Как соперник наказывает ваш ход</b></p>"]
            else:
                parts = [f"<p><b>Разбор ИИ: лучший ход {who} в этой позиции</b></p>"]
            if bp is not None:
                self.board.circles[bp] = RED if refuting else GREEN
                facts = tactical_facts(board, color, bp, opening=False)
                parts.append(f"<p><b>{best.move}</b>. {esc(' '.join(facts.sentences))}</p>")
            sign = 1 if color == BLACK else -1
            alts = [m for m in a.moves[1:4] if m.visits >= 5]
            if s.problem.kind == "whole" and alts:
                rows = []
                for m in alts:
                    d = sign * (best.score_lead - m.score_lead)
                    rows.append(f"{m.move} (−{d:.1f})" if d >= 0.1 else f"{m.move} (так же хорошо)")
                parts.append(f"<p>Другие ходы: {', '.join(rows)}.</p>")
            if best.pv:
                for i, mv in enumerate(best.pv[:8]):
                    p = from_gtp(mv, board.size)
                    if p is not None and p not in self.board.labels and board.get(p) == 0:
                        self.board.labels[p] = (str(i + 1), BLUE)
                parts.append(f"<p>Продолжение: {pv_text(best.pv, color, 8)}.</p>")
            if a.ownership and s.problem.kind != "whole":
                parts.append("<p><b>Итог по оценке ИИ:</b></p>" + group_summary(board, a.ownership))
            parts.append("<p>Цифры на доске — ожидаемый порядок ходов.</p>")
            self.text.setHtml("".join(parts))
            self.board.update()

        self.em.engine.analyze_position(game, self.em.in_ui(done), visits=500, allow_moves=allow)


def group_summary(board, ownership) -> str:
    from ..explain import group_area, _genitive_stones
    rows = []
    for st, _ in board.groups():
        if len(st) < 3:
            continue
        c = board.get(next(iter(st)))
        own = sum(ownership[q[1] * board.size + q[0]] for q in st) / len(st)
        alive = (own if c == BLACK else -own)
        name = "Чёрная" if c == BLACK else "Белая"
        if alive > 0.6:
            state = "живёт"
        elif alive < -0.6:
            state = "погибает"
        else:
            state = "под вопросом"
        rows.append(f"<li>{name} группа из {_genitive_stones(len(st))} {group_area(st, board.size)}: {state}</li>")
    return "<ul>" + "".join(rows) + "</ul>" if rows else ""
