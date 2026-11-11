"""Объяснение ходов простым языком.

Объяснение складывается из двух источников:
1. Тактический разбор позиции самой программой (атари, захват, спасение группы,
   лестница, глаза, соединение и разрезание). Работает всегда, даже без ИИ.
2. Оценка KataGo: сколько очков стоит ход, что было лучше, какие группы из-за
   хода живут или умирают и какие области переходят к сопернику.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .board import BLACK, EMPTY, Board, Point, other, to_gtp, from_gtp
from .engine.katago import Analysis


# ---------------------------------------------------------------- места на доске

def area_name(p: Point, size: int) -> str:
    x, y = p
    edge = 3 if size <= 9 else (4 if size <= 13 else 6)
    left, right = x < edge, x >= size - edge
    top, bottom = y < edge, y >= size - edge
    if top and left:
        return "в левом верхнем углу"
    if top and right:
        return "в правом верхнем углу"
    if bottom and left:
        return "в левом нижнем углу"
    if bottom and right:
        return "в правом нижнем углу"
    if top:
        return "вверху"
    if bottom:
        return "внизу"
    if left:
        return "слева"
    if right:
        return "справа"
    return "в центре"


def group_area(stones: set[Point], size: int) -> str:
    xs = sorted(p[0] for p in stones)
    ys = sorted(p[1] for p in stones)
    return area_name((xs[len(xs) // 2], ys[len(ys) // 2]), size)


def stones_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} камень"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} камня"
    return f"{n} камней"


def points_word(x: float) -> str:
    n = int(round(abs(x)))
    if n % 10 == 1 and n % 100 != 11:
        w = "очко"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        w = "очка"
    else:
        w = "очков"
    return f"{abs(x):.1f}".rstrip("0").rstrip(".") + f" {w}" if abs(x) < 10 else f"{n} {w}"


def points_gen(x: float) -> str:
    """Родительный падеж: «около 1 очка», «около 5 очков»."""
    n = abs(x)
    num = f"{n:.1f}".rstrip("0").rstrip(".") if n < 10 else str(int(round(n)))
    return f"{num} {'очка' if num == '1' or '.' in num else 'очков'}"


def line_of(p: Point, size: int) -> int:
    x, y = p
    return min(x, y, size - 1 - x, size - 1 - y) + 1


def _genitive_stones(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} камня"
    return f"{n} камней"


# ---------------------------------------------------------------- тактическое чтение

def capture_search(board: Board, target: Point, attacker: int, attacker_to_move: bool, depth: int = 0,
                   max_depth: int = 80) -> bool:
    """Можно ли захватить группу с камнем target (лестница/простая погоня)?

    Чтение ограничено: если у группы 3 и больше дамэ, считаем, что она убежала.
    """
    if board.get(target) == EMPTY or board.get(target) == attacker:
        return True
    if depth > max_depth:
        return False
    defender = other(attacker)
    stones, libs = board.group(target)
    if attacker_to_move:
        if len(libs) == 1:
            return True
        if len(libs) >= 3:
            return False
        for lib in libs:
            b = board.copy()
            try:
                b.play(attacker, lib)
            except Exception:
                continue
            # собственный камень атакующего не должен сам попасть под захват, иначе защита съест его
            if capture_search(b, target, attacker, False, depth + 1, max_depth):
                return True
        return False
    else:
        if len(libs) >= 3:
            return False
        candidates = set(libs)
        # защитник может спастись, захватив окружающие камни, находящиеся в атари
        for s in stones:
            for nb in board.neighbors(s):
                if board.get(nb) == attacker:
                    ast, alibs = board.group(nb)
                    if len(alibs) == 1:
                        candidates |= alibs
        for mv in candidates:
            b = board.copy()
            try:
                b.play(defender, mv)
            except Exception:
                continue
            if not capture_search(b, target, attacker, True, depth + 1, max_depth):
                return False
        return True


def eye_points(board: Board, stones: set[Point], color: int) -> set[Point]:
    """Пустые пункты, похожие на настоящие глаза группы."""
    res = set()
    for s in stones:
        for nb in board.neighbors(s):
            if board.is_eye_like(nb, color):
                res.add(nb)
    return res


@dataclass
class MoveFacts:
    """Что делает ход с точки зрения тактики."""
    sentences: list[str] = field(default_factory=list)
    captured: int = 0
    atari_groups: list[set[Point]] = field(default_factory=list)
    saved: bool = False
    self_atari: bool = False
    fills_own_eye: bool = False
    illegal: Optional[str] = None


def tactical_facts(board: Board, color: int, p: Optional[Point], opening: bool = True) -> MoveFacts:
    facts = MoveFacts()
    size = board.size
    if p is None:
        facts.sentences.append("Пас: игрок пропускает ход.")
        return facts
    opp = other(color)
    after = board.copy()
    try:
        captured = after.play(color, p)
    except Exception as e:
        facts.illegal = str(e)
        facts.sentences.append(f"Этот ход невозможен: {e}.")
        return facts
    S = facts.sentences
    my_stones, my_libs = after.group(p)

    # Захват
    if captured:
        facts.captured = len(captured)
        S.append(f"Забирает {stones_word(len(captured))} соперника.")
        if after.ko_point is not None:
            S.append("Это ко: соперник не сможет сразу отбить камень и должен сначала сыграть в другом месте (угрозу ко).")

    # Заполнение собственного глаза
    if board.is_eye_like(p, color):
        facts.fills_own_eye = True
        S.append("Ход заполняет собственный глаз. Это почти всегда ошибка: группе для жизни нужны два глаза.")

    # Спасение своих групп из атари
    for nb in board.neighbors(p):
        if board.get(nb) == color:
            st, lb = board.group(nb)
            if len(lb) == 1:
                if len(my_libs) >= 2:
                    if capture_search(after, p, opp, True):
                        S.append(f"Пытается спасти {_acc(board, st)} из атари, но это не помогает: "
                                 f"соперник всё равно поймает группу в лестницу или сеть.")
                    else:
                        facts.saved = True
                        S.append(f"Спасает {_acc(board, st)} из атари: у группы теперь {len(my_libs)} дамэ.")
                break
    if captured and not facts.saved:
        for st, lb in board.groups(color):
            if len(lb) != 1 or p in lb:
                continue
            after_libs = after.group(next(iter(st)))[1]
            if len(after_libs) >= 2:
                S.append(f"Захват заодно спасает из атари {_acc(board, st)}.")
                facts.saved = True
                break

    # Атари и давление
    seen: set[Point] = set()
    for nb in after.neighbors(p):
        if after.get(nb) == opp and nb not in seen:
            st, lb = after.group(nb)
            seen |= st
            before_libs = board.group(nb)[1]
            if len(lb) == 1:
                facts.atari_groups.append(st)
                if len(my_libs) == 1 and not captured:
                    continue  # атари из положения, где сам под атари — опишем ниже
                if capture_search(after, nb, color, False):
                    S.append(f"Ставит атари: {_nom(after, st)} не может убежать — "
                             f"если соперник попробует вытянуть камни, получится лестница или сеть, и он потеряет ещё больше.")
                else:
                    S.append(f"Ставит атари: у {_gen(after, st)} осталось одно дамэ, его нужно срочно спасать.")
            elif len(lb) == 2 and len(before_libs) > 2:
                if capture_search(after, nb, color, False):
                    S.append(f"{_nom(after, st).capitalize()} попадает в ловушку (лестница или сеть): "
                             f"убежать уже не получится.")
                elif len(st) >= 2:
                    S.append(f"Сокращает дамэ: у {_gen(after, st)} остаётся только 2 дамэ.")
            elif len(lb) == 3 and len(before_libs) > 3 and len(st) >= 2:
                S.append(f"Давит на {_acc(after, st)}: у неё остаётся 3 дамэ, ей становится тесно.")

    # Самоатари
    if len(my_libs) == 1 and not captured:
        facts.self_atari = True
        if len(my_stones) == 1 and _is_snapback_like(after, p, color):
            S.append("Камень жертвуется: соперник может его снять, но тогда сам попадёт под захват (снэпбэк) "
                     "или потеряет форму. Жертва — важный приём.")
        else:
            S.append(f"Опасно: после хода {_nom(after, my_stones)} оказывается в атари, "
                     f"и соперник может это снять.")

    # Соединение и разрезание
    own_groups = {frozenset(board.group(nb)[0]) for nb in board.neighbors(p) if board.get(nb) == color}
    if len(own_groups) >= 2:
        S.append(f"Соединяет {len(own_groups)} группы в одну: соединённые камни сильнее и их труднее окружить.")
    opp_groups = {frozenset(board.group(nb)[0]) for nb in board.neighbors(p) if board.get(nb) == opp}
    if len(opp_groups) >= 2 and not captured:
        S.append("Встаёт между камнями соперника и разрезает их: разделённые группы слабее.")
    elif _is_cut_diagonal(board, p, opp):
        S.append("Разрезает камни соперника по диагонали.")

    # Глаза
    for st, _ in board.groups(opp):
        if _near(st, p):
            e_before = len(eye_points(board, st, opp))
            if after.get(next(iter(st))) != opp:
                continue
            st_after = after.group(next(iter(st)))[0]
            e_after = len(eye_points(after, st_after, opp))
            if e_after < e_before:
                S.append(f"Разрушает глаз у {_gen(after, st_after)}: без двух глаз группа не может жить.")
                break
    st_after = my_stones
    st_before_union: set[Point] = set()
    for g in own_groups:
        st_before_union |= set(g)
    if st_before_union:
        e_before = len(eye_points(board, st_before_union, color))
        e_after = len(eye_points(after, st_after, color))
        if e_after > e_before and not facts.fills_own_eye:
            S.append("Помогает своей группе сделать глаз.")

    # Дебют
    stones_on_board = sum(1 for q in board.points() if board.get(q) != EMPTY)
    if opening and stones_on_board < max(6, size // 2) and not S:
        line = line_of(p, size)
        area = area_name(p, size)
        if "угл" in area:
            corner = {"в левом верхнем углу": "левый верхний угол", "в правом верхнем углу": "правый верхний угол",
                      "в левом нижнем углу": "левый нижний угол", "в правом нижнем углу": "правый нижний угол"}[area]
            S.append(f"Занимает {corner}: в начале партии углы самые ценные, "
                     f"там территорию окружить легче всего.")
        if line == 3:
            S.append("3-я линия — линия территории: камень надёжно забирает край.")
        elif line == 4:
            S.append("4-я линия — линия влияния: камень смотрит в центр, но территория под ним менее надёжна.")
        elif line <= 2:
            S.append("В начале партии ходы на 1-й и 2-й линии слишком низкие: они берут мало территории.")
    return facts


def _near(stones: set[Point], p: Point, dist: int = 2) -> bool:
    return any(abs(s[0] - p[0]) + abs(s[1] - p[1]) <= dist for s in stones)


def _is_cut_diagonal(board: Board, p: Point, opp: int) -> bool:
    x, y = p
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        a, b, c = (x + dx, y), (x, y + dy), (x + dx, y + dy)
        if all(board.on_board(q) for q in (a, b, c)):
            if board.get(a) == opp and board.get(b) == opp and board.get(c) == other(opp):
                if board.group(a)[0] != board.group(b)[0]:
                    return True
    return False


def _is_snapback_like(after: Board, p: Point, color: int) -> bool:
    lib = next(iter(after.group(p)[1]))
    b = after.copy()
    try:
        b.play(other(color), lib)
    except Exception:
        return False
    st, lb = b.group(lib)
    return len(lb) == 1 and len(st) >= 2


def _nom(board: Board, stones: set[Point]) -> str:
    if len(stones) == 1:
        return f"камень {to_gtp(next(iter(stones)), board.size)}"
    return f"группа из {_genitive_stones(len(stones))} {group_area(stones, board.size)}"


def _gen(board: Board, stones: set[Point]) -> str:
    if len(stones) == 1:
        return f"камня {to_gtp(next(iter(stones)), board.size)}"
    return f"группы из {_genitive_stones(len(stones))} {group_area(stones, board.size)}"


def _acc(board: Board, stones: set[Point]) -> str:
    if len(stones) == 1:
        return f"камень {to_gtp(next(iter(stones)), board.size)}"
    return f"группу из {_genitive_stones(len(stones))} {group_area(stones, board.size)}"


# ---------------------------------------------------------------- оценка ИИ

def verdict(loss: float) -> tuple[str, str]:
    """Оценка хода по потере очков: (название, знак)."""
    if loss < 0.5:
        return "отличный ход", "!"
    if loss < 1.5:
        return "хороший ход", ""
    if loss < 3.5:
        return "неточность", "?!"
    if loss < 8:
        return "ошибка", "?"
    return "грубая ошибка", "??"


def _sign(color: int) -> int:
    return 1 if color == BLACK else -1


def _yours(board: Board, stones: set[Point]) -> str:
    return ("ваш " if len(stones) == 1 else "ваша ") + _nom(board, stones)


def group_status_changes(board_after: Board, color: int, own_ref: list[float], own_new: list[float]) -> list[str]:
    """Сравнивает оценку жизни групп при лучшей игре (own_ref) и после хода (own_new)."""
    S = []
    size = board_after.size
    for stones, _ in board_after.groups():
        c = board_after.get(next(iter(stones)))
        s = _sign(c)
        ref = sum(s * own_ref[q[1] * size + q[0]] for q in stones) / len(stones)
        new = sum(s * own_new[q[1] * size + q[0]] for q in stones) / len(stones)
        if len(stones) < 2 and abs(ref - new) < 1.0:
            continue  # одиночные камни упоминаем, только если их судьба меняется резко
        if c == color and ref > 0.25 and new < -0.25:
            S.append(f"После этого хода погибает {_yours(board_after, stones)}, "
                     f"хотя при правильной игре это можно было предотвратить.")
        elif c != color and ref < -0.25 and new > 0.25:
            S.append(f"Упущена возможность: лучший ход оставлял без жизни {_acc(board_after, stones)} соперника, "
                     f"а теперь соперник успевает спастись.")
    return S


def territory_shift(color: int, own_ref: list[float], own_new: list[float], size: int) -> tuple[float, Optional[str]]:
    """Сколько пунктов (по оценке владения) переходит к сопернику и где."""
    s = _sign(color)
    lost_pts = []
    total = 0.0
    for i in range(size * size):
        d = s * (own_new[i] - own_ref[i])
        if d < -0.3:
            lost_pts.append((i % size, i // size))
            total += -d / 2  # владение меняется от +1 до -1, значит пункт стоит 2 единицы
    if not lost_pts:
        return 0.0, None
    xs = sorted(p[0] for p in lost_pts)
    ys = sorted(p[1] for p in lost_pts)
    return total, area_name((xs[len(xs) // 2], ys[len(ys) // 2]), size)


def _dist(a: Point, b: Point) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def pv_text(pv: list[str], first_color: int, limit: int = 6) -> str:
    out = []
    c = first_color
    for mv in pv[:limit]:
        out.append(("Ч " if c == BLACK else "Б ") + ("пас" if mv.lower() == "pass" else mv))
        c = other(c)
    return ", ".join(out)


@dataclass
class MoveReview:
    move_number: int
    color: int
    point: Optional[Point]
    loss: float
    winrate_before: float  # для игрока, сделавшего ход
    winrate_after: float
    best_move: Optional[str]
    best_pv: list[str]
    text: str
    label: str
    mark: str


def review_move(board_before: Board, color: int, point: Optional[Point], move_number: int,
                before: Analysis, after: Optional[Analysis]) -> MoveReview:
    """Полное объяснение одного хода на основе анализа до и после него."""
    size = board_before.size
    s = _sign(color)
    gtp = to_gtp(point, size)
    best = before.best
    best_value = s * (best.score_lead if best else before.score_lead)
    if after is not None:
        played_value = s * after.score_lead
        wr_after = after.winrate if color == BLACK else 1 - after.winrate
    else:
        info = before.info_for(gtp)
        played_value = s * info.score_lead if info else best_value
        wr_after = (info.winrate if color == BLACK else 1 - info.winrate) if info else 0.5
    best_wr = best.winrate if best else before.winrate
    wr_before = best_wr if color == BLACK else 1 - best_wr
    loss = max(0.0, best_value - played_value)
    is_best = best is not None and best.move.upper() == gtp.upper()
    if is_best:
        loss = 0.0
    label, mark = verdict(loss)

    who = "Чёрные" if color == BLACK else "Белые"
    lines = [f"Ход {move_number}: {who} {gtp if point else 'пас'} — {label}"
             + (f" (потеря около {points_gen(loss)})" if loss >= 0.5 else "") + "."]

    facts = tactical_facts(board_before, color, point)
    if facts.sentences:
        lines.append("Что делает ход: " + " ".join(facts.sentences))

    bp = from_gtp(best.move, size) if best is not None else None
    if not is_best and loss >= 0.5 and after is not None:
        board_after = board_before.copy()
        try:
            board_after.play(color, point)
        except Exception:
            pass
        reasons: list[str] = []
        if before.ownership and after.ownership:
            reasons += group_status_changes(board_after, color, before.ownership, after.ownership)
        # Чем соперник ответит: его лучший ход после нашей ошибки
        threat = after.best
        tp = from_gtp(threat.move, size) if threat is not None else None
        if tp is not None:
            tf = tactical_facts(board_after, other(color), tp)
            t_txt = f"Теперь соперник может сыграть {threat.move}"
            if tf.sentences and not tf.illegal:
                t_txt += " — " + _lower_first(" ".join(tf.sentences))
            else:
                t_txt += f" {area_name(tp, size)} — это самое ценное место на доске сейчас."
            reasons.append(t_txt if t_txt.endswith(".") else t_txt + ".")
        if bp is not None and point is not None and _dist(bp, point) >= 4:
            reasons.append(f"Ход сделан в стороне от главного: важнее всего было играть {area_name(bp, size)}.")
        if bp is not None and tp is not None and _dist(bp, tp) <= 2 and bp != point:
            reasons.append(f"Лучший ход {best.move} занимал этот важный район первым и не давал сопернику "
                           f"сыграть {threat.move} с такой пользой.")
        if before.ownership and after.ownership:
            lost, where = territory_shift(color, before.ownership, after.ownership, size)
            if lost >= 1.5 and where:
                reasons.append(f"По оценке ИИ, около {points_gen(lost)} {where} переходит к сопернику.")
        if reasons:
            lines.append("Почему это хуже: " + " ".join(reasons))

    if best is not None and not is_best and loss >= 0.5:
        bf = tactical_facts(board_before, color, bp)
        txt = f"Лучше было {best.move}."
        if bf.sentences and not bf.illegal:
            txt += " " + " ".join(bf.sentences)
        lines.append(txt)
        if best.pv:
            lines.append("Ожидаемое продолжение: " + pv_text(best.pv, color) + ".")
    elif is_best:
        lines.append("ИИ считает этот ход лучшим в позиции.")
        if best and len(best.pv) > 1:
            lines.append("Ожидаемое продолжение: " + pv_text(best.pv, color) + ".")

    lines.append(f"Шансы на победу ({who.lower()}): {wr_before * 100:.0f}% → {wr_after * 100:.0f}%.")
    return MoveReview(move_number, color, point, loss, wr_before, wr_after,
                      best.move if best else None, best.pv if best else [], "\n".join(lines), label, mark)


def _lower_first(t: str) -> str:
    return t[:1].lower() + t[1:] if t else t


def offline_explanation(board_before: Board, color: int, point: Optional[Point], move_number: int) -> str:
    """Объяснение без ИИ: только тактический разбор."""
    who = "Чёрные" if color == BLACK else "Белые"
    facts = tactical_facts(board_before, color, point)
    head = f"Ход {move_number}: {who} {to_gtp(point, board_before.size) if point else 'пас'}."
    body = " ".join(facts.sentences) if facts.sentences else (
        "Явных тактических последствий нет: ход строит позицию. "
        "Подробную оценку (сколько очков стоит ход и что было лучше) даёт ИИ KataGo.")
    warn = _ignored_atari(board_before, color, point)
    return "\n".join(x for x in (head, body, warn) if x)


def _ignored_atari(board: Board, color: int, point: Optional[Point]) -> str:
    after = board.copy()
    try:
        after.play(color, point)
    except Exception:
        return ""
    for st, lb in after.groups(color):
        if len(lb) == 1 and len(st) >= 2 and (point is None or point not in st):
            return f"Внимание: {_nom(after, st)} остаётся в атари — соперник может её снять."
    return ""
