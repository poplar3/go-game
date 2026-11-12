"""Подсчёт очков по китайским (площадь) и японским (территория) правилам."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .board import BLACK, EMPTY, WHITE, Board, Point, other


@dataclass
class ScoreResult:
    rules: str
    komi: float
    territory: dict[int, int]
    stones: dict[int, int]
    prisoners: dict[int, int]  # пленники + мёртвые камни соперника
    dead: set[Point]
    owner: dict[Point, int]  # чья территория у каждого пустого/мёртвого пункта
    total: dict[int, float] = field(default_factory=dict)

    @property
    def winner(self) -> Optional[int]:
        if self.total[BLACK] > self.total[WHITE]:
            return BLACK
        if self.total[WHITE] > self.total[BLACK]:
            return WHITE
        return None

    @property
    def margin(self) -> float:
        return abs(self.total[BLACK] - self.total[WHITE])

    def result_string(self) -> str:
        w = self.winner
        if w is None:
            return "Ничья (джиго)"
        return f"{'Чёрные' if w == BLACK else 'Белые'} побеждают с перевесом {self.margin:g} оч."

    def sgf_result(self) -> str:
        w = self.winner
        if w is None:
            return "0"
        return f"{'B' if w == BLACK else 'W'}+{self.margin:g}"

    def details(self) -> str:
        lines = []
        if self.rules == "chinese":
            lines.append("Китайские правила: камни на доске + окружённые пустые пункты.")
            for c, name in ((BLACK, "Чёрные"), (WHITE, "Белые")):
                extra = f" + коми {self.komi:g}" if c == WHITE else ""
                lines.append(f"{name}: камни {self.stones[c]} + территория {self.territory[c]}{extra} = {self.total[c]:g}")
        else:
            lines.append("Японские правила: окружённые пустые пункты + пленники (включая мёртвые камни).")
            for c, name in ((BLACK, "Чёрные"), (WHITE, "Белые")):
                extra = f" + коми {self.komi:g}" if c == WHITE else ""
                lines.append(f"{name}: территория {self.territory[c]} + пленники {self.prisoners[c]}{extra} = {self.total[c]:g}")
        lines.append(self.result_string())
        return "\n".join(lines)


def score(board: Board, rules: str, komi: float, captures: dict[int, int],
          dead: Optional[set[Point]] = None) -> ScoreResult:
    """Подсчитывает результат. `dead` — камни, которые игроки признали мёртвыми."""
    dead = set(dead or ())
    b = board.copy()
    prisoners = dict(captures)
    for p in dead:
        c = b.get(p)
        if c != EMPTY:
            prisoners[other(c)] += 1
            b.set(p, EMPTY)

    territory = {BLACK: 0, WHITE: 0}
    owner: dict[Point, int] = {}
    seen: set[Point] = set()
    for p in b.points():
        if b.get(p) != EMPTY or p in seen:
            continue
        region = {p}
        border: set[int] = set()
        stack = [p]
        while stack:
            q = stack.pop()
            for nb in b.neighbors(q):
                c = b.get(nb)
                if c == EMPTY:
                    if nb not in region:
                        region.add(nb)
                        stack.append(nb)
                else:
                    border.add(c)
        seen |= region
        if len(border) == 1:
            c = border.pop()
            territory[c] += len(region)
            for q in region:
                owner[q] = c

    stones = {BLACK: 0, WHITE: 0}
    for p in b.points():
        c = b.get(p)
        if c != EMPTY:
            stones[c] += 1

    if rules == "chinese":
        total = {BLACK: float(stones[BLACK] + territory[BLACK]),
                 WHITE: float(stones[WHITE] + territory[WHITE]) + komi}
    else:
        total = {BLACK: float(territory[BLACK] + prisoners[BLACK]),
                 WHITE: float(territory[WHITE] + prisoners[WHITE]) + komi}
    return ScoreResult(rules, komi, territory, stones, prisoners, dead, owner, total)


def dead_from_ownership(board: Board, ownership: list[float], threshold: float = 0.4) -> set[Point]:
    """Определяет мёртвые камни по карте владения от KataGo (значения от -1 до 1, плюс — у чёрных)."""
    dead: set[Point] = set()
    for stones, _ in board.groups():
        color = board.get(next(iter(stones)))
        avg = sum(ownership[p[1] * board.size + p[0]] for p in stones) / len(stones)
        if color == BLACK and avg < -threshold:
            dead |= stones
        elif color == WHITE and avg > threshold:
            dead |= stones
    return dead


def toggle_dead_group(board: Board, dead: set[Point], p: Point) -> set[Point]:
    """Переключает статус группы (жива/мертва) при щелчке в режиме подсчёта."""
    if board.get(p) == EMPTY:
        return dead
    stones, _ = board.group(p)
    dead = set(dead)
    if p in dead:
        dead -= stones
    else:
        dead |= stones
    return dead
