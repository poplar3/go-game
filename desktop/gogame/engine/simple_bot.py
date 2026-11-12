"""Простой встроенный бот на эвристиках. Используется, когда KataGo не установлен.

Играет слабо (уровень новичка), но честно соблюдает правила и понимает базовую
тактику: забирает камни в атари, спасает свои, не заполняет свои глаза.
"""

from __future__ import annotations

import random
from typing import Optional

from ..board import EMPTY, Board, Point, other


def _line(p: Point, size: int) -> int:
    x, y = p
    return min(x, y, size - 1 - x, size - 1 - y) + 1


def _region(board: Board, p: Point) -> tuple[int, set[int]]:
    region = {p}
    borders: set[int] = set()
    stack = [p]
    while stack:
        q = stack.pop()
        for nb in board.neighbors(q):
            c = board.get(nb)
            if c == EMPTY:
                if nb not in region:
                    region.add(nb)
                    stack.append(nb)
            else:
                borders.add(c)
    return len(region), borders


def evaluate_move(board: Board, color: int, p: Point, last: Optional[Point], rng: random.Random) -> Optional[float]:
    if board.get(p) != EMPTY:
        return None
    if board.is_eye_like(p, color):
        return None  # свой глаз не заполняем
    region_size, borders = _region(board, p)
    if borders == {color} and region_size < board.size * board.size // 3:
        return None  # своя окружённая территория: ход туда ничего не даёт
    b = board.copy()
    try:
        captured = b.play(color, p)
    except Exception:
        return None
    size = board.size
    opp = other(color)
    score = rng.random() * 2.0

    # 1. Захват камней соперника
    score += 12 * len(captured)

    # 2. Спасение своих групп, бывших в атари
    for nb in board.neighbors(p):
        if board.get(nb) == color:
            stones, libs = board.group(nb)
            if len(libs) == 1:
                _, new_libs = b.group(p)
                if len(new_libs) >= 2:
                    score += 10 * len(stones)

    # 3. Атари и давление на соперника
    for nb in b.neighbors(p):
        if b.get(nb) == opp:
            stones, libs = b.group(nb)
            if len(libs) == 1:
                score += 4 + 2 * len(stones)
            elif len(libs) == 2:
                score += 1

    # 4. Не ставим атари сами себе
    stones, libs = b.group(p)
    if len(libs) == 1 and not captured:
        score -= 15 + 3 * len(stones)
    elif len(libs) == 2:
        score -= 1

    # 5. Дебют: 3-я и 4-я линии ценнее края и центра
    move_no = sum(1 for q in board.points() if board.get(q) != EMPTY)
    line = _line(p, size)
    if move_no < size * 1.5:
        score += {1: -6, 2: -2, 3: 3, 4: 3}.get(line, 1)
    else:
        if line == 1:
            score -= 2

    # 6. Играть рядом с камнями и последним ходом, но не вплотную к своим без причины
    near_opp = sum(1 for q in board.neighbors(p) if board.get(q) == opp)
    near_own = sum(1 for q in board.neighbors(p) if board.get(q) == color)
    score += 0.6 * near_opp - 0.3 * max(0, near_own - 1)
    if last is not None:
        d = abs(last[0] - p[0]) + abs(last[1] - p[1])
        if d <= 3:
            score += 1.5

    # 7. Не играть внутри явной территории соперника, где камень сразу окружён
    if near_opp >= 3 and not captured:
        score -= 4
    if borders == {opp} and region_size <= 6 and not captured:
        score -= 6
    return score


def choose_move(board: Board, color: int, last: Optional[Point] = None, seed: Optional[int] = None) -> Optional[Point]:
    rng = random.Random(seed)
    best: Optional[Point] = None
    best_score = 0.0  # если ничего не лучше нуля — пас
    for p in board.points():
        s = evaluate_move(board, color, p, last, rng)
        if s is not None and s > best_score:
            best, best_score = p, s
    return best
