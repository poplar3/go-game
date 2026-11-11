"""Проверка задач на жизнь и смерть с помощью KataGo.

Для каждого правильного варианта и каждой ошибки (с ответом соперника) печатается,
кому по оценке KataGo принадлежат группы из 3+ камней (+1 — чёрным, −1 — белым).
Для задач без дерева решений перебираются все ходы внутри окружённых областей.
Запуск: python tools/verify_problems.py 5-1 6-2 ...
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gogame.board import Game, from_gtp  # noqa: E402
from gogame.engine.katago import KataGo, find_katago  # noqa: E402
from gogame.problems import load, local_region  # noqa: E402

VISITS = 300


def status(k, p, seq):
    g = Game(p.size, 0.0, "japanese", initial=p.initial_board(), to_play=p.to_play)
    for m in seq:
        g.play(from_gtp(m, p.size))
    ev = threading.Event()
    r = {}

    def cb(a):
        r["a"] = a
        ev.set()
    k.analyze_position(g, cb, visits=VISITS)
    ev.wait(600)
    a = r["a"]
    b = g.board
    out = []
    for st, _ in b.groups():
        if len(st) >= 3:
            c = "Ч" if b.get(next(iter(st))) == 1 else "Б"
            own = sum(a.ownership[q[1] * b.size + q[0]] for q in st) / len(st)
            out.append(f"{c}{len(st)}:{own:+.2f}")
    return " ".join(out)


def main(ids):
    exe, model = find_katago()
    k = KataGo(exe, model)
    k.start()
    assert k.wait_ready() and not k.error, k.error
    _, problems = load()
    for p in problems:
        if ids and p.id not in ids:
            continue
        print(f"\n[{p.id}] {p.title}   исходно: {status(k, p, [])}")
        if not p.tree.get("next"):
            for mv in local_region(p.initial_board()):
                print(f"   кандидат {mv}: {status(k, p, [mv])}")
            continue

        def walk(node, seq):
            for n in node.get("next", []):
                s2 = seq + [n["move"]] + ([n["reply"]] if n.get("reply") else [])
                if not n.get("next"):
                    print(f"   верно {' '.join(s2)}: {status(k, p, s2)}")
                walk(n, s2)
            for w in node.get("wrong", []):
                s2 = seq + [w["move"]] + ([w["reply"]] if w.get("reply") else [])
                print(f"   ошибка {' '.join(s2)}: {status(k, p, s2)}")
        walk(p.tree, [])
    k.stop()


if __name__ == "__main__":
    main(sys.argv[1:])
