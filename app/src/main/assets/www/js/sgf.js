// Минимальное чтение и запись SGF (основная ветка партии).
import { BLACK, WHITE, EMPTY, Board, Game } from "./board.js";

const sgfPt = (p, size) => (p === null ? "" : String.fromCharCode(97 + (p % size)) + String.fromCharCode(97 + Math.floor(p / size)));
function unPt(s, size) {
  if (!s || (s === "tt" && size <= 19)) return null;
  const x = s.charCodeAt(0) - 97, y = s.charCodeAt(1) - 97;
  if (x < 0 || y < 0 || x >= size || y >= size) return null;
  return y * size + x;
}
const esc = (s) => s.replace(/\\/g, "\\\\").replace(/]/g, "\\]");

export function saveSgf(game, result = "", comments = {}) {
  const rules = game.rules === "chinese" ? "Chinese" : "Japanese";
  let head = `(;GM[1]FF[4]CA[UTF-8]AP[GoTrainer:1.0]SZ[${game.size}]KM[${game.komi}]RU[${rules}]`;
  if (game.handicap >= 2) head += `HA[${game.handicap}]`;
  if (result) head += `RE[${result}]`;
  const ab = [], aw = [];
  for (let p = 0; p < game.initial.n; p++) {
    if (game.initial.get(p) === BLACK) ab.push(p);
    else if (game.initial.get(p) === WHITE) aw.push(p);
  }
  if (ab.length) head += "AB" + ab.map((p) => `[${sgfPt(p, game.size)}]`).join("");
  if (aw.length) head += "AW" + aw.map((p) => `[${sgfPt(p, game.size)}]`).join("");
  if (game.firstToPlay === WHITE && !game.moves.length) head += "PL[W]";
  const parts = [head];
  game.moves.forEach((m, i) => {
    let node = `;${m.color === BLACK ? "B" : "W"}[${sgfPt(m.point, game.size)}]`;
    if (comments[i + 1]) node += `C[${esc(comments[i + 1])}]`;
    parts.push(node);
  });
  return parts.join("\n") + ")\n";
}

const PROP = /([A-Z]+)((?:\s*\[(?:\\[\s\S]|[^\]\\])*\])+)/g;
const VAL = /\[((?:\\[\s\S]|[^\]\\])*)\]/g;

export function loadSgf(text) {
  // Только основная ветка: отрезаем всё после первой вложенной вариации
  let depth = 0, body = "";
  for (const ch of text) {
    if (ch === "(") { depth++; if (depth > 1) break; continue; }
    if (ch === ")") break;
    body += ch;
  }
  const nodes = body.split(";").filter((n) => n.trim());
  const propsList = nodes.map((n) => {
    const props = {};
    for (const m of n.matchAll(PROP)) {
      const vals = [...m[2].matchAll(VAL)].map((v) => v[1].replace(/\\]/g, "]"));
      (props[m[1]] = props[m[1]] || []).push(...vals);
    }
    return props;
  });
  const root = propsList[0] || {};
  const size = parseInt((root.SZ || ["19"])[0].split(":")[0], 10) || 19;
  const komi = parseFloat((root.KM || ["6.5"])[0]) || 6.5;
  const ru = (root.RU || ["Japanese"])[0].toLowerCase();
  const rules = ru.startsWith("chin") ? "chinese" : "japanese";
  const init = new Board(size);
  for (const v of root.AB || []) { const p = unPt(v, size); if (p !== null) init.set(p, BLACK); }
  for (const v of root.AW || []) { const p = unPt(v, size); if (p !== null) init.set(p, WHITE); }
  let toPlay = null;
  if (root.PL) toPlay = root.PL[0].toUpperCase().startsWith("W") ? WHITE : BLACK;
  const ha = parseInt((root.HA || ["0"])[0], 10) || 0;
  const hasInit = init.grid.some((c) => c !== EMPTY);
  const game = new Game(size, komi, rules, ha, hasInit ? init : null, toPlay);
  for (const props of propsList) {
    for (const [key, color] of [["B", BLACK], ["W", WHITE]]) {
      if (props[key]) {
        const p = unPt(props[key][0], size);
        if (game.toPlay !== color) game.play(null); // два хода подряд одним цветом — вставляем пас
        game.play(p);
      }
    }
  }
  return game;
}
