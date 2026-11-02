// Сравнивает JS-порт с эталоном из Python (gen.py).
import fs from "fs";
const W = "../../app/src/main/assets/www/js/";
const { Board, BLACK, WHITE } = await import(W + "board.js");
const { tacticalFacts, offlineExplanation, reviewMove } = await import(W + "explain.js");
const { score } = await import(W + "scoring.js");
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const an = (d, size) => d && ({ turn: d.turnNumber, winrate: d.rootInfo.winrate, scoreLead: d.rootInfo.scoreLead,
  moves: d.moveInfos.map((m) => ({ ...m })), ownership: d.ownership, policy: null, size });
let ok = 0, bad = 0;
const cmp = (a, b, what) => { if (JSON.stringify(a) === JSON.stringify(b)) ok++; else { bad++; if (bad < 8) console.log("DIFF", what, "\n JS:", a, "\n PY:", b); } };
for (const g of data) {
  const b = Board.fromAscii(g.rows);
  for (const c of g.cases) {
    cmp(tacticalFacts(b, g.color, c.p).sentences, c.facts, "facts");
    cmp(offlineExplanation(b, g.color, c.p, 0).split("\n").slice(1), c.offline.split("\n").slice(1), "offline");
  }
  for (const r of g.reviews) {
    const n = parseInt(r.text.match(/^Ход (\d+)/)[1]);
    cmp(reviewMove(b, g.color, r.p, n, an(r.a0, b.size), an(r.a1, b.size)).text, r.text, "review");
  }
  cmp(score(b, g.rules, g.rules === "chinese" ? 7.5 : 7.5, { [BLACK]: g.caps[0], [WHITE]: g.caps[1] }, new Set(g.dead)).details(), g.score, "score");
}
console.log("ok", ok, "bad", bad);
