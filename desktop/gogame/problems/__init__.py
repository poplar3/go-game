"""Учебные задачи: загрузка, проверка ответов и объяснения.

Формат задачи (problems.json):
  board   — строки доски: X — чёрный, O — белый, . — пусто
  to_play — кто ходит ("B"/"W")
  marked  — камни-цели (подсвечиваются)
  tree    — дерево решения:
      {"next": [узел...], "wrong": [ошибка...]}
      узел:   {"move": "E4", "comment": "...", "reply": "F5" | null,
               "reply_comment": "...", "next": [...], "wrong": [...]}
      ошибка: {"move": "D6", "comment": "почему это не работает", "reply": "E4"}
  Если у правильного узла нет "next" — задача решена.
  concept — что изучаем (идея задачи), why — зачем это нужно в партии,
  source  — книга или классический сборник, по мотивам которого сделана задача.

Задачи, импортированные пользователем из SGF, хранятся в папке настроек
(imported_problems.json) и показываются отдельными разделами.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..board import BLACK, WHITE, Board, Game, IllegalMove, Point, from_gtp, other, to_gtp

DATA = Path(__file__).with_name("problems.json")


@dataclass
class Level:
    level: int
    title: str
    lesson: str
    stage: str = ""
    books: str = ""


@dataclass
class Problem:
    id: str
    level: int
    title: str
    task: str
    hint: str
    board: list[str]
    to_play: int
    tree: dict
    marked: list[str] = field(default_factory=list)
    concept: str = ""
    why: str = ""
    source: str = ""
    kind: str = "local"  # "local" — местная задача, "whole" — выбор хода на всей доске (дебют, ёсэ)
    pre: list[str] = field(default_factory=list)  # ходы, сыгранные до начала задачи (например, взятие ко)

    @property
    def size(self) -> int:
        return len(self.board)

    def initial_board(self) -> Board:
        return Board.from_ascii(self.board)

    def solution_line(self) -> list[tuple[str, str]]:
        """Главный вариант решения: [(ход, комментарий), ...] включая ответы соперника."""
        res = []
        node = self.tree
        while node.get("next"):
            n = node["next"][0]
            res.append((n["move"], n.get("comment", "")))
            if n.get("reply"):
                res.append((n["reply"], n.get("reply_comment", "")))
            node = n
        return res


def imported_path() -> Path:
    from ..engine.katago import app_data_dir
    return app_data_dir() / "imported_problems.json"


def _parse(data: dict) -> tuple[list[Level], list[Problem]]:
    levels = [Level(l["level"], l["title"], l["lesson"], l.get("stage", ""), l.get("books", ""))
              for l in data.get("levels", [])]
    problems = []
    for p in data.get("problems", []):
        problems.append(Problem(p["id"], p["level"], p["title"], p["task"], p.get("hint", ""), p["board"],
                                BLACK if p.get("to_play", "B") == "B" else WHITE, p.get("tree", {}),
                                p.get("marked", []), p.get("concept", ""), p.get("why", ""), p.get("source", ""),
                                p.get("kind", "local"), p.get("pre", [])))
    return levels, problems


LIBRARY = Path(__file__).with_name("library.json.gz")


def load(include_imported: bool = True, include_library: bool = True) -> tuple[list[Level], list[Problem]]:
    levels, problems = _parse(json.loads(DATA.read_text(encoding="utf-8")))
    if include_library and LIBRARY.exists():
        import gzip
        with gzip.open(LIBRARY, "rt", encoding="utf-8") as f:
            lv, pr = _parse(json.load(f))
        levels += lv
        problems += pr
    if include_imported:
        try:
            path = imported_path()
            if path.exists():
                lv2, pr2 = _parse(json.loads(path.read_text(encoding="utf-8")))
                levels += lv2
                problems += pr2
        except Exception:
            pass  # повреждённый файл импорта не должен мешать встроенным задачам
    return levels, problems


def local_region(board: Board) -> list[str]:
    """Пункты, где имеет смысл ходить в задаче: окружённые пустые области (будущие глаза),
    а если их нет — пустые пункты рядом с камнями."""
    from ..board import EMPTY
    seen: set = set()
    enclosed: list = []
    for p in board.points():
        if board.get(p) != EMPTY or p in seen:
            continue
        region = {p}
        stack = [p]
        while stack:
            q = stack.pop()
            for nb in board.neighbors(q):
                if board.get(nb) == EMPTY and nb not in region:
                    region.add(nb)
                    stack.append(nb)
        seen |= region
        if len(region) <= 12:
            enclosed.extend(region)
    if not enclosed:
        enclosed = [p for p in board.points() if board.get(p) == EMPTY and
                    any(board.get(q) != EMPTY for q in board.neighbors(p) + board.diagonals(p))]
    return [to_gtp(p, board.size) for p in sorted(enclosed, key=lambda t: (t[1], t[0]))]


@dataclass
class Answer:
    kind: str  # "correct", "solved", "wrong", "unknown", "illegal"
    comment: str
    reply: Optional[Point] = None
    reply_comment: str = ""


class ProblemSession:
    """Ход решения одной задачи."""

    def __init__(self, problem: Problem):
        self.problem = problem
        first = problem.to_play if len(problem.pre) % 2 == 0 else other(problem.to_play)
        self.game = Game(problem.size, 0.0, "japanese", initial=problem.initial_board(), to_play=first)
        for m in problem.pre:
            self.game.play(from_gtp(m, problem.size))
        self.node = problem.tree
        self.solved = False
        self.failed = False

    @property
    def board(self) -> Board:
        return self.game.board

    def play(self, p: Point) -> Answer:
        size = self.problem.size
        gtp = to_gtp(p, size)
        try:
            self.game.play(p)
        except IllegalMove as e:
            return Answer("illegal", f"Так ходить нельзя: {e}.")
        for n in self.node.get("next", []):
            if n["move"].upper() == gtp:
                reply = from_gtp(n["reply"], size) if n.get("reply") else None
                if reply is not None:
                    self.game.play(reply)
                self.node = n
                if not n.get("next"):
                    self.solved = True
                    return Answer("solved", n.get("comment", ""), reply, n.get("reply_comment", ""))
                return Answer("correct", n.get("comment", ""), reply, n.get("reply_comment", ""))
        for w in self.node.get("wrong", []):
            if w["move"].upper() == gtp:
                reply = from_gtp(w["reply"], size) if w.get("reply") else None
                if reply is not None:
                    try:
                        self.game.play(reply)
                    except IllegalMove:
                        reply = None
                self.failed = True
                return Answer("wrong", w.get("comment", ""), reply)
        self.failed = True
        return Answer("unknown", "")

    def expected_moves(self) -> list[str]:
        return [n["move"] for n in self.node.get("next", [])]
