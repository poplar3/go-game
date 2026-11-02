// Рисование доски на canvas и обработка касаний.
import { BLACK, EMPTY, GTP_LETTERS, Board, starPoints } from "./board.js";

export const GREEN = "#1aa34a", RED = "#d93025", BLUE = "#1a5fd0";
const WOOD = "#dcb35c", WOOD_DARK = "#c99f45", LINE = "#3b2a12";

export class BoardView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.board = new Board(9);
    this.lastMove = null;
    this.ghostColor = BLACK;
    this.interactive = true;
    this.labels = new Map(); // пункт -> [текст, цвет]
    this.circles = new Map(); // пункт -> цвет
    this.dead = new Set();
    this.territory = new Map();
    this.ownership = null;
    this.marked = new Set();
    this.view = null; // [x0, y0, x1, y1] — показываемая часть доски
    this.hover = null;
    this.pending = null; // ход, ожидающий подтверждения вторым касанием
    this.confirmTap = () => false;
    this.onClick = null;
    this._bind();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  setBoard(board, lastMove = null) { this.board = board; this.lastMove = lastMove; this.pending = null; this.draw(); }
  clearMarks() {
    this.labels.clear(); this.circles.clear(); this.dead = new Set(); this.territory = new Map();
    this.ownership = null; this.marked = new Set(); this.pending = null; this.draw();
  }

  resize() {
    const parent = this.canvas.parentElement;
    const w = parent.clientWidth;
    const h = Math.min(w, Math.max(240, window.innerHeight * 0.62));
    const side = Math.max(200, Math.min(w, h));
    const dpr = window.devicePixelRatio || 1;
    this.canvas.style.width = side + "px";
    this.canvas.style.height = side + "px";
    this.canvas.width = Math.round(side * dpr);
    this.canvas.height = Math.round(side * dpr);
    this.cssSize = side;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  bounds() {
    const n = this.board.size;
    if (!this.view) return [0, 0, n - 1, n - 1];
    const [x0, y0, x1, y1] = this.view;
    return [Math.max(0, x0), Math.max(0, y0), Math.min(n - 1, x1), Math.min(n - 1, y1)];
  }

  geometry() {
    const [x0, y0, x1, y1] = this.bounds();
    const cols = x1 - x0 + 1, rows = y1 - y0 + 1;
    const W = this.cssSize, H = this.cssSize;
    const cell = Math.min(W / (cols + 0.9), H / (rows + 0.9));
    const ox = (W - cell * (cols - 1)) / 2 - x0 * cell;
    const oy = (H - cell * (rows - 1)) / 2 - y0 * cell;
    return [cell, ox, oy];
  }

  toScreen(p) {
    const [cell, ox, oy] = this.geometry();
    const n = this.board.size;
    return [ox + (p % n) * cell, oy + Math.floor(p / n) * cell];
  }

  toPoint(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    const [cell, ox, oy] = this.geometry();
    const x = Math.round((clientX - r.left - ox) / cell);
    const y = Math.round((clientY - r.top - oy) / cell);
    const [x0, y0, x1, y1] = this.bounds();
    if (x >= x0 && x <= x1 && y >= y0 && y <= y1) return y * this.board.size + x;
    return null;
  }

  _bind() {
    const c = this.canvas;
    let down = false;
    c.addEventListener("pointerdown", (e) => {
      down = true;
      c.setPointerCapture(e.pointerId);
      this.hover = this.toPoint(e.clientX, e.clientY);
      this.draw();
    });
    c.addEventListener("pointermove", (e) => {
      if (!down && e.pointerType !== "mouse") return;
      const p = this.toPoint(e.clientX, e.clientY);
      if (p !== this.hover) { this.hover = p; this.draw(); }
    });
    const finish = (e, cancel) => {
      if (!down) return;
      down = false;
      const p = this.toPoint(e.clientX, e.clientY);
      if (e.pointerType !== "mouse") this.hover = null;
      if (cancel || p === null) { this.draw(); return; }
      const needConfirm = this.confirmTap() && this.interactive && this.ghostColor !== null && this.board.get(p) === EMPTY;
      if (needConfirm && this.pending !== p) { this.pending = p; this.draw(); return; }
      this.pending = null;
      this.draw();
      if (this.onClick) this.onClick(p);
    };
    c.addEventListener("pointerup", (e) => finish(e, false));
    c.addEventListener("pointercancel", (e) => finish(e, true));
    c.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse" && !down) { this.hover = null; this.draw(); } });
  }

  draw() {
    const ctx = this.ctx;
    if (!this.cssSize) return;
    const n = this.board.size;
    const [cell] = this.geometry();
    const [x0, y0, x1, y1] = this.bounds();
    const W = this.cssSize;
    ctx.clearRect(0, 0, W, W);
    const [tlx, tly] = this.toScreen(y0 * n + x0);
    const [brx, bry] = this.toScreen(y1 * n + x1);
    const pad = cell * 0.45;
    ctx.save();
    ctx.fillStyle = WOOD;
    ctx.strokeStyle = WOOD_DARK;
    ctx.lineWidth = 2;
    roundRect(ctx, tlx - pad, tly - pad, brx - tlx + 2 * pad, bry - tly + 2 * pad, 6);
    ctx.fill(); ctx.stroke();
    ctx.beginPath();
    ctx.rect(tlx - pad, tly - pad, brx - tlx + 2 * pad, bry - tly + 2 * pad);
    ctx.clip();

    if (this.ownership) { // карта владения
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        const v = this.ownership[y * n + x];
        if (Math.abs(v) < 0.15) continue;
        ctx.fillStyle = v > 0 ? `rgba(0,0,0,${0.55 * Math.abs(v)})` : `rgba(255,255,255,${0.67 * Math.abs(v)})`;
        const [sx, sy] = this.toScreen(y * n + x);
        const s = cell * 0.9;
        ctx.fillRect(sx - s / 2, sy - s / 2, s, s);
      }
    }
    // сетка
    ctx.strokeStyle = LINE;
    ctx.lineWidth = Math.max(1, cell / 30);
    const ext = (cond) => (cond ? 0 : 0.6 * cell);
    ctx.beginPath();
    for (let i = x0; i <= x1; i++) {
      const [ax, ay] = this.toScreen(y0 * n + i), [, by] = this.toScreen(y1 * n + i);
      ctx.moveTo(ax, ay - ext(y0 === 0)); ctx.lineTo(ax, by + ext(y1 === n - 1));
    }
    for (let i = y0; i <= y1; i++) {
      const [ax, ay] = this.toScreen(i * n + x0), [bx] = this.toScreen(i * n + x1);
      ctx.moveTo(ax - ext(x0 === 0), ay); ctx.lineTo(bx + ext(x1 === n - 1), ay);
    }
    ctx.stroke();
    ctx.fillStyle = LINE;
    for (const p of starPoints(n)) {
      const x = p % n, y = Math.floor(p / n);
      if (x >= x0 && x <= x1 && y >= y0 && y <= y1) {
        const [sx, sy] = this.toScreen(p);
        ctx.beginPath(); ctx.arc(sx, sy, Math.max(2, cell * 0.1), 0, 2 * Math.PI); ctx.fill();
      }
    }
    ctx.restore();

    // координаты (снаружи деревянной рамки, мелко)
    ctx.fillStyle = "#6b5530";
    ctx.font = `${Math.max(8, Math.floor(cell * 0.3))}px sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (let i = x0; i <= x1; i++) {
      const [sx] = this.toScreen(y0 * n + i);
      ctx.fillText(GTP_LETTERS[i], sx, Math.max(6, tly - pad - cell * 0.0) - cell * 0.0 - Math.min(cell * 0.22, (tly - pad) / 2));
    }
    for (let i = y0; i <= y1; i++) {
      const [, sy] = this.toScreen(i * n + x0);
      ctx.fillText(String(n - i), Math.max(6, (tlx - pad) / 2), sy);
    }

    const r = cell * 0.47;
    const inView = (p) => { const x = p % n, y = Math.floor(p / n); return x >= x0 && x <= x1 && y >= y0 && y <= y1; };
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const p = y * n + x, c = this.board.get(p);
      if (c !== EMPTY) this.drawStone(p, c, r, this.dead.has(p) ? 0.35 : 1);
    }
    for (const [p, owner] of this.territory) { // территория при подсчёте
      if (!inView(p)) continue;
      const [sx, sy] = this.toScreen(p);
      const s = cell * 0.3;
      ctx.fillStyle = owner === BLACK ? "#141414" : "#f5f5f5";
      ctx.fillRect(sx - s / 2, sy - s / 2, s, s);
    }
    for (const p of this.marked) { // цели задачи
      if (!inView(p)) continue;
      const [sx, sy] = this.toScreen(p);
      ctx.strokeStyle = "#e03030"; ctx.lineWidth = Math.max(2, cell / 14);
      const s = cell * 0.22;
      ctx.beginPath(); ctx.moveTo(sx - s, sy - s); ctx.lineTo(sx + s, sy + s); ctx.moveTo(sx - s, sy + s); ctx.lineTo(sx + s, sy - s); ctx.stroke();
    }
    if (this.lastMove !== null && inView(this.lastMove) && this.board.get(this.lastMove) !== EMPTY) {
      const [sx, sy] = this.toScreen(this.lastMove);
      ctx.strokeStyle = this.board.get(this.lastMove) === BLACK ? "#fff" : "#000";
      ctx.lineWidth = Math.max(1.5, cell / 18);
      ctx.beginPath(); ctx.arc(sx, sy, r * 0.45, 0, 2 * Math.PI); ctx.stroke();
    }
    for (const [p, col] of this.circles) {
      if (!inView(p)) continue;
      const [sx, sy] = this.toScreen(p);
      ctx.strokeStyle = col; ctx.lineWidth = Math.max(2.5, cell / 10);
      ctx.beginPath(); ctx.arc(sx, sy, r * 0.8, 0, 2 * Math.PI); ctx.stroke();
    }
    ctx.font = `bold ${Math.max(9, Math.floor(cell * 0.42))}px sans-serif`;
    for (const [p, [text, col]] of this.labels) {
      if (!inView(p)) continue;
      const [sx, sy] = this.toScreen(p);
      const stone = this.board.get(p);
      if (stone === EMPTY) {
        ctx.fillStyle = WOOD;
        ctx.beginPath(); ctx.arc(sx, sy, r * 0.6, 0, 2 * Math.PI); ctx.fill();
        ctx.fillStyle = col;
      } else ctx.fillStyle = stone === BLACK ? "#fff" : "#000";
      ctx.fillText(text, sx, sy + 1);
    }
    const ghost = this.pending !== null ? this.pending : this.hover;
    if (this.interactive && ghost !== null && this.ghostColor !== null && this.board.get(ghost) === EMPTY) {
      this.drawStone(ghost, this.ghostColor, r, this.pending !== null ? 0.7 : 0.45);
      if (this.pending !== null) {
        const [sx, sy] = this.toScreen(ghost);
        ctx.strokeStyle = GREEN; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(sx, sy, r * 1.05, 0, 2 * Math.PI); ctx.stroke();
      }
    }
  }

  drawStone(p, color, r, alpha = 1) {
    const ctx = this.ctx;
    const [sx, sy] = this.toScreen(p);
    ctx.save();
    ctx.globalAlpha = alpha;
    const g = ctx.createRadialGradient(sx - r * 0.35, sy - r * 0.35, r * 0.1, sx - r * 0.35, sy - r * 0.35, r * 1.4);
    if (color === BLACK) { g.addColorStop(0, "#666"); g.addColorStop(1, "#0a0a0a"); ctx.strokeStyle = "#000"; }
    else { g.addColorStop(0, "#fff"); g.addColorStop(1, "#cfcfcf"); ctx.strokeStyle = "#777"; }
    ctx.fillStyle = g;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(sx, sy, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    ctx.restore();
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// График шансов чёрных на победу
export class WinrateGraph {
  constructor(canvas) {
    this.canvas = canvas;
    this.values = new Map();
    this.marks = new Map();
    this.total = 0;
    this.current = 0;
    this.onSelect = null;
    canvas.addEventListener("click", (e) => {
      if (!this.total) return;
      const r = canvas.getBoundingClientRect();
      const n = Math.round(((e.clientX - r.left - 5) / Math.max(1, r.width - 10)) * this.total);
      if (this.onSelect) this.onSelect(Math.max(0, Math.min(this.total, n)));
    });
    new ResizeObserver(() => this.draw()).observe(canvas);
  }
  setData(values, total, marks) { this.values = values; this.total = total; this.marks = marks; this.draw(); }
  setCurrent(n) { this.current = n; this.draw(); }
  draw() {
    const c = this.canvas, dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w) return;
    c.width = w * dpr; c.height = h * dpr;
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const X = (n) => 5 + (n / Math.max(1, this.total)) * (w - 10);
    const Y = (v) => 5 + (1 - v) * (h - 10);
    ctx.fillStyle = "#f4f1ea"; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#bbb"; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(5, Y(0.5)); ctx.lineTo(w - 5, Y(0.5)); ctx.stroke();
    ctx.setLineDash([]);
    if (!this.values.size) {
      ctx.fillStyle = "#888"; ctx.font = "12px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("Здесь появится график после разбора партии", w / 2, h / 2);
      return;
    }
    const pts = [...this.values.entries()].sort((a, b) => a[0] - b[0]);
    ctx.beginPath(); ctx.moveTo(X(pts[0][0]), Y(0));
    for (const [n, v] of pts) ctx.lineTo(X(n), Y(v));
    ctx.lineTo(X(pts[pts.length - 1][0]), Y(0)); ctx.closePath();
    ctx.fillStyle = "rgba(40,40,40,0.63)"; ctx.fill();
    for (const [n, mark] of this.marks) {
      if (mark === "?" || mark === "??") {
        ctx.strokeStyle = mark === "??" ? "#d33" : "#e90"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(X(n), 5); ctx.lineTo(X(n), h - 5); ctx.stroke();
      }
    }
    ctx.strokeStyle = "#2a7"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(X(this.current), 0); ctx.lineTo(X(this.current), h); ctx.stroke();
    ctx.fillStyle = "#333"; ctx.font = "11px sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText("чёрные", 6, 3); ctx.textBaseline = "bottom"; ctx.fillText("белые", 6, h - 3);
  }
}
