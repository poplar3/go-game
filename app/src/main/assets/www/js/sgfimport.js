// Импорт задач из SGF-файлов (сборники цумэго с сайтов и из книг). Порт настольной версии.
// 1. Обычный задачник: расстановка в корне, решения и ошибки — вариантами (пометки RIGHT / Correct / правильно).
//    Если пометок нет, правильным считается главный вариант.
// 2. «Лекция» (файлы, сконвертированные из обучающих программ, например wbaduk): каждый вариант корня —
//    отдельная диаграмма. Первая — условие, остальные — ответы.
import { BLACK, WHITE, Board, Game, GTP_LETTERS, IllegalMove, fromGtp } from "./board.js";

const RIGHT_CS = /\bRIGHT\b|正解|正确|成功|정해|정답|성공/;
const RIGHT_CI = /(?<!in)correct|success|solution|answer|правильн|верно|решено/i;
const WRONG_CS = /失败|错|실패|오답/;
const WRONG_CI = /wrong|incorrect|not correct|fail|mistake|неверно|ошибк/i;

function firstIndex(s, res) {
  let best = -1;
  for (const re of res) { const m = re.exec(s); if (m && (best < 0 || m.index < best)) best = m.index; }
  return best;
}
const rightAt = (s) => firstIndex(s, [RIGHT_CS, RIGHT_CI]);
const wrongAt = (s) => firstIndex(s, [WRONG_CS, WRONG_CI]);

function decodeBytes(bytes, enc) {
  return new TextDecoder(enc, { fatal: true }).decode(bytes);
}

// Убирает разметку RTF; байты \'hh — корейский текст в кодировке cp949
export function stripRtf(text) {
  text = text.replace(/\{\\\*?(?:colortbl|stylesheet|fonttbl)(?:[^{}]|\{[^{}]*\})*\}/g, "");
  text = text.replace(/(?:\\'[0-9a-fA-F]{2})+/g, (m) => {
    const raw = new Uint8Array([...m.matchAll(/\\'([0-9a-fA-F]{2})/g)].map((x) => parseInt(x[1], 16)));
    try { return decodeBytes(raw, "euc-kr"); } catch { return ""; }
  });
  return text.replace(/\\[a-z]+-?\d* ?/g, "");
}

class Node {
  constructor() { this.props = {}; this.children = []; }
  get move() {
    for (const c of ["B", "W"]) if (this.props[c] && this.props[c].length) return [c, this.props[c][0]];
    return null;
  }
  get comment() { return (this.props.C || []).join(" ").trim(); }
  get hasSetup() { return "AB" in this.props || "AW" in this.props; }
}

export function parseCollection(text) {
  let i = 0;
  const n = text.length;
  const isSpace = (ch) => /\s/.test(ch);
  function parseValue() {
    i++;
    let out = "";
    while (i < n && text[i] !== "]") {
      if (text[i] === "\\" && i + 1 < n) i++;
      out += text[i];
      i++;
    }
    i++;
    return out;
  }
  function parseNode() {
    const node = new Node();
    i++;
    while (i < n) {
      while (i < n && isSpace(text[i])) i++;
      if (i >= n || "(;)".includes(text[i])) break;
      const m = /^[A-Za-z]+/.exec(text.slice(i, i + 32));
      if (!m) { i++; continue; }
      const key = [...m[0]].filter((ch) => ch >= "A" && ch <= "Z").join("");
      i += m[0].length;
      while (i < n && isSpace(text[i])) i++;
      const vals = [];
      while (i < n && text[i] === "[") {
        vals.push(parseValue());
        while (i < n && isSpace(text[i])) i++;
      }
      (node.props[key] = node.props[key] || []).push(...vals);
    }
    return node;
  }
  function parseTree() {
    i++;
    let first = null, last = null;
    while (i < n) {
      const ch = text[i];
      if (ch === ";") {
        const node = parseNode();
        if (first === null) first = node; else last.children.push(node);
        last = node;
      } else if (ch === "(") {
        const sub = parseTree();
        if (sub !== null) {
          if (last === null) first = last = sub; else last.children.push(sub);
        }
      } else if (ch === ")") { i++; return first; }
      else i++;
    }
    return first;
  }
  const trees = [];
  while (i < n) {
    if (text[i] === "(") { const t = parseTree(); if (t !== null) trees.push(t); }
    else i++;
  }
  return trees;
}

// Кодировка по свойству CA, иначе перебор распространённых
export function decode(bytes) {
  const head = new TextDecoder("latin1").decode(bytes.subarray(0, 4000));
  const m = /CA\[([^\]]+)\]/.exec(head);
  const encs = [];
  if (m) {
    const ca = m[1].trim().toLowerCase();
    encs.push({ gb2312: "gb18030", gbk: "gb18030", big5: "big5", cp949: "euc-kr", "ks_c_5601-1987": "euc-kr" }[ca] || ca);
  }
  encs.push("utf-8", "gb18030", "big5", "windows-1251");
  for (const enc of encs) {
    try { return decodeBytes(bytes, enc); } catch { /* следующая */ }
  }
  return new TextDecoder("latin1").decode(bytes);
}

// Убирает служебный мусор из комментариев
export function cleanText(s) {
  const lines = [];
  for (const line of s.replace(/\r/g, "").split("\n")) {
    let t = line.trim();
    if (!t || t.includes("ctf2sgf") || t.includes("http") || t.includes("www.") || t.startsWith("<=")) continue;
    if ((t.match(/�/g) || []).length > 2 || /'[0-9a-f]{2}'[0-9a-f]{2}/.test(t)) continue;
    t = t.replace(/[{}]/g, "").replace(/<=/g, "").trim();
    lines.push(t);
  }
  return lines.join(" ").replace(/\s+/g, " ").trim();
}

const STOCK = /^(black|white|b|w)\s+to\s+(play|move|kill|live|capture)[^.]*\.?\s*/i;
const MARKER_ONLY = /^(right|correct|correct answer|wrong|incorrect|failure|fail)\s*[.!;:]*\s*/i;
const DIA_HEAD = /^((dia(gram)?\.?\s*\d*|\d+(st|nd|rd|th)\s+dia\.?)\s*(\([^)]*\))?\s*[-–:.]?\s*)?((correct answer|the correct answer|answer|solution|success|mistake|failure|wrong|right|correct)\b\s*(\([^)]*\))?\s*[-–:.!]?\s*)?/i;
const NOISE = /^(elementary|intermediate|advanced|pro|problem\s*\d*)\s*[.:]?\s*$/i;

function dedupe(t) {
  const out = [];
  for (const sent of t.split(/(?<=[.?!])\s+/)) if (sent && !out.includes(sent)) out.push(sent);
  return out.join(" ");
}

function ruComment(s, correct) {
  const t = dedupe(cleanText(s));
  const rest = t.replace(DIA_HEAD, "").trim();
  const head = correct ? "Верно!" : "Этот ход не работает.";
  if (!rest) return head;
  if (rest === t && correct && rightAt(t) < 0) return rest;
  return `${head} ${rest}`;
}

function taskText(comment, player) {
  const who = player === "B" ? "Чёрные" : "Белые";
  let t = cleanText(comment);
  let goal = "";
  const m = STOCK.exec(t);
  if (m) {
    goal = { kill: " и убивают", live: " и живут", capture: " и захватывают камни" }[m[2].toLowerCase()] || "";
    t = t.slice(m[0].length).trim();
  }
  t = t.replace(/^(problem|problem \d+|задача \d+)\s*[.:]?\s*/i, "");
  t = NOISE.test(t) ? "" : dedupe(t);
  const base = `${who} ходят${goal}.`;
  return t ? `${base} ${t}`.trim() : base;
}

// ------------------------------------------------------------------ доска
function sgfXy(v, size) {
  if (!v || v.length < 2) return null;
  const x = v.charCodeAt(0) - 97, y = v.charCodeAt(1) - 97;
  if (!(x >= 0 && x < size && y >= 0 && y < size)) return null;
  return [x, y];
}
function sgfGtp(v, size) {
  const r = sgfXy(v, size);
  return r ? `${GTP_LETTERS[r[0]]}${size - r[1]}` : null;
}
function expand(vals) {
  const out = [];
  for (const v of vals) {
    if (v.includes(":") && v.length === 5) {
      const [a, b] = v.split(":");
      for (let x = a.charCodeAt(0); x <= b.charCodeAt(0); x++)
        for (let y = a.charCodeAt(1); y <= b.charCodeAt(1); y++) out.push(String.fromCharCode(x) + String.fromCharCode(y));
    } else out.push(v);
  }
  return out;
}
function sizeOf(root) {
  const v = parseInt((root.props.SZ || ["19"])[0].split(":")[0], 10);
  return Number.isNaN(v) ? 19 : v;
}
function applySetup(b, node) {
  for (const [key, col] of [["AB", BLACK], ["AW", WHITE]]) {
    for (const v of expand(node.props[key] || [])) { const r = sgfXy(v, b.size); if (r) b.set(r[1] * b.size + r[0], col); }
  }
  for (const v of expand(node.props.AE || [])) { const r = sgfXy(v, b.size); if (r) b.set(r[1] * b.size + r[0], 0); }
}
const rowsOf = (b) => b.ascii().split("\n");
function playOn(b, color, v) {
  const r = sgfXy(v, b.size);
  if (!r) return false;
  try { b.play(color === "B" ? BLACK : WHITE, r[1] * b.size + r[0]); } catch (e) { if (e instanceof IllegalMove) return false; throw e; }
  return true;
}

// ------------------------------------------------------------------ формат 1: задачник
function hasRight(node) {
  const c = node.comment;
  if (c && rightAt(c) >= 0 && wrongAt(c) < 0) return true;
  return node.children.some(hasRight);
}

function convert(children, player, size, markedMode, depth = 0) {
  const res = { next: [], wrong: [] };
  children.forEach((ch, idx) => {
    const mv = ch.move;
    if (mv === null || mv[0] !== player) return;
    const gtp = sgfGtp(mv[1], size);
    if (gtp === null || [...res.next, ...res.wrong].some((n) => n.move === gtp)) return;
    const correct = markedMode ? hasRight(ch) : idx === 0;
    const replies = ch.children.filter((c) => c.move && c.move[0] !== player && sgfGtp(c.move[1], size));
    if (correct) {
      const node = { move: gtp, comment: ruComment(ch.comment, true) };
      const stop = !markedMode && depth > 0 && Boolean(cleanText(ch.comment));
      if (replies.length && !stop) {
        const good = replies.filter((r) => !markedMode || hasRight(r));
        const r = (good.length ? good : replies)[0];
        node.reply = sgfGtp(r.move[1], size);
        const rc = cleanText(r.comment);
        const full = new RegExp("^(?:" + MARKER_ONLY.source.slice(1) + ")$", "i");
        node.reply_comment = full.test(rc + " ") ? "" : rc.replace(MARKER_ONLY, "");
        if (depth < 40) {
          const sub = convert(r.children, player, size, markedMode, depth + 1);
          if (sub.next.length) node.next = sub.next;
          if (sub.wrong.length) node.wrong = sub.wrong;
        }
      }
      res.next.push(node);
    } else {
      const w = { move: gtp, comment: ruComment(ch.comment, false) };
      if (replies.length) {
        w.reply = sgfGtp(replies[0].move[1], size);
        const rc = cleanText(replies[0].comment).replace(MARKER_ONLY, "").trim();
        if (rc) w.comment += " " + rc;
      }
      res.wrong.push(w);
    }
  });
  return res;
}

function classic(root, size) {
  const b = new Board(size);
  let node = root;
  for (;;) {
    applySetup(b, node);
    if (node.move === null && node.children.length === 1 && node.children[0].move === null) { node = node.children[0]; continue; }
    break;
  }
  const setupNode = node;
  const firstChildren = setupNode.move !== null ? [setupNode] : setupNode.children;
  const moves = firstChildren.filter((c) => c.move).map((c) => c.move);
  if (!moves.length) return null;
  let player = ((root.props.PL || [moves[0][0]])[0] || "").toUpperCase().slice(0, 1);
  if (player !== "B" && player !== "W") player = moves[0][0];
  const markedMode = firstChildren.some(hasRight);
  const tree = convert(firstChildren, player, size, markedMode);
  if (!tree.next.length) return null;
  return [rowsOf(b), player, tree, root.comment || setupNode.comment];
}

// ------------------------------------------------------------------ формат 2: лекция с диаграммами
function diagram(root, v, size) {
  const b = new Board(size);
  applySetup(b, root);
  let node = v;
  applySetup(b, node);
  const line = [];
  for (;;) {
    if (node.move) line.push([node.move[0], node.move[1], node.comment]);
    else if (node !== v && node.hasSetup) break;
    else if (node !== v && node.comment) line.push(["", "", node.comment]);
    if (!node.children.length) break;
    node = node.children[0];
  }
  if (v.move === null && v.comment && !line.some((x) => x[2])) line.push(["", "", v.comment]);
  return [b, line];
}

function lecture(root, size) {
  const vars = root.children;
  if (vars.length < 2 || !vars[0].hasSetup) return null;
  const [b0, line0] = diagram(root, vars[0], size);
  const baseRows = rowsOf(b0);
  for (const [color, v] of line0) if (color && !playOn(b0, color, v)) return null;
  const prefix = line0.filter((x) => x[0]).map((x) => [x[0], x[1]]);
  const task = line0.filter((x) => x[2]).map((x) => x[2]).join(" ") || vars[0].comment;
  const diagrams = vars.slice(1).map((v) => {
    const [b, line] = diagram(root, v, size);
    return [rowsOf(b), line.filter((x) => x[0]).map((x) => [x[0], x[1]]), line.filter((x) => x[2]).map((x) => x[2]).join(" ")];
  });
  for (const [target, strip] of [[rowsOf(b0), true], [baseRows, false]]) {
    const res = lectureTree(diagrams, target, baseRows, strip ? prefix : [], size);
    if (res) return [target, res[0], res[1], task];
  }
  return null;
}

const eqRows = (a, b) => a.join("\n") === b.join("\n");
const eqMoves = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function lectureTree(diagrams, target, baseRows, prefix, size) {
  const branches = [];
  for (let [rows, mv, text] of diagrams) {
    if (prefix.length && eqRows(rows, baseRows) && eqMoves(mv.slice(0, prefix.length), prefix)) mv = mv.slice(prefix.length);
    else if (!eqRows(rows, target)) continue;
    if (!mv.length) continue;
    const v = verdictOf(text);
    if (v === null) continue;
    branches.push([v, mv, text]);
  }
  const correct = branches.filter((x) => x[0]);
  if (!correct.length) return null;
  const player = correct[0][1][0][0];
  const tree = { next: [], wrong: [] };
  const sorted = [...branches.filter((x) => x[0]), ...branches.filter((x) => !x[0])];
  for (const [ok, mv, text] of sorted) {
    let node = tree;
    for (let k = 0; k < mv.length; k += 2) {
      const [color, v] = mv[k];
      if (color !== player) break;
      const gtp = sgfGtp(v, size);
      if (gtp === null) break;
      const reply = k + 1 < mv.length && mv[k + 1][0] !== player ? sgfGtp(mv[k + 1][1], size) : null;
      const existing = (node.next || []).find((n) => n.move === gtp);
      if (existing) {
        if (!ok && existing.reply && reply && existing.reply !== reply) break;
        node = existing;
        continue;
      }
      if (!ok) {
        if (!(node.wrong || []).some((w) => w.move === gtp)) {
          const w = { move: gtp, comment: ruComment(text, false) };
          if (reply) w.reply = reply;
          (node.wrong = node.wrong || []).push(w);
        }
        break;
      }
      const nw = { move: gtp, comment: node === tree ? ruComment(text, true) : "Верно, продолжайте." };
      if (reply) { nw.reply = reply; nw.reply_comment = ""; }
      (node.next = node.next || []).push(nw);
      node = nw;
    }
  }
  finalize(tree);
  if (!tree.next.length) return null;
  return [player, tree];
}

function verdictOf(text) {
  const head = cleanText(text).slice(0, 70) || text.slice(0, 70);
  const w = wrongAt(head), r = rightAt(head);
  if (w >= 0 && (r < 0 || w <= r)) return false;
  if (r >= 0) return true;
  return null;
}

function finalize(node) {
  for (const n of node.next || []) {
    if ((!n.next || !n.next.length) && n.comment === "Верно, продолжайте.") n.comment = "Верно! Задача решена.";
    finalize(n);
  }
}

// ------------------------------------------------------------------ общий вход
function treeToProblem(root, pid, level, number) {
  const size = sizeOf(root);
  if (size > 19 || size < 5) return null;
  let res = null;
  if (!root.hasSetup && root.children.length >= 2 && root.children.every((c) => c.hasSetup || c.move)) res = lecture(root, size);
  if (!res) res = classic(root, size);
  if (!res) return null;
  const [board, player, tree, comment] = res;
  if (!valid(board, player, tree, size)) return null;
  const name = cleanText((root.props.GN || [""])[0] || "");
  let task = taskText(comment, player);
  if (task.length > 600) task = task.slice(0, 600) + "…";
  const title = name && !/^\d+$/.test(name) ? name.slice(0, 60) : `Задача ${number}`;
  return { id: pid, level, title, task,
    hint: "Найдите ход, после которого у соперника не будет хорошего ответа. Если застряли, «Разбор с ИИ» покажет лучший ход.",
    board, to_play: player, tree, marked: [], concept: "", why: "", source: "" };
}

// Все ходы дерева должны быть разрешены правилами
function valid(rows, player, tree, size) {
  const initial = Board.fromAscii(rows);
  const color = player === "B" ? BLACK : WHITE;
  function walk(node, game) {
    for (const n of node.next || []) {
      const g = new Game(size, 0, "japanese", 0, game.board, game.toPlay);
      try {
        g.play(fromGtp(n.move, size));
        if (n.reply) g.play(fromGtp(n.reply, size));
      } catch (e) { if (e instanceof IllegalMove) return false; throw e; }
      if (!walk(n, g)) return false;
    }
    node.wrong = (node.wrong || []).filter((w) => game.board.isLegal(game.toPlay, fromGtp(w.move, size)));
    if (!node.wrong.length) delete node.wrong;
    return true;
  }
  return walk(tree, new Game(size, 0, "japanese", 0, initial, color));
}

export function bytesToProblems(bytes, level, startNumber = 1, pidPrefix = "") {
  const text = stripRtf(decode(bytes));
  const out = [];
  for (const t of parseCollection(text)) {
    const n = startNumber + out.length;
    const p = treeToProblem(t, `${pidPrefix}${level}-${n}`, level, n);
    if (p) out.push(p);
  }
  return out;
}

// files: [{name, folder, bytes}] -> добавляет задачи в data ({levels, problems}). Возвращает [добавлено, пропущено]
export function importInto(data, files) {
  let nextLevel = Math.max(999, ...data.levels.map((l) => l.level)) + 1;
  let added = 0, skipped = 0;
  const byDir = new Map();
  for (const f of files) {
    if (!byDir.has(f.folder)) byDir.set(f.folder, []);
    byDir.get(f.folder).push(f);
  }
  for (const [folder, fs] of byDir) {
    const probs = [];
    for (const f of fs) {
      let got = [];
      try { got = bytesToProblems(f.bytes, nextLevel, probs.length + 1, `imp${Date.now() % 100000}-`); } catch (e) { console.error(f.name, e); }
      if (!got.length) skipped++;
      probs.push(...got);
    }
    if (!probs.length) continue;
    const name = fs.length === 1 ? fs[0].name.replace(/\.sgf$/i, "") : (folder || "сборник");
    data.levels.push({ level: nextLevel, title: `Импорт: ${name}`,
      lesson: `Задачи из «${name}». Объяснения взяты из комментариев файлов; если их нет, нажмите «Разбор с ИИ».`,
      stage: "Мои сборники" });
    data.problems.push(...probs);
    added += probs.length;
    nextLevel++;
  }
  return [added, skipped];
}
