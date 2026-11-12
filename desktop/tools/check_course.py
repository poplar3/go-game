"""Проверка задач курса через KataGo.

Для каждой задачи: лучший ход по мнению ИИ в исходной позиции, а для каждого первого хода из дерева
(правильного и ошибочного) — сколько очков он теряет относительно лучшего и кому после него принадлежат
группы из 3+ камней. Для правильных вариантов дополнительно проверяется вся линия до конца.
Запуск: python tools/check_course.py [id ...] [--visits N]
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gogame.board import BLACK, from_gtp, to_gtp  # noqa: E402
from gogame.engine.katago import KataGo, find_katago  # noqa: E402
from gogame.problems import ProblemSession, load  # noqa: E402


def ask(k, game, visits, allow=None):
    ev = threading.Event()
    r = {}

    def cb(a):
        r["a"] = a
        ev.set()
    k.analyze_position(game, cb, visits=visits, allow_moves=allow)
    ev.wait(900)
    return r["a"]


def groups(board, a):
    out = []
    for st, _ in board.groups():
        if len(st) >= 3:
            c = "X" if board.get(next(iter(st))) == BLACK else "O"
            own = sum(a.ownership[q[1] * board.size + q[0]] for q in st) / len(st)
            out.append(f"{c}{len(st)}@{to_gtp(min(st), board.size)}:{own:+.1f}")
    return " ".join(out)


def main(ids, visits):
    exe, model = find_katago()
    k = KataGo(exe, model)
    k.start()
    assert k.wait_ready() and not k.error, k.error
    _, problems = load(include_imported=False)
    for p in problems:
        if ids and p.id not in ids:
            continue
        s = ProblemSession(p)
        me = s.game.to_play
        sign = 1 if me == BLACK else -1
        root = ask(k, s.game, visits)
        best = sign * root.moves[0].score_lead
        print(f"\n[{p.id}] {p.title}  best {root.moves[0].move}  top:",
              [(m.move, round(sign * m.score_lead - best, 1)) for m in root.moves[:6]], flush=True)
        print("   исходно:", groups(s.game.board, root))
        for kind in ("next", "wrong"):
            for n in p.tree.get(kind, []):
                s2 = ProblemSession(p)
                s2.game.play(from_gtp(n["move"], p.size))
                a = ask(k, s2.game, visits)
                val = sign * a.moves[0].score_lead
                loss = best - val
                line = f"   {'ВЕРНО ' if kind == 'next' else 'ошибка'} {n['move']:4} потеря {loss:+5.1f}  "
                # продолжение по дереву для правильных
                seq = [n["move"]]
                node = n
                s3 = ProblemSession(p)
                if kind == "next":
                    s3.play(from_gtp(n["move"], p.size))
                while kind == "next" and node.get("next"):
                    node = node["next"][0]
                    s3.play(from_gtp(node["move"], p.size))
                    seq.append(node["move"])
                if kind == "next" and len(seq) > 1:
                    a3 = ask(k, s3.game, visits)
                    line += f"| конец линии {' '.join(seq)}: {groups(s3.game.board, a3)}"
                else:
                    line += groups(s2.game.board, a)
                print(line, flush=True)
    k.stop()


if __name__ == "__main__":
    args = sys.argv[1:]
    v = 300
    if "--visits" in args:
        i = args.index("--visits")
        v = int(args[i + 1])
        del args[i:i + 2]
    main(args, v)
