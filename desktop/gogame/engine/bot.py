"""Уровни силы бота и выбор хода по анализу KataGo."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from ..board import Point, from_gtp
from .katago import Analysis


@dataclass(frozen=True)
class BotLevel:
    name: str
    description: str
    mode: str  # "simple" — встроенный бот, "policy" — интуиция нейросети, "search" — поиск
    temperature: float = 1.0
    visits: int = 1
    needs_engine: bool = True


LEVELS: list[BotLevel] = [
    BotLevel("Новичок", "Встроенный бот на простых правилах. Работает без KataGo.", "simple", needs_engine=False),
    BotLevel("Начинающий", "Нейросеть со случайными отклонениями: часто ошибается.", "policy", temperature=2.2),
    BotLevel("Любитель", "Играет по интуиции нейросети, иногда ошибается.", "policy", temperature=1.0),
    BotLevel("Сильный любитель", "Всегда выбирает самый естественный ход нейросети.", "policy", temperature=0.25),
    BotLevel("Мастер", "Короткий поиск вариантов (50 просмотров).", "search", visits=50),
    BotLevel("Профи", "Глубокий поиск (400 просмотров). Сильнее любого человека.", "search", visits=400),
]

DEFAULT_LEVEL = 2


def choose_from_analysis(level: BotLevel, analysis: Analysis, size: int, opponent_passed: bool,
                         rng: Optional[random.Random] = None) -> Optional[Point]:
    """Возвращает ход бота (None — пас)."""
    rng = rng or random.Random()
    if level.mode == "search" or not analysis.policy:
        best = analysis.best
        if best is None or best.move.lower() == "pass":
            return None
        return from_gtp(best.move, size)

    policy = analysis.policy
    n = size * size
    pass_prob = policy[n] if len(policy) > n else 0.0
    best_search = analysis.best
    # Пас, если нейросеть считает его лучшим, или соперник спасовал и играть больше негде
    if pass_prob > 0.5 or (opponent_passed and best_search is not None and best_search.move.lower() == "pass"):
        return None
    candidates = []
    top = max(policy[:n]) if n else 0
    for i in range(n):
        p = policy[i]
        if p <= 0 or p < top * 0.002:
            continue
        candidates.append((i, p ** (1.0 / level.temperature)))
    if not candidates:
        return None
    total = sum(w for _, w in candidates)
    r = rng.random() * total
    for i, w in candidates:
        r -= w
        if r <= 0:
            return (i % size, i // size)
    i = candidates[-1][0]
    return (i % size, i // size)
