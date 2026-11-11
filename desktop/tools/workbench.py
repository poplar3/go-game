"""Инструмент разработки задач: оценивает позиции KataGo.
Использование: python tools/workbench.py file.txt
Файл: блоки, разделённые пустой строкой; первая строка блока — "B" или "W" [и ходы через пробел],
дальше строки доски (X/O/.)."""
import sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gogame.board import Board, Game, BLACK, WHITE, from_gtp, to_gtp

def main(path, visits=400):
    from gogame.engine.katago import KataGo, find_katago
    exe, model = find_katago(); k = KataGo(exe, model); k.start(); k.wait_ready()
    blocks = [b.strip("\n") for b in Path(path).read_text().split("\n\n") if b.strip()]
    for blk in blocks:
        lines = blk.split("\n")
        head = lines[0].split()
        rows = [l.strip() for l in lines[1:] if l.strip()]
        board = Board.from_ascii(rows)
        tp = BLACK if head[0] == "B" else WHITE
        g = Game(board.size, 0.0 if len(head) < 2 or not head[1].startswith('k=') else float(head[1][2:]), "japanese", initial=board, to_play=tp)
        for m in [h for h in head[1:] if not h.startswith('k=')]:
            g.play(from_gtp(m, board.size))
        ev = threading.Event(); r = {}
        def cb(a): r['a'] = a; ev.set()
        k.analyze_position(g, cb, visits=visits)
        ev.wait(900); a = r['a']
        s = 1 if g.to_play == BLACK else -1
        best = s * a.moves[0].score_lead
        print("====", " ".join(head), "to_play", "B" if g.to_play == BLACK else "W")
        print("\n".join(rows) if len(head) < 2 else g.board.ascii())
        print(" top:", [(m.move, round(s*m.score_lead - best, 1), m.visits) for m in a.moves[:8]])
        print(" pv:", a.moves[0].pv[:8], " leadB=%.1f" % a.moves[0].score_lead)
        b = g.board
        out = []
        for st, _ in b.groups():
            if len(st) >= 2:
                c = "X" if b.get(next(iter(st))) == BLACK else "O"
                own = sum(a.ownership[q[1]*b.size+q[0]] for q in st)/len(st)
                out.append(f"{c}{len(st)}@{to_gtp(sorted(st)[0], b.size)}:{own:+.1f}")
        print(" groups:", " ".join(out), flush=True)
    k.stop()

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 400)
