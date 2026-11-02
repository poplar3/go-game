// Работа с KataGo (режим анализа, JSON-протокол) через мост Android и уровни силы бота.
// Процесс KataGo запускает Java-часть приложения (KataGoBridge), сюда приходят строки его ответов.
import { BLACK, toGtp } from "./board.js";

export const LEVELS = [
  { name: "Новичок", description: "Встроенный бот на простых правилах. Работает без KataGo.", mode: "simple", needsEngine: false },
  { name: "Начинающий", description: "Нейросеть со случайными отклонениями: часто ошибается.", mode: "policy", temperature: 2.2, needsEngine: true },
  { name: "Любитель", description: "Играет по интуиции нейросети, иногда ошибается.", mode: "policy", temperature: 1.0, needsEngine: true },
  { name: "Сильный любитель", description: "Всегда выбирает самый естественный ход нейросети.", mode: "policy", temperature: 0.25, needsEngine: true },
  { name: "Мастер", description: "Короткий поиск вариантов (50 просмотров).", mode: "search", visits: 50, needsEngine: true },
  { name: "Профи", description: "Глубокий поиск (400 просмотров). Сильнее любого человека.", mode: "search", visits: 400, needsEngine: true },
];
export const DEFAULT_LEVEL = 2;

export function analysisFromJson(d, size) {
  const root = d.rootInfo || {};
  return {
    turn: d.turnNumber || 0,
    winrate: root.winrate ?? 0.5,
    scoreLead: root.scoreLead ?? 0,
    moves: (d.moveInfos || []).map((m) => ({ move: m.move, visits: m.visits || 0, winrate: m.winrate ?? 0.5,
      scoreLead: m.scoreLead ?? 0, prior: m.prior || 0, pv: m.pv || [], ownership: m.ownership || null })),
    ownership: d.ownership || null,
    policy: d.policy || null,
    size,
  };
}

// Ход бота по анализу (null — пас). point — номер пункта.
export function chooseFromAnalysis(level, a, size, opponentPassed, rng = Math.random) {
  const best = a.moves[0] || null;
  const fromGtpLocal = (s) => {
    const L = "ABCDEFGHJKLMNOPQRST";
    return (size - parseInt(s.slice(1), 10)) * size + L.indexOf(s[0].toUpperCase());
  };
  if (level.mode === "search" || !a.policy) {
    if (!best || best.move.toLowerCase() === "pass") return null;
    return fromGtpLocal(best.move);
  }
  const policy = a.policy, n = size * size;
  const passProb = policy.length > n ? policy[n] : 0;
  if (passProb > 0.5 || (opponentPassed && best && best.move.toLowerCase() === "pass")) return null;
  let top = 0;
  for (let i = 0; i < n; i++) top = Math.max(top, policy[i]);
  const cands = [];
  for (let i = 0; i < n; i++) {
    const p = policy[i];
    if (p <= 0 || p < top * 0.002) continue;
    cands.push([i, Math.pow(p, 1 / level.temperature)]);
  }
  if (!cands.length) return null;
  let r = rng() * cands.reduce((s, c) => s + c[1], 0);
  for (const [i, w] of cands) { r -= w; if (r <= 0) return i; }
  return cands[cands.length - 1][0];
}

class KataGoEngine {
  constructor() {
    this.callbacks = new Map(); // id -> [cb, remaining]
    this.counter = 0;
    this.ready = false;
    this.status = "ИИ не запущен";
    this.listeners = [];
    this.info = null;
    window.__kg = {
      onLine: (line) => this._onLine(line),
      onStatus: (state, text) => this._setStatus(state === "ready", text),
      onDownload: (what, done, total, state) => this.onDownload && this.onDownload(what, done, total, state),
    };
  }
  get bridge() { return window.Android || null; }
  get hasBridge() { return !!this.bridge; }

  onChange(fn) { this.listeners.push(fn); }
  _setStatus(ready, text) {
    this.ready = ready;
    this.status = text;
    console.log("[engine] " + text);
    for (const fn of this.listeners) { try { fn(ready, text); } catch (e) { console.error(e); } }
  }

  available() { return this.ready && this.hasBridge; }

  getInfo() {
    if (!this.hasBridge) return { hasBinary: false, models: [], cores: navigator.hardwareConcurrency || 4, abi: "" };
    try { this.info = JSON.parse(this.bridge.engineInfo()); } catch { this.info = { hasBinary: false, models: [] }; }
    return this.info;
  }

  start(settings) {
    this.stop();
    if (!this.hasBridge) { this._setStatus(false, "KataGo работает только в Android-приложении — играет встроенный бот."); return; }
    this._setStatus(false, "Запускаю ИИ KataGo…");
    this.bridge.engineStart(JSON.stringify(settings || {}));
  }
  stop() {
    this.callbacks.clear();
    if (this.hasBridge) this.bridge.engineStop();
    this.ready = false;
  }

  _onLine(line) {
    if (!line.startsWith("{")) return;
    let data;
    try { data = JSON.parse(line); } catch { return; }
    const qid = data.id || "";
    const entry = this.callbacks.get(qid);
    if (!entry) return;
    const [cb] = entry;
    if ("error" in data || data.isDuringSearch === false || "noResults" in data) {
      entry[1] -= 1;
      if (entry[1] <= 0) this.callbacks.delete(qid);
    }
    try { cb(data); } catch (e) { console.error("callback error", e); }
  }

  query(payload, cb, expected = 1) {
    if (!this.available()) throw new Error("KataGo не запущен");
    const qid = `q${++this.counter}`;
    this.callbacks.set(qid, [cb, expected]);
    this.bridge.engineQuery(JSON.stringify({ ...payload, id: qid }));
    return qid;
  }

  cancel(qid) {
    if (!qid || !this.available()) return;
    this.callbacks.delete(qid);
    this.bridge.engineQuery(JSON.stringify({ id: `cancel-${qid}`, action: "terminate", terminateId: qid }));
  }

  static basePayload(game, upto = null) {
    const p = { moves: game.gtpMoves(upto), rules: game.rules === "chinese" ? "chinese" : "japanese", komi: game.komi,
      boardXSize: game.size, boardYSize: game.size };
    const init = game.initialStonesGtp();
    if (init.length) p.initialStones = init;
    p.initialPlayer = game.firstToPlay === BLACK ? "B" : "W";
    return p;
  }

  analyzePosition(game, callback, { upto = null, visits = 200, ownership = true, policy = false, allowMoves = null } = {}) {
    const n = upto === null ? game.moves.length : upto;
    const payload = KataGoEngine.basePayload(game, n);
    Object.assign(payload, { maxVisits: visits, includeOwnership: ownership, includePolicy: policy });
    if (allowMoves) {
      const player = game.toPlayAt(n) === BLACK ? "B" : "W";
      payload.allowMoves = [{ player, moves: allowMoves, untilDepth: 1 }];
    }
    return this.query(payload, (d) => callback("error" in d ? null : analysisFromJson(d, game.size)));
  }

  analyzeGame(game, onTurn, visits = 100) {
    const turns = [];
    for (let i = 0; i <= game.moves.length; i++) turns.push(i);
    const payload = KataGoEngine.basePayload(game, game.moves.length);
    Object.assign(payload, { maxVisits: visits, includeOwnership: true, analyzeTurns: turns });
    return this.query(payload, (d) => { if (!("error" in d) && !("noResults" in d)) onTurn(analysisFromJson(d, game.size)); }, turns.length);
  }
}

export const engine = new KataGoEngine();
export { toGtp };
