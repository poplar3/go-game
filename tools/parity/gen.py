# Генерирует позиции и эталонные объяснения из настольной версии (Python) для проверки JS-порта.
import json, random, sys
sys.path.insert(0, sys.argv[1])
from gogame.board import Game, BLACK, WHITE, to_gtp
from gogame.engine.simple_bot import choose_move
from gogame.explain import tactical_facts, offline_explanation, review_move
from gogame.engine.katago import Analysis
from gogame.scoring import score
rng = random.Random(5)
out = []
for gi in range(60):
    size = rng.choice([9, 9, 13, 19])
    g = Game(size, 7.5, rng.choice(["chinese", "japanese"]))
    n = rng.randint(5, size * size // 2)
    for i in range(n):
        last = g.moves[-1].point if g.moves else None
        p = choose_move(g.board, g.to_play, last, seed=rng.randint(0, 10**6)) if rng.random() < 0.8 else None
        if p is None:
            empties = [q for q in g.board.points() if g.board.get(q) == 0 and g.board.is_legal(g.to_play, q)]
            if not empties: break
            p = rng.choice(empties)
        g.play(p)
    b = g.board
    rows = b.ascii().split("\n")
    color = g.to_play
    cases = []
    pts = [q for q in b.points() if b.get(q) == 0]
    for q in rng.sample(pts, min(25, len(pts))):
        f = tactical_facts(b, color, q)
        cases.append({"p": q[1]*size+q[0], "facts": f.sentences, "offline": offline_explanation(b, color, q, n + 1)})
    def fake(turn):
        mv = []
        for k in range(3):
            q = rng.choice(pts)
            mv.append({"move": to_gtp(q, size), "visits": 10, "winrate": rng.random(), "scoreLead": rng.uniform(-20, 20),
                       "prior": 0.1, "pv": [to_gtp(rng.choice(pts), size) for _ in range(rng.randint(1, 7))]})
        mv.sort(key=lambda m: -m["scoreLead"] * (1 if color == BLACK else -1))
        return {"turnNumber": turn, "rootInfo": {"winrate": rng.random(), "scoreLead": rng.uniform(-10, 10)}, "moveInfos": mv,
                "ownership": [rng.uniform(-1, 1) for _ in range(size*size)]}
    reviews = []
    for k in range(5):
        q = rng.choice(pts)
        if not b.is_legal(color, q): continue
        a0, a1 = fake(n), fake(n + 1)
        if k == 0: a1["moveInfos"][0]["move"] = a0["moveInfos"][0]["move"]
        r = review_move(b, color, q, n + 1, Analysis.from_json(a0, size), Analysis.from_json(a1, size) if k != 1 else None)
        reviews.append({"p": q[1]*size+q[0], "a0": a0, "a1": a1 if k != 1 else None, "text": r.text, "loss": r.loss})
    dead = set(rng.sample([q for q in b.points() if b.get(q) != 0], min(3, sum(1 for q in b.points() if b.get(q) != 0))))
    sc = score(b, g.rules, g.komi, g.captures(), dead)
    out.append({"rows": rows, "color": color, "cases": cases, "reviews": reviews, "rules": g.rules,
                "caps": [g.captures()[BLACK], g.captures()[WHITE]], "dead": [q[1]*size+q[0] for q in dead], "score": sc.details()})
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
