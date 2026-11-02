// Правила го: доска, ходы, захват камней, ко, история партии.
// Пункт доски — число p = y * size + x (x — столбец слева направо, y — строка сверху вниз).

export const EMPTY = 0, BLACK = 1, WHITE = 2;
export const GTP_LETTERS = "ABCDEFGHJKLMNOPQRST"; // буква I пропускается по традиции

export const other = (c) => (c === BLACK ? WHITE : BLACK);

export function colorName(color, cas = "nom") {
  const names = {
    [BLACK]: { nom: "чёрные", gen: "чёрных", short: "Чёрные" },
    [WHITE]: { nom: "белые", gen: "белых", short: "Белые" },
  };
  return names[color][cas];
}

export const xy = (p, size) => [p % size, Math.floor(p / size)];
export const pt = (x, y, size) => y * size + x;

export function toGtp(p, size) {
  if (p === null || p === undefined) return "pass";
  return GTP_LETTERS[p % size] + String(size - Math.floor(p / size));
}

export function fromGtp(s, size) {
  s = String(s).trim().toUpperCase();
  if (s === "PASS" || s === "") return null;
  const x = GTP_LETTERS.indexOf(s[0]);
  const y = size - parseInt(s.slice(1), 10);
  return y * size + x;
}

export class IllegalMove extends Error {}

const NB_CACHE = {};
function neighborTable(size) {
  if (NB_CACHE[size]) return NB_CACHE[size];
  const nb = [], dg = [];
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const r = [];
    if (x > 0) r.push(y * size + x - 1);
    if (x < size - 1) r.push(y * size + x + 1);
    if (y > 0) r.push((y - 1) * size + x);
    if (y < size - 1) r.push((y + 1) * size + x);
    nb.push(r);
    const d = [];
    for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const a = x + dx, b = y + dy;
      if (a >= 0 && a < size && b >= 0 && b < size) d.push(b * size + a);
    }
    dg.push(d);
  }
  return (NB_CACHE[size] = { nb, dg });
}

export class Board {
  constructor(size = 19) {
    this.size = size;
    this.grid = new Uint8Array(size * size);
    this.koPoint = null; // пункт, куда нельзя ходить из-за ко
    this._t = neighborTable(size);
  }

  copy() {
    const b = new Board(this.size);
    b.grid.set(this.grid);
    b.koPoint = this.koPoint;
    return b;
  }

  get(p) { return this.grid[p]; }
  set(p, c) { this.grid[p] = c; }
  neighbors(p) { return this._t.nb[p]; }
  diagonals(p) { return this._t.dg[p]; }
  get n() { return this.size * this.size; }

  // Возвращает [камни группы (Set), её дамэ (Set)]
  group(p) {
    const color = this.grid[p];
    const stones = new Set([p]);
    const libs = new Set();
    const stack = [p];
    while (stack.length) {
      const q = stack.pop();
      for (const nb of this._t.nb[q]) {
        const c = this.grid[nb];
        if (c === color && !stones.has(nb)) { stones.add(nb); stack.push(nb); }
        else if (c === EMPTY) libs.add(nb);
      }
    }
    return [stones, libs];
  }

  groups(color = null) {
    const seen = new Set();
    const res = [];
    for (let p = 0; p < this.n; p++) {
      const c = this.grid[p];
      if (c === EMPTY || seen.has(p) || (color !== null && c !== color)) continue;
      const g = this.group(p);
      for (const s of g[0]) seen.add(s);
      res.push(g);
    }
    return res;
  }

  isLegal(color, p) {
    try { this.copy().play(color, p); return true; } catch (e) { if (e instanceof IllegalMove) return false; throw e; }
  }

  // Делает ход и возвращает список снятых камней
  play(color, p) {
    if (p === null || p === undefined) { this.koPoint = null; return []; }
    if (p < 0 || p >= this.n) throw new IllegalMove("за пределами доски");
    if (this.grid[p] !== EMPTY) throw new IllegalMove("пункт занят");
    if (p === this.koPoint) throw new IllegalMove("ко: сразу отбить камень нельзя, сначала нужно сходить в другом месте");
    this.grid[p] = color;
    const captured = [];
    const opp = other(color);
    for (const nb of this._t.nb[p]) {
      if (this.grid[nb] === opp) {
        const [stones, libs] = this.group(nb);
        if (libs.size === 0) for (const s of stones) { this.grid[s] = EMPTY; captured.push(s); }
      }
    }
    const [stones, libs] = this.group(p);
    if (libs.size === 0) {
      this.grid[p] = EMPTY;
      throw new IllegalMove("самоубийство: у камня не остаётся дамэ");
    }
    // Простое ко: один камень снял ровно один камень и сам остался с одним дамэ
    this.koPoint = (captured.length === 1 && stones.size === 1 && libs.size === 1) ? captured[0] : null;
    return captured;
  }

  // Пустой пункт, окружённый своими камнями (возможный глаз)
  isEyeLike(p, color) {
    if (this.grid[p] !== EMPTY) return false;
    for (const nb of this._t.nb[p]) if (this.grid[nb] !== color) return false;
    const diag = this._t.dg[p];
    let bad = 0;
    for (const d of diag) if (this.grid[d] === other(color)) bad++;
    if (diag.length < 4) return bad === 0;
    return bad <= 1;
  }

  ascii() {
    const sym = ".XO";
    const rows = [];
    for (let y = 0; y < this.size; y++) {
      let r = "";
      for (let x = 0; x < this.size; x++) r += sym[this.grid[y * this.size + x]];
      rows.push(r);
    }
    return rows.join("\n");
  }

  static fromAscii(rows) {
    const size = rows.length;
    const b = new Board(size);
    rows.forEach((row, y) => {
      row = row.replace(/ /g, "");
      for (let x = 0; x < row.length && x < size; x++) {
        const ch = row[x];
        if ("XxB".includes(ch)) b.set(y * size + x, BLACK);
        else if ("OoW".includes(ch)) b.set(y * size + x, WHITE);
      }
    });
    return b;
  }
}

export class Game {
  constructor(size = 19, komi = 7.5, rules = "chinese", handicap = 0, initial = null, toPlay = null) {
    this.size = size;
    this.komi = komi;
    this.rules = rules; // "chinese" или "japanese"
    this.handicap = handicap;
    this.initial = initial ? initial.copy() : new Board(size);
    if (handicap >= 2 && !initial) for (const p of handicapPoints(size, handicap)) this.initial.set(p, BLACK);
    if (toPlay === null || toPlay === undefined) toPlay = handicap >= 2 ? WHITE : BLACK;
    this.firstToPlay = toPlay;
    this.moves = []; // {color, point, captured}
    this.boards = [this.initial.copy()];
    this.resigned = null;
  }

  get board() { return this.boards[this.boards.length - 1]; }
  get toPlay() { return this.moves.length ? other(this.moves[this.moves.length - 1].color) : this.firstToPlay; }

  captures(upto = null) {
    const res = { [BLACK]: 0, [WHITE]: 0 };
    const ms = upto === null ? this.moves : this.moves.slice(0, upto);
    for (const m of ms) res[m.color] += m.captured.length;
    return res;
  }

  play(point) {
    const color = this.toPlay;
    const b = this.board.copy();
    const captured = b.play(color, point);
    const m = { color, point: point ?? null, captured };
    this.moves.push(m);
    this.boards.push(b);
    return m;
  }

  undo() {
    if (!this.moves.length) return null;
    this.boards.pop();
    return this.moves.pop();
  }

  consecutivePasses() {
    let n = 0;
    for (let i = this.moves.length - 1; i >= 0; i--) { if (this.moves[i].point !== null) break; n++; }
    return n;
  }

  isOver() { return this.resigned !== null || this.consecutivePasses() >= 2; }

  gtpMoves(upto = null) {
    const ms = upto === null ? this.moves : this.moves.slice(0, upto);
    return ms.map((m) => [m.color === BLACK ? "B" : "W", toGtp(m.point, this.size)]);
  }

  initialStonesGtp() {
    const res = [];
    for (let p = 0; p < this.initial.n; p++) {
      const c = this.initial.get(p);
      if (c !== EMPTY) res.push([c === BLACK ? "B" : "W", toGtp(p, this.size)]);
    }
    return res;
  }

  toPlayAt(n) { return n === 0 ? this.firstToPlay : other(this.moves[n - 1].color); }
}

// Стандартная расстановка форы (на пунктах хоси)
export function handicapPoints(size, n) {
  const edge = size < 13 ? 2 : 3;
  const lo = edge, hi = size - 1 - edge, mid = Math.floor(size / 2);
  const P = (x, y) => y * size + x;
  const corners = [P(hi, lo), P(lo, hi), P(hi, hi), P(lo, lo)];
  if (n <= 4) return corners.slice(0, n);
  if (n === 5) return [...corners, P(mid, mid)];
  if (n === 6) return [...corners, P(lo, mid), P(hi, mid)];
  if (n === 7) return [...corners, P(lo, mid), P(hi, mid), P(mid, mid)];
  if (n === 8) return [...corners, P(lo, mid), P(hi, mid), P(mid, lo), P(mid, hi)];
  return [...corners, P(lo, mid), P(hi, mid), P(mid, lo), P(mid, hi), P(mid, mid)];
}

export function starPoints(size) {
  let c;
  if (size === 19) c = [3, 9, 15];
  else if (size === 13) return [[3, 3], [3, 9], [9, 3], [9, 9], [6, 6]].map(([x, y]) => y * size + x);
  else if (size === 9) return [[2, 2], [2, 6], [6, 2], [6, 6], [4, 4]].map(([x, y]) => y * size + x);
  else return [];
  const r = [];
  for (const x of c) for (const y of c) r.push(y * size + x);
  return r;
}
