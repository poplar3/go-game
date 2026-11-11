"""Импорт задач из SGF-файлов (сборники цумэго с сайтов и из книг).

Поддерживаются два вида файлов.

1. Обычный задачник: в корне расстановка (AB/AW), условие (C или GN), кто ходит (PL), а решения
   и ошибки — вариантами. Правильные варианты помечены в комментарии словами RIGHT / Correct /
   правильно / верно. Если пометок нет, правильным считается главный вариант.
2. «Лекция» (так устроены файлы, сконвертированные из обучающих программ, например wbaduk):
   каждый вариант корня — отдельная диаграмма со своей расстановкой. Первая диаграмма — условие,
   остальные — ответы; правильные подписаны «Correct», остальные считаются ошибками.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..board import BLACK, WHITE, Board, GTP_LETTERS, IllegalMove

RIGHT_RE = re.compile(r"\bRIGHT\b|(?i:(?<!in)correct|success|solution|answer|правильн|верно|решено)|"
                      r"正解|正确|成功|정해|정답|성공")
WRONG_RE = re.compile(r"(?i:wrong|incorrect|not correct|fail|mistake|неверно|ошибк)|失败|错|실패|오답")
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\ufffd]")
RTF_GROUP_RE = re.compile(r"\{\\\*?(?:colortbl|stylesheet|fonttbl)(?:[^{}]|\{[^{}]*\})*\}")
RTF_HEX_RE = re.compile(r"(?:\\'[0-9a-fA-F]{2})+")
RTF_WORD_RE = re.compile(r"\\[a-z]+-?\d* ?")


def strip_rtf(text: str) -> str:
    """Убирает разметку RTF, которую конвертеры оставляют в комментариях. Байты \\'hh — корейский текст
    в кодировке cp949."""
    text = RTF_GROUP_RE.sub("", text)

    def hexrun(m):
        raw = bytes(int(h, 16) for h in re.findall(r"\\'([0-9a-fA-F]{2})", m.group(0)))
        try:
            return raw.decode("cp949")
        except UnicodeDecodeError:
            return ""
    text = RTF_HEX_RE.sub(hexrun, text)
    return RTF_WORD_RE.sub("", text)


class Node:
    def __init__(self):
        self.props: dict[str, list[str]] = {}
        self.children: list["Node"] = []

    @property
    def move(self) -> Optional[tuple[str, str]]:
        for c in ("B", "W"):
            if self.props.get(c):
                return c, self.props[c][0]
        return None

    @property
    def comment(self) -> str:
        return " ".join(self.props.get("C", [])).strip()

    @property
    def has_setup(self) -> bool:
        return "AB" in self.props or "AW" in self.props


def parse_collection(text: str) -> list[Node]:
    """Разбирает SGF-файл (может содержать несколько партий) в деревья узлов."""
    i = 0
    n = len(text)

    def parse_value() -> str:
        nonlocal i
        i += 1  # '['
        out = []
        while i < n and text[i] != "]":
            if text[i] == "\\" and i + 1 < n:
                i += 1
            out.append(text[i])
            i += 1
        i += 1
        return "".join(out)

    def parse_node() -> Node:
        nonlocal i
        node = Node()
        i += 1  # ';'
        while i < n:
            while i < n and text[i].isspace():
                i += 1
            if i >= n or text[i] in "(;)":
                break
            m = re.match(r"[A-Za-z]+", text[i:i + 32])
            if not m:
                i += 1
                continue
            key = "".join(ch for ch in m.group(0) if ch.isupper())
            i += len(m.group(0))
            while i < n and text[i].isspace():
                i += 1
            vals = []
            while i < n and text[i] == "[":
                vals.append(parse_value())
                while i < n and text[i].isspace():
                    i += 1
            node.props.setdefault(key, []).extend(vals)
        return node

    def parse_tree() -> Optional[Node]:
        nonlocal i
        i += 1  # '('
        first: Optional[Node] = None
        last: Optional[Node] = None
        while i < n:
            ch = text[i]
            if ch == ";":
                node = parse_node()
                if first is None:
                    first = node
                else:
                    last.children.append(node)
                last = node
            elif ch == "(":
                sub = parse_tree()
                if sub is not None:
                    if last is None:
                        first = last = sub
                    else:
                        last.children.append(sub)
            elif ch == ")":
                i += 1
                return first
            else:
                i += 1
        return first

    trees = []
    while i < n:
        if text[i] == "(":
            t = parse_tree()
            if t is not None:
                trees.append(t)
        else:
            i += 1
    return trees


# ------------------------------------------------------------------ текст
def decode(raw: bytes) -> str:
    """Определяет кодировку по свойству CA, иначе перебирает распространённые."""
    m = re.search(rb"CA\[([^\]]+)\]", raw[:4000])
    encs = []
    if m:
        ca = m.group(1).decode("ascii", "ignore").strip().lower()
        encs.append({"gb2312": "gb18030", "gbk": "gb18030", "big5": "big5hkscs"}.get(ca, ca))
    encs += ["utf-8-sig", "gb18030", "big5hkscs", "cp1251", "latin-1"]
    for enc in encs:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


# Перевод комментариев сборников на русский: исходный текст -> перевод (tools/translations/*.json)
TRANSLATIONS: dict[str, str] = {}
COLLECT: Optional[set] = None
CYR_RE = re.compile(r"[а-яА-ЯёЁ]")
FOREIGN_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def tr(s: str) -> str:
    """Переводит текст сборника, если для него есть перевод; иначе возвращает как есть."""
    if not s or len(FOREIGN_RE.findall(s)) < 2 or len(CYR_RE.findall(s)) > len(s) // 3:
        return s
    if COLLECT is not None:
        COLLECT.add(s)
    return TRANSLATIONS.get(s, s)


def load_translations(folder: Path) -> None:
    for f in sorted(Path(folder).glob("*.json")):
        TRANSLATIONS.update(json.loads(f.read_text(encoding="utf-8")))


def clean_text(s: str) -> str:
    """Убирает служебный мусор из комментариев: адреса сайтов, пометки конвертеров, текст на
    языках, которые ученик не читает (китайский, корейский, японский)."""
    lines = []
    for line in s.replace("\r", "").split("\n"):
        t = line.strip()
        if not t or "ctf2sgf" in t or "http" in t or "www." in t or t.startswith("<="):
            continue
        if t.count("\ufffd") > 2 or re.search(r"'[0-9a-f]{2}'[0-9a-f]{2}", t):
            continue  # нераспознанная кодировка
        t = t.replace("{", "").replace("}", "")
        t = t.replace("<=", "").strip()
        lines.append(t)
    out = " ".join(lines)
    out = re.sub(r"\s+", " ", out).strip()
    return out


STOCK = re.compile(r"^(black|white|b|w)\s+to\s+(play|move|kill|live|capture)[^.]*\.?\s*", re.I)
MARKER_ONLY = re.compile(r"^(right|correct|correct answer|wrong|incorrect|failure|fail)\s*[.!;:]*\s*", re.I)
DIA_HEAD = re.compile(r"^((dia(gram)?\.?\s*\d*|\d+(st|nd|rd|th)\s+dia\.?)\s*(\([^)]*\))?\s*[-–:.]?\s*)?"
                      r"((correct answer|the correct answer|answer|solution|success|mistake|failure|wrong|right|correct)"
                      r"\b\s*(\([^)]*\))?\s*[-–:.!]?\s*)?", re.I)
NOISE = re.compile(r"^(elementary|intermediate|advanced|pro|problem\s*\d*)\s*[.:]?\s*$", re.I)


def _dedupe(t: str) -> str:
    out = []
    for sent in re.split(r"(?<=[.?!])\s+", t):
        if sent and sent not in out:
            out.append(sent)
    return " ".join(out)


def ru_comment(s: str, correct: bool) -> str:
    """Короткие стандартные пометки переводим, содержательный текст оставляем."""
    t = _dedupe(clean_text(s))
    rest = DIA_HEAD.sub("", t, count=1).strip()
    head = "Верно!" if correct else "Этот ход не работает."
    if not rest:
        return head
    rest = tr(rest)
    if rest == t and correct and RIGHT_RE.search(t) is None:
        return rest
    return f"{head} {rest}"


def task_text(comment: str, player: str) -> str:
    who = "Чёрные" if player == "B" else "Белые"
    t = clean_text(comment)
    goal = ""
    m = STOCK.match(t)
    if m:
        verb = m.group(2).lower()
        goal = {"kill": " и убивают", "live": " и живут", "capture": " и захватывают камни"}.get(verb, "")
        t = t[m.end():].strip()
    t = re.sub(r"^(problem|problem \d+|задача \d+)\s*[.:]?\s*", "", t, flags=re.I)
    t = "" if NOISE.match(t) else tr(_dedupe(t))
    base = f"{who} ходят{goal}."
    return f"{base} {t}".strip() if t else base


# ------------------------------------------------------------------ доска
def _pt(v: str, size: int) -> Optional[str]:
    if len(v) < 2:
        return None
    x, y = ord(v[0]) - 97, ord(v[1]) - 97
    if not (0 <= x < size and 0 <= y < size):
        return None
    return f"{GTP_LETTERS[x]}{size - y}"


def _xy(v: str, size: int) -> Optional[tuple[int, int]]:
    if len(v) < 2:
        return None
    x, y = ord(v[0]) - 97, ord(v[1]) - 97
    if not (0 <= x < size and 0 <= y < size):
        return None
    return x, y


def _expand(vals: list[str]) -> list[str]:
    """Раскрывает сжатые списки пунктов вида aa:cc."""
    out = []
    for v in vals:
        if ":" in v and len(v) == 5:
            a, b = v.split(":", 1)
            for x in range(ord(a[0]), ord(b[0]) + 1):
                for y in range(ord(a[1]), ord(b[1]) + 1):
                    out.append(chr(x) + chr(y))
        else:
            out.append(v)
    return out


def _size(root: Node) -> int:
    try:
        return int(root.props.get("SZ", ["19"])[0].split(":")[0])
    except ValueError:
        return 19


def _apply_setup(b: Board, node: Node) -> None:
    for key, col in (("AB", BLACK), ("AW", WHITE)):
        for v in _expand(node.props.get(key, [])):
            p = _xy(v, b.size)
            if p:
                b.set(p, col)
    for v in _expand(node.props.get("AE", [])):
        p = _xy(v, b.size)
        if p:
            b.set(p, 0)


def _rows(b: Board) -> list[str]:
    return ["".join("X" if b.get((x, y)) == BLACK else "O" if b.get((x, y)) == WHITE else "."
                    for x in range(b.size)) for y in range(b.size)]


def _play(b: Board, color: str, v: str) -> bool:
    p = _xy(v, b.size)
    if p is None:
        return False
    try:
        b.play(BLACK if color == "B" else WHITE, p)
    except IllegalMove:
        return False
    return True


# ------------------------------------------------------------------ формат 1: задачник
def _has_right(node: Node) -> bool:
    c = node.comment
    if c and RIGHT_RE.search(c) and not WRONG_RE.search(c):
        return True
    return any(_has_right(c) for c in node.children)


def _convert(children: list[Node], player: str, size: int, marked_mode: bool, depth: int = 0) -> dict:
    """Узлы-ходы игрока -> {"next": [...], "wrong": [...]}"""
    res: dict = {"next": [], "wrong": []}
    for idx, ch in enumerate(children):
        mv = ch.move
        if mv is None or mv[0] != player:
            continue
        gtp = _pt(mv[1], size)
        if gtp is None or any(n["move"] == gtp for n in res["next"] + res["wrong"]):
            continue
        correct = _has_right(ch) if marked_mode else idx == 0
        replies = [c for c in ch.children if c.move and c.move[0] != player and _pt(c.move[1], size)]
        if correct:
            node: dict = {"move": gtp, "comment": ru_comment(ch.comment, True)}
            # без пометок главный вариант обрывается на первом комментарии — дальше обычно другая диаграмма
            stop = not marked_mode and depth > 0 and bool(clean_text(ch.comment))
            if replies and not stop:
                good = [r for r in replies if (not marked_mode) or _has_right(r)] or replies
                r = good[0]
                node["reply"] = _pt(r.move[1], size)
                rc = clean_text(r.comment)
                node["reply_comment"] = "" if MARKER_ONLY.fullmatch(rc + " ") else tr(MARKER_ONLY.sub("", rc))
                if depth < 40:
                    sub = _convert(r.children, player, size, marked_mode, depth + 1)
                    if sub["next"]:
                        node["next"] = sub["next"]
                    if sub["wrong"]:
                        node["wrong"] = sub["wrong"]
            res["next"].append(node)
        else:
            w = {"move": gtp, "comment": ru_comment(ch.comment, False)}
            if replies:
                w["reply"] = _pt(replies[0].move[1], size)
                rc = clean_text(replies[0].comment)
                rc = MARKER_ONLY.sub("", rc).strip()
                if rc:
                    w["comment"] += " " + tr(rc)
            res["wrong"].append(w)
    return res


def _classic(root: Node, size: int) -> Optional[tuple[list[str], str, dict, str]]:
    b = Board(size)
    node = root
    while True:
        _apply_setup(b, node)
        if node.move is None and len(node.children) == 1 and node.children[0].move is None:
            node = node.children[0]
            continue
        break
    setup_node = node
    first_children = [setup_node] if setup_node.move is not None else setup_node.children
    moves = [c.move for c in first_children if c.move]
    if not moves:
        return None
    player = root.props.get("PL", [moves[0][0]])[0].upper()[:1]
    if player not in ("B", "W"):
        player = moves[0][0]
    marked_mode = any(_has_right(c) for c in first_children)
    tree = _convert(first_children, player, size, marked_mode)
    if not tree["next"]:
        return None
    comment = root.comment or setup_node.comment
    return _rows(b), player, tree, comment


# ------------------------------------------------------------------ формат 2: лекция с диаграммами
def _diagram(root: Node, var: Node, size: int) -> tuple[Board, list[tuple[str, str, str]]]:
    """Расстановка варианта и его главная линия [(цвет, пункт, комментарий)]."""
    b = Board(size)
    _apply_setup(b, root)
    node = var
    _apply_setup(b, node)
    line = []
    while True:
        if node.move:
            line.append((node.move[0], node.move[1], node.comment))
        elif node is not var and node.has_setup:
            break
        elif node is not var and node.comment:
            line.append(("", "", node.comment))
        if not node.children:
            break
        node = node.children[0]
    if var.move is None and var.comment and not any(c for _, _, c in line):
        line.append(("", "", var.comment))
    return b, line


def _lecture(root: Node, size: int) -> Optional[tuple[list[str], str, dict, str]]:
    variations = root.children
    if len(variations) < 2 or not variations[0].has_setup:
        return None
    b0, line0 = _diagram(root, variations[0], size)
    base_rows = _rows(b0)
    for color, v, _ in line0:
        if color and not _play(b0, color, v):
            return None
    prefix = [(c, v) for c, v, _ in line0 if c]
    task = " ".join(c for _, _, c in line0 if c) or variations[0].comment
    diagrams = []
    for var in variations[1:]:
        b, line = _diagram(root, var, size)
        mv = [(c, v) for c, v, _ in line if c]
        text = " ".join(c for _, _, c in line if c)
        diagrams.append((_rows(b), mv, text))
    # Обычно условие — позиция после ходов первой диаграммы. Но бывает, что первая диаграмма показывает
    # неверную попытку, а задача начинается с её исходной расстановки: пробуем оба варианта.
    for target, strip in ((_rows(b0), True), (base_rows, False)):
        res = _lecture_tree(diagrams, target, base_rows, prefix if strip else [], size)
        if res is not None:
            return target, res[0], res[1], task
    return None


def _lecture_tree(diagrams, target, base_rows, prefix, size) -> Optional[tuple[str, dict]]:
    branches = []
    for rows, mv, text in diagrams:
        if prefix and rows == base_rows and mv[:len(prefix)] == prefix:
            mv = mv[len(prefix):]  # диаграмма-ответ повторяет ходы из условия
        elif rows != target:
            continue
        if not mv:
            continue
        verdict = _verdict(text)
        if verdict is None:
            continue  # «вариант», «справка» — не ответ и не ошибка
        branches.append((verdict, mv, text))
    correct = [x for x in branches if x[0]]
    if not correct:
        return None
    player = correct[0][1][0][0]
    tree: dict = {"next": [], "wrong": []}
    for ok, mv, text in sorted(branches, key=lambda x: not x[0]):
        node = tree
        for k in range(0, len(mv), 2):
            color, v = mv[k]
            if color != player:
                break
            gtp = _pt(v, size)
            if gtp is None:
                break
            reply = _pt(mv[k + 1][1], size) if k + 1 < len(mv) and mv[k + 1][0] != player else None
            existing = next((n for n in node.get("next", []) if n["move"] == gtp), None)
            if existing is not None:
                if not ok and existing.get("reply") and reply and existing["reply"] != reply:
                    break  # другой ответ соперника — такую развилку не храним
                node = existing
                continue
            if not ok:
                if gtp not in [w["move"] for w in node.get("wrong", [])]:
                    w = {"move": gtp, "comment": ru_comment(text, False)}
                    if reply:
                        w["reply"] = reply
                    node.setdefault("wrong", []).append(w)
                break
            new = {"move": gtp, "comment": ru_comment(text, True) if node is tree else "Верно, продолжайте."}
            if reply:
                new["reply"] = reply
                new["reply_comment"] = ""
            node.setdefault("next", []).append(new)
            node = new
    _finalize(tree)
    if not tree["next"]:
        return None
    return player, tree


def _verdict(text: str) -> Optional[bool]:
    """Правильный ли ответ, по заголовку диаграммы («Diagram 1 (solution)», «Success», «Mistake»…)."""
    head = clean_text(text)[:70] or text[:70]
    w, r = WRONG_RE.search(head), RIGHT_RE.search(head)
    if w and (not r or w.start() <= r.start()):
        return False
    if r:
        return True
    return None


def _finalize(node: dict) -> None:
    for n in node.get("next", []):
        if not n.get("next") and n.get("comment") == "Верно, продолжайте.":
            n["comment"] = "Верно! Задача решена."
        _finalize(n)


# ------------------------------------------------------------------ общий вход
def tree_to_problem(root: Node, pid: str, level: int, number: int) -> Optional[dict]:
    size = _size(root)
    if size > 19 or size < 5:
        return None
    res = None
    if not root.has_setup and len(root.children) >= 2 and all(c.has_setup or c.move for c in root.children):
        res = _lecture(root, size)
    if res is None:
        res = _classic(root, size)
    if res is None:
        return None
    board, player, tree, comment = res
    if not _valid(board, player, tree, size):
        return None
    name = clean_text(root.props.get("GN", [""])[0] or "")
    task = task_text(comment, player)
    if len(task) > 600:
        task = task[:600] + "…"
    title = name[:60] if name and not name.isdigit() else f"Задача {number}"
    return {
        "id": pid, "level": level, "title": title, "task": task,
        "hint": "Найдите ход, после которого у соперника не будет хорошего ответа. "
                "Если застряли, «Разбор с ИИ» покажет лучший ход.",
        "board": board, "to_play": player, "tree": tree, "marked": [],
        "concept": "", "why": "", "source": "",
    }


def _valid(rows: list[str], player: str, tree: dict, size: int) -> bool:
    """Все ходы дерева должны быть разрешены правилами — иначе задачу не взять."""
    from ..board import Game, from_gtp
    initial = Board.from_ascii(rows)
    color = BLACK if player == "B" else WHITE

    def walk(node: dict, game: Game) -> bool:
        for n in node.get("next", []):
            g = Game(size, 0.0, "japanese", initial=game.board, to_play=game.to_play)
            try:
                g.play(from_gtp(n["move"], size))
                if n.get("reply"):
                    g.play(from_gtp(n["reply"], size))
            except IllegalMove:
                return False
            if not walk(n, g):
                return False
        node["wrong"] = [w for w in node.get("wrong", []) if game.board.is_legal(game.to_play, from_gtp(w["move"], size))]
        if not node["wrong"]:
            node.pop("wrong")
        return True

    return walk(tree, Game(size, 0.0, "japanese", initial=initial, to_play=color))


def file_to_problems(path: Path, level: int, start_number: int = 1, pid_prefix: str = "") -> list[dict]:
    text = strip_rtf(decode(Path(path).read_bytes()))
    out = []
    for k, t in enumerate(parse_collection(text)):
        n = start_number + len(out)
        p = tree_to_problem(t, f"{pid_prefix}{level}-{n}", level, n)
        if p:
            out.append(p)
    return out


def import_files(paths: list[Path]) -> tuple[int, int]:
    """Добавляет задачи из SGF-файлов в imported_problems.json. Возвращает (добавлено, пропущено)."""
    from . import imported_path
    path = imported_path()
    data = {"levels": [], "problems": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    next_level = max([l["level"] for l in data["levels"]] + [999]) + 1
    added = skipped = 0
    # файлы из одной папки — один раздел (в сборниках часто по задаче на файл)
    by_dir: dict[Path, list[Path]] = {}
    for f in paths:
        by_dir.setdefault(Path(f).parent, []).append(Path(f))
    for folder, files in by_dir.items():
        probs: list[dict] = []
        for f in files:
            try:
                got = file_to_problems(f, next_level, len(probs) + 1, pid_prefix="imp")
            except Exception:
                got = []
            if not got:
                skipped += 1
            probs.extend(got)
        if not probs:
            continue
        name = files[0].stem if len(files) == 1 else folder.name
        data["levels"].append({"level": next_level, "title": f"Импорт: {name}",
                               "lesson": f"Задачи из «{name}». Объяснения взяты из комментариев файлов; если их "
                                         f"нет, нажмите «Разбор с ИИ».",
                               "stage": "Мои сборники"})
        data["problems"].extend(probs)
        added += len(probs)
        next_level += 1
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return added, skipped


def clear_imported() -> None:
    from . import imported_path
    p = imported_path()
    if p.exists():
        p.unlink()
