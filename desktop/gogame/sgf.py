"""Минимальное чтение и запись SGF (основная ветка партии)."""

from __future__ import annotations

import re
from typing import Optional

from .board import BLACK, EMPTY, WHITE, Board, Game, Point


def _pt(p: Optional[Point]) -> str:
    if p is None:
        return ""
    return chr(ord("a") + p[0]) + chr(ord("a") + p[1])


def _unpt(s: str, size: int) -> Optional[Point]:
    if not s or (s == "tt" and size <= 19):
        return None
    return (ord(s[0]) - ord("a"), ord(s[1]) - ord("a"))


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("]", "\\]")


def save_sgf(game: Game, result: str = "", comments: Optional[dict[int, str]] = None) -> str:
    rules = "Chinese" if game.rules == "chinese" else "Japanese"
    head = f"(;GM[1]FF[4]CA[UTF-8]AP[GoTrainer:1.0]SZ[{game.size}]KM[{game.komi:g}]RU[{rules}]"
    if game.handicap >= 2:
        head += f"HA[{game.handicap}]"
    if result:
        head += f"RE[{result}]"
    ab = [p for p in game.initial.points() if game.initial.get(p) == BLACK]
    aw = [p for p in game.initial.points() if game.initial.get(p) == WHITE]
    if ab:
        head += "AB" + "".join(f"[{_pt(p)}]" for p in ab)
    if aw:
        head += "AW" + "".join(f"[{_pt(p)}]" for p in aw)
    if game.first_to_play == WHITE and not game.moves:
        head += "PL[W]"
    parts = [head]
    for i, m in enumerate(game.moves, start=1):
        node = f";{'B' if m.color == BLACK else 'W'}[{_pt(m.point)}]"
        if comments and comments.get(i):
            node += f"C[{_esc(comments[i])}]"
        parts.append(node)
    return "\n".join(parts) + ")\n"


_PROP = re.compile(r"([A-Z]+)((?:\s*\[(?:\\.|[^\]\\])*\])+)", re.S)
_VAL = re.compile(r"\[((?:\\.|[^\]\\])*)\]", re.S)


def load_sgf(text: str) -> Game:
    # Берём только основную ветку: отрезаем всё после первой вложенной вариации
    depth = 0
    main = []
    for ch in text:
        if ch == "(":
            depth += 1
            if depth > 1:
                break
            continue
        if ch == ")":
            break
        main.append(ch)
    body = "".join(main)
    nodes = [n for n in body.split(";") if n.strip()]
    props_list = []
    for n in nodes:
        props: dict[str, list[str]] = {}
        for m in _PROP.finditer(n):
            props.setdefault(m.group(1), []).extend(v.replace("\\]", "]") for v in _VAL.findall(m.group(2)))
        props_list.append(props)
    root = props_list[0] if props_list else {}
    size = int(root.get("SZ", ["19"])[0].split(":")[0])
    komi = float(root.get("KM", ["6.5"])[0] or 6.5)
    ru = root.get("RU", ["Japanese"])[0].lower()
    rules = "chinese" if ru.startswith("chin") else "japanese"
    init = Board(size)
    for v in root.get("AB", []):
        p = _unpt(v, size)
        if p:
            init.set(p, BLACK)
    for v in root.get("AW", []):
        p = _unpt(v, size)
        if p:
            init.set(p, WHITE)
    to_play = None
    if "PL" in root:
        to_play = WHITE if root["PL"][0].upper().startswith("W") else BLACK
    ha = int(root.get("HA", ["0"])[0] or 0)
    has_init = any(init.get(p) != EMPTY for p in init.points())
    game = Game(size, komi, rules, handicap=ha, initial=init if has_init else None, to_play=to_play)
    for props in props_list:
        for key, color in (("B", BLACK), ("W", WHITE)):
            if key in props:
                p = _unpt(props[key][0], size)
                if game.to_play != color:
                    # SGF может содержать два хода подряд одним цветом — вставляем пас
                    game.play(None)
                game.play(p)
    return game
