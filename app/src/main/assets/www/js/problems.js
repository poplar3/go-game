// Учебные задачи: загрузка, проверка ответов. Формат совпадает с настольной версией (problems.json).
import { BLACK, WHITE, EMPTY, Board, Game, IllegalMove, fromGtp, toGtp, other } from "./board.js";
import { store } from "./store.js";

export const STAGE_ORDER = ["Основы", "Тактика", "Жизнь и смерть", "Форма", "Дебют", "Середина игры", "Ёсэ (конец игры)",
  "Библиотека: 25–16 кю", "Библиотека: 15–10 кю", "Библиотека: 9–4 кю", "Библиотека: 3 кю – 2 дан",
  "Библиотека: 3–5 дан и сильнее", "Библиотека: тематические сборники", "Мои сборники"];

export const isCourse = (stage) => !stage.startsWith("Библиотека") && stage !== "Мои сборники";

function parse(data) {
  const levels = (data.levels || []).map((l) => ({ level: l.level, title: l.title, lesson: l.lesson, stage: l.stage || "", books: l.books || "" }));
  const problems = (data.problems || []).map((p) => ({
    id: p.id, level: p.level, title: p.title, task: p.task, hint: p.hint || "", board: p.board,
    toPlay: (p.to_play || "B") === "B" ? BLACK : WHITE, tree: p.tree || {}, marked: p.marked || [],
    concept: p.concept || "", why: p.why || "", source: p.source || "", kind: p.kind || "local", pre: p.pre || [],
    get size() { return this.board.length; },
  }));
  return [levels, problems];
}

async function fetchJson(url, gz) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  if (!gz) return r.json();
  const stream = r.body.pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).json();
}

export async function loadAll() {
  const [levels, problems] = parse(await fetchJson("data/problems.json", false));
  try {
    const [lv, pr] = parse(await fetchJson("data/library.json.gz", true));
    levels.push(...lv); problems.push(...pr);
  } catch (e) { console.error("library", e); }
  try {
    const imp = await store.getBig("imported_problems");
    if (imp) { const [lv, pr] = parse(JSON.parse(imp)); levels.push(...lv); problems.push(...pr); }
  } catch (e) { console.error("imported", e); }
  return [levels, problems];
}

export function solutionLine(problem) {
  const res = [];
  let node = problem.tree;
  while (node.next && node.next.length) {
    const n = node.next[0];
    res.push([n.move, n.comment || ""]);
    if (n.reply) res.push([n.reply, n.reply_comment || ""]);
    node = n;
  }
  return res;
}

// Пункты, где имеет смысл ходить в задаче: окружённые пустые области, иначе — рядом с камнями
export function localRegion(board) {
  const seen = new Set();
  let enclosed = [];
  for (let p = 0; p < board.n; p++) {
    if (board.get(p) !== EMPTY || seen.has(p)) continue;
    const region = new Set([p]);
    const stack = [p];
    while (stack.length) {
      const q = stack.pop();
      for (const nb of board.neighbors(q)) if (board.get(nb) === EMPTY && !region.has(nb)) { region.add(nb); stack.push(nb); }
    }
    for (const q of region) seen.add(q);
    if (region.size <= 12) enclosed.push(...region);
  }
  if (!enclosed.length) {
    for (let p = 0; p < board.n; p++) {
      if (board.get(p) !== EMPTY) continue;
      if ([...board.neighbors(p), ...board.diagonals(p)].some((q) => board.get(q) !== EMPTY)) enclosed.push(p);
    }
  }
  return enclosed.sort((a, b) => a - b).map((p) => toGtp(p, board.size));
}

export class ProblemSession {
  constructor(problem) {
    this.problem = problem;
    const firstColor = problem.pre.length % 2 === 0 ? problem.toPlay : other(problem.toPlay);
    this.game = new Game(problem.size, 0, "japanese", 0, Board.fromAscii(problem.board), firstColor);
    for (const m of problem.pre) this.game.play(fromGtp(m, problem.size));
    this.node = problem.tree;
    this.solved = false;
    this.failed = false;
  }
  get board() { return this.game.board; }

  // Возвращает {kind: correct|solved|wrong|unknown|illegal, comment, reply, replyComment}
  play(p) {
    const size = this.problem.size;
    const gtp = toGtp(p, size);
    try { this.game.play(p); } catch (e) {
      if (e instanceof IllegalMove) return { kind: "illegal", comment: `Так ходить нельзя: ${e.message}.` };
      throw e;
    }
    for (const n of this.node.next || []) {
      if (n.move.toUpperCase() === gtp) {
        const reply = n.reply ? fromGtp(n.reply, size) : null;
        if (reply !== null) this.game.play(reply);
        this.node = n;
        if (!n.next || !n.next.length) {
          this.solved = true;
          return { kind: "solved", comment: n.comment || "", reply, replyComment: n.reply_comment || "" };
        }
        return { kind: "correct", comment: n.comment || "", reply, replyComment: n.reply_comment || "" };
      }
    }
    for (const w of this.node.wrong || []) {
      if (w.move.toUpperCase() === gtp) {
        let reply = w.reply ? fromGtp(w.reply, size) : null;
        if (reply !== null) { try { this.game.play(reply); } catch { reply = null; } }
        this.failed = true;
        return { kind: "wrong", comment: w.comment || "", reply };
      }
    }
    this.failed = true;
    return { kind: "unknown", comment: "" };
  }

  expectedMoves() { return (this.node.next || []).map((n) => n.move); }
}
