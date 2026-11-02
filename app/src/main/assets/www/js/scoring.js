// Подсчёт очков по китайским (площадь) и японским (территория) правилам.
import { BLACK, WHITE, EMPTY, other } from "./board.js";

export const fmt = (x) => String(Number(x.toFixed(2)));

export class ScoreResult {
  constructor(rules, komi, territory, stones, prisoners, dead, owner, total) {
    Object.assign(this, { rules, komi, territory, stones, prisoners, dead, owner, total });
  }
  get winner() {
    if (this.total[BLACK] > this.total[WHITE]) return BLACK;
    if (this.total[WHITE] > this.total[BLACK]) return WHITE;
    return null;
  }
  get margin() { return Math.abs(this.total[BLACK] - this.total[WHITE]); }
  resultString() {
    const w = this.winner;
    if (w === null) return "Ничья (джиго)";
    return `${w === BLACK ? "Чёрные" : "Белые"} побеждают с перевесом ${fmt(this.margin)} оч.`;
  }
  sgfResult() {
    const w = this.winner;
    if (w === null) return "0";
    return `${w === BLACK ? "B" : "W"}+${this.margin}`;
  }
  details() {
    const lines = [];
    const names = [[BLACK, "Чёрные"], [WHITE, "Белые"]];
    if (this.rules === "chinese") {
      lines.push("Китайские правила: камни на доске + окружённые пустые пункты.");
      for (const [c, name] of names) {
        const extra = c === WHITE ? ` + коми ${fmt(this.komi)}` : "";
        lines.push(`${name}: камни ${this.stones[c]} + территория ${this.territory[c]}${extra} = ${fmt(this.total[c])}`);
      }
    } else {
      lines.push("Японские правила: окружённые пустые пункты + пленники (включая мёртвые камни).");
      for (const [c, name] of names) {
        const extra = c === WHITE ? ` + коми ${fmt(this.komi)}` : "";
        lines.push(`${name}: территория ${this.territory[c]} + пленники ${this.prisoners[c]}${extra} = ${fmt(this.total[c])}`);
      }
    }
    lines.push(this.resultString());
    return lines.join("\n");
  }
}

// dead — камни, которые игроки признали мёртвыми (Set пунктов)
export function score(board, rules, komi, captures, dead = new Set()) {
  dead = new Set(dead);
  const b = board.copy();
  const prisoners = { [BLACK]: captures[BLACK], [WHITE]: captures[WHITE] };
  for (const p of dead) {
    const c = b.get(p);
    if (c !== EMPTY) { prisoners[other(c)] += 1; b.set(p, EMPTY); }
  }
  const territory = { [BLACK]: 0, [WHITE]: 0 };
  const owner = new Map();
  const seen = new Set();
  for (let p = 0; p < b.n; p++) {
    if (b.get(p) !== EMPTY || seen.has(p)) continue;
    const region = new Set([p]);
    const border = new Set();
    const stack = [p];
    while (stack.length) {
      const q = stack.pop();
      for (const nb of b.neighbors(q)) {
        const c = b.get(nb);
        if (c === EMPTY) { if (!region.has(nb)) { region.add(nb); stack.push(nb); } }
        else border.add(c);
      }
    }
    for (const q of region) seen.add(q);
    if (border.size === 1) {
      const c = [...border][0];
      territory[c] += region.size;
      for (const q of region) owner.set(q, c);
    }
  }
  const stones = { [BLACK]: 0, [WHITE]: 0 };
  for (let p = 0; p < b.n; p++) { const c = b.get(p); if (c !== EMPTY) stones[c]++; }
  const total = rules === "chinese"
    ? { [BLACK]: stones[BLACK] + territory[BLACK], [WHITE]: stones[WHITE] + territory[WHITE] + komi }
    : { [BLACK]: territory[BLACK] + prisoners[BLACK], [WHITE]: territory[WHITE] + prisoners[WHITE] + komi };
  return new ScoreResult(rules, komi, territory, stones, prisoners, dead, owner, total);
}

// Мёртвые камни по карте владения KataGo (от -1 до 1, плюс — у чёрных)
export function deadFromOwnership(board, ownership, threshold = 0.4) {
  const dead = new Set();
  for (const [stones] of board.groups()) {
    const color = board.get([...stones][0]);
    let sum = 0;
    for (const p of stones) sum += ownership[p];
    const avg = sum / stones.size;
    if ((color === BLACK && avg < -threshold) || (color === WHITE && avg > threshold)) for (const p of stones) dead.add(p);
  }
  return dead;
}

export function toggleDeadGroup(board, dead, p) {
  if (board.get(p) === EMPTY) return dead;
  const [stones] = board.group(p);
  const res = new Set(dead);
  if (dead.has(p)) for (const s of stones) res.delete(s);
  else for (const s of stones) res.add(s);
  return res;
}
