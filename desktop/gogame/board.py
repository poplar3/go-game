"""Правила го: доска, ходы, захват камней, ко, история партии."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

EMPTY, BLACK, WHITE = 0, 1, 2

GTP_LETTERS = "ABCDEFGHJKLMNOPQRST"  # буква I пропускается по традиции

Point = tuple[int, int]  # (x, y): x — столбец слева направо, y — строка сверху вниз


def other(color: int) -> int:
    return WHITE if color == BLACK else BLACK


def color_name(color: int, case: str = "nom") -> str:
    names = {
        BLACK: {"nom": "чёрные", "gen": "чёрных", "short": "Чёрные"},
        WHITE: {"nom": "белые", "gen": "белых", "short": "Белые"},
    }
    return names[color][case]


def to_gtp(point: Optional[Point], size: int) -> str:
    if point is None:
        return "pass"
    x, y = point
    return f"{GTP_LETTERS[x]}{size - y}"


def from_gtp(s: str, size: int) -> Optional[Point]:
    s = s.strip().upper()
    if s in ("PASS", ""):
        return None
    x = GTP_LETTERS.index(s[0])
    y = size - int(s[1:])
    return (x, y)


class IllegalMove(Exception):
    pass


class Board:
    """Состояние доски без истории. Камни хранятся в плоском списке."""

    def __init__(self, size: int = 19):
        self.size = size
        self.grid = [EMPTY] * (size * size)
        self.ko_point: Optional[Point] = None  # точка, куда нельзя ходить из-за ко

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.size = self.size
        b.grid = self.grid[:]
        b.ko_point = self.ko_point
        return b

    def get(self, p: Point) -> int:
        return self.grid[p[1] * self.size + p[0]]

    def set(self, p: Point, color: int) -> None:
        self.grid[p[1] * self.size + p[0]] = color

    def on_board(self, p: Point) -> bool:
        return 0 <= p[0] < self.size and 0 <= p[1] < self.size

    def neighbors(self, p: Point) -> list[Point]:
        x, y = p
        n = self.size
        res = []
        if x > 0:
            res.append((x - 1, y))
        if x < n - 1:
            res.append((x + 1, y))
        if y > 0:
            res.append((x, y - 1))
        if y < n - 1:
            res.append((x, y + 1))
        return res

    def diagonals(self, p: Point) -> list[Point]:
        x, y = p
        return [q for q in ((x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1), (x + 1, y + 1)) if self.on_board(q)]

    def points(self) -> Iterable[Point]:
        for y in range(self.size):
            for x in range(self.size):
                yield (x, y)

    def group(self, p: Point) -> tuple[set[Point], set[Point]]:
        """Возвращает (камни группы, её дамэ)."""
        color = self.get(p)
        stones = {p}
        libs: set[Point] = set()
        stack = [p]
        while stack:
            q = stack.pop()
            for nb in self.neighbors(q):
                c = self.get(nb)
                if c == color and nb not in stones:
                    stones.add(nb)
                    stack.append(nb)
                elif c == EMPTY:
                    libs.add(nb)
        return stones, libs

    def groups(self, color: Optional[int] = None) -> list[tuple[set[Point], set[Point]]]:
        seen: set[Point] = set()
        res = []
        for p in self.points():
            c = self.get(p)
            if c == EMPTY or p in seen or (color is not None and c != color):
                continue
            stones, libs = self.group(p)
            seen |= stones
            res.append((stones, libs))
        return res

    def is_legal(self, color: int, p: Point) -> bool:
        try:
            self.copy().play(color, p)
            return True
        except IllegalMove:
            return False

    def play(self, color: int, p: Optional[Point]) -> list[Point]:
        """Делает ход и возвращает список снятых камней."""
        if p is None:
            self.ko_point = None
            return []
        if not self.on_board(p):
            raise IllegalMove("за пределами доски")
        if self.get(p) != EMPTY:
            raise IllegalMove("пункт занят")
        if p == self.ko_point:
            raise IllegalMove("ко: сразу отбить камень нельзя, сначала нужно сходить в другом месте")
        self.set(p, color)
        captured: list[Point] = []
        opp = other(color)
        for nb in self.neighbors(p):
            if self.get(nb) == opp:
                stones, libs = self.group(nb)
                if not libs:
                    for s in stones:
                        self.set(s, EMPTY)
                    captured.extend(stones)
        stones, libs = self.group(p)
        if not libs:
            self.set(p, EMPTY)
            raise IllegalMove("самоубийство: у камня не остаётся дамэ")
        # Простое ко: один камень снял ровно один камень и сам остался с одним дамэ
        if len(captured) == 1 and len(stones) == 1 and len(libs) == 1:
            self.ko_point = captured[0]
        else:
            self.ko_point = None
        return captured

    def is_eye_like(self, p: Point, color: int) -> bool:
        """Пустой пункт, окружённый своими камнями (возможный глаз)."""
        if self.get(p) != EMPTY:
            return False
        if any(self.get(nb) != color for nb in self.neighbors(p)):
            return False
        diag = self.diagonals(p)
        bad = sum(1 for d in diag if self.get(d) == other(color))
        if len(diag) < 4:  # край или угол
            return bad == 0
        return bad <= 1

    def ascii(self) -> str:
        sym = {EMPTY: ".", BLACK: "X", WHITE: "O"}
        return "\n".join(
            "".join(sym[self.get((x, y))] for x in range(self.size)) for y in range(self.size)
        )

    @classmethod
    def from_ascii(cls, rows: list[str]) -> "Board":
        size = len(rows)
        b = cls(size)
        for y, row in enumerate(rows):
            row = row.replace(" ", "")
            for x, ch in enumerate(row):
                if ch in "XxB":
                    b.set((x, y), BLACK)
                elif ch in "OoW":
                    b.set((x, y), WHITE)
        return b


@dataclass
class Move:
    color: int
    point: Optional[Point]  # None — пас
    captured: list[Point] = field(default_factory=list)


class Game:
    """Партия: начальная позиция, последовательность ходов, правила и коми."""

    def __init__(self, size: int = 19, komi: float = 7.5, rules: str = "chinese", handicap: int = 0,
                 initial: Optional[Board] = None, to_play: Optional[int] = None):
        self.size = size
        self.komi = komi
        self.rules = rules  # "chinese" или "japanese"
        self.handicap = handicap
        self.initial = initial.copy() if initial else Board(size)
        if handicap >= 2 and initial is None:
            for p in handicap_points(size, handicap):
                self.initial.set(p, BLACK)
        if to_play is None:
            to_play = WHITE if handicap >= 2 else BLACK
        self.first_to_play = to_play
        self.moves: list[Move] = []
        self.boards: list[Board] = [self.initial.copy()]
        self.resigned: Optional[int] = None  # цвет сдавшегося

    @property
    def board(self) -> Board:
        return self.boards[-1]

    @property
    def to_play(self) -> int:
        if not self.moves:
            return self.first_to_play
        return other(self.moves[-1].color)

    def captures(self, upto: Optional[int] = None) -> dict[int, int]:
        """Сколько камней соперника снял каждый цвет (пленники)."""
        res = {BLACK: 0, WHITE: 0}
        for m in self.moves[:upto]:
            res[m.color] += len(m.captured)
        return res

    def play(self, point: Optional[Point]) -> Move:
        color = self.to_play
        b = self.board.copy()
        captured = b.play(color, point)
        m = Move(color, point, captured)
        self.moves.append(m)
        self.boards.append(b)
        return m

    def undo(self) -> Optional[Move]:
        if not self.moves:
            return None
        self.boards.pop()
        return self.moves.pop()

    def consecutive_passes(self) -> int:
        n = 0
        for m in reversed(self.moves):
            if m.point is not None:
                break
            n += 1
        return n

    def is_over(self) -> bool:
        return self.resigned is not None or self.consecutive_passes() >= 2

    def gtp_moves(self, upto: Optional[int] = None) -> list[list[str]]:
        return [["B" if m.color == BLACK else "W", to_gtp(m.point, self.size)] for m in self.moves[:upto]]

    def initial_stones_gtp(self) -> list[list[str]]:
        res = []
        for p in self.initial.points():
            c = self.initial.get(p)
            if c != EMPTY:
                res.append(["B" if c == BLACK else "W", to_gtp(p, self.size)])
        return res


def handicap_points(size: int, n: int) -> list[Point]:
    """Стандартная расстановка форы (по традиции на пунктах хоси)."""
    edge = 2 if size < 13 else 3
    lo, hi, mid = edge, size - 1 - edge, size // 2
    # в порядке: правый верх, левый низ, правый низ, левый верх, центр...
    corners = [(hi, lo), (lo, hi), (hi, hi), (lo, lo)]
    pts: list[Point] = []
    if n <= 4:
        pts = corners[:n]
    elif n == 5:
        pts = corners + [(mid, mid)]
    elif n == 6:
        pts = corners + [(lo, mid), (hi, mid)]
    elif n == 7:
        pts = corners + [(lo, mid), (hi, mid), (mid, mid)]
    elif n == 8:
        pts = corners + [(lo, mid), (hi, mid), (mid, lo), (mid, hi)]
    else:
        pts = corners + [(lo, mid), (hi, mid), (mid, lo), (mid, hi), (mid, mid)]
    return pts


def star_points(size: int) -> list[Point]:
    if size == 19:
        c = [3, 9, 15]
    elif size == 13:
        return [(3, 3), (3, 9), (9, 3), (9, 9), (6, 6)]
    elif size == 9:
        return [(2, 2), (2, 6), (6, 2), (6, 6), (4, 4)]
    else:
        return []
    return [(x, y) for x in c for y in c]
