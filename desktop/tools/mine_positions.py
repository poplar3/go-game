"""Поиск учебных позиций в партиях KataGo против самого себя (для задач середины игры и ёсэ).
Запуск: python tools/mine_positions.py <число партий> <seed> > out.txt"""
import random
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gogame.board import BLACK, Game, from_gtp, to_gtp  # noqa: E402
from gogame.engine.katago import KataGo, find_katago  # noqa: E402
from gogame.explain import tactical_facts  # noqa: E402


def ask(k, g, visits):
    ev = threading.Event()
    r = {}

    def cb(a):
        r["a"] = a
        ev.set()
    k.analyze_position(g, cb, visits=visits)
    ev.wait(600)
    return r["a"]


def main(n_games, seed, start=14, min_gap=2.5):
    rng = random.Random(seed)
    exe, model = find_katago()
    k = KataGo(exe, model)
    k.start()
    k.wait_ready()
    for gi in range(n_games):
        g = Game(9, 7.0, "japanese")
        while not g.is_over() and len(g.moves) < 80:
            a = ask(k, g, 40)
            moves = [m for m in a.moves[:3] if m.visits >= 3]
            m = moves[0] if (rng.random() < 0.75 or len(moves) == 1) else rng.choice(moves[1:])
            g.play(from_gtp(m.move, 9))
        for n in range(start, len(g.moves)):
            sub = Game(9, 7.0, "japanese")
            for mv in g.moves[:n]:
                sub.play(mv.point)
            a = ask(k, sub, 200)
            s = 1 if sub.to_play == BLACK else -1
            ms = [m for m in a.moves if m.visits >= 10]
            if len(ms) < 2 or ms[0].move == "pass":
                continue
            gap = s * (ms[0].score_lead - ms[1].score_lead)
            if gap < min_gap:
                continue
            p = from_gtp(ms[0].move, 9)
            facts = tactical_facts(sub.board, sub.to_play, p, opening=False)
            print(f"=== game{gi} move{n} to_play {'B' if s == 1 else 'W'} best {ms[0].move} gap {gap:.1f} "
                  f"leadB {a.score_lead:.1f}")
            print(sub.board.ascii())
            print(" top:", [(m.move, round(s * (m.score_lead - ms[0].score_lead), 1)) for m in ms[:5]])
            print(" pv:", ms[0].pv[:8])
            print(" facts:", " ".join(facts.sentences))
            sys.stdout.flush()
    k.stop()


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), *(float(a) if '.' in a else int(a) for a in sys.argv[3:]))
