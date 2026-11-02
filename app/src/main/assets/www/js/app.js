// Интерфейс приложения: вкладки «Партия», «Задачи», «Правила», «Настройки».
import { BLACK, WHITE, EMPTY, Game, IllegalMove, fromGtp, toGtp } from "./board.js";
import { LEVELS, DEFAULT_LEVEL, chooseFromAnalysis, engine } from "./engine.js";
import { chooseMove } from "./simplebot.js";
import { reviewMove, offlineExplanation, tacticalFacts, pvText, pointsWord, pointsGen, groupArea, genitiveStones } from "./explain.js";
import { score, deadFromOwnership, toggleDeadGroup, fmt } from "./scoring.js";
import { saveSgf, loadSgf } from "./sgf.js";
import { BoardView, WinrateGraph, GREEN, RED, BLUE } from "./boardview.js";
import { STAGE_ORDER, isCourse, loadAll, solutionLine, localRegion, ProblemSession } from "./problems.js";
import { importInto } from "./sgfimport.js";
import { readZip, inflate } from "./zip.js";
import { store } from "./store.js";

const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------------ общие диалоги
function modal(title, bodyHtml, buttons) {
  return new Promise((resolve) => {
    $("modal-title").textContent = title;
    $("modal-body").innerHTML = bodyHtml;
    const box = $("modal-buttons");
    box.innerHTML = "";
    for (const [label, value, cls] of buttons) {
      const b = document.createElement("button");
      b.textContent = label;
      if (cls) b.className = cls;
      b.onclick = () => { $("modal").classList.add("hidden"); resolve(value); };
      box.appendChild(b);
    }
    $("modal").classList.remove("hidden");
  });
}
const confirmBox = (title, text) => modal(title, `<p>${esc(text)}</p>`, [["Отмена", false], ["Да", true, "accent"]]);
const info = (title, text) => modal(title, `<p>${esc(text).replace(/\n/g, "<br>")}</p>`, [["OK", true, "accent"]]);
let toastTimer = null;
function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3000);
}

function textToHtml(text) {
  const lines = text.split("\n").filter((l) => l.trim());
  if (!lines.length) return "";
  const out = [`<p><b>${esc(lines[0])}</b></p>`];
  for (const l of lines.slice(1)) {
    const i = l.indexOf(": ");
    if (i >= 0 && i < 30) out.push(`<p><b>${esc(l.slice(0, i))}:</b> ${esc(l.slice(i + 2))}</p>`);
    else out.push(`<p>${esc(l)}</p>`);
  }
  return out.join("");
}

function confirmFor(size) { return size >= 13 ? store.get("confirm19", true) : store.get("confirm9", false); }

// ------------------------------------------------------------------ файлы
function pickFiles(accept) {
  return new Promise((resolve) => {
    const inp = $("file-input");
    inp.value = "";
    inp.accept = accept || "";
    inp.onchange = () => resolve([...inp.files]);
    inp.click();
  });
}
function saveTextFile(name, text) {
  if (window.Android && window.Android.saveFile) { window.Android.saveFile(name, text); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/x-go-sgf" }));
  a.download = name;
  a.click();
}
window.__onFileSaved = (ok, msg) => toast(ok ? "Файл сохранён" : `Не удалось сохранить: ${msg}`);

// ================================================================== Партия
class GameTab {
  constructor() {
    this.settings = { size: store.get("game/size", 9), rules: store.get("game/rules", "chinese"),
      komi: store.get("game/komi", 7.5), handicap: 0, human: BLACK, level: store.get("game/level", DEFAULT_LEVEL) };
    this.game = new Game(9, 7.5, "chinese");
    this.view = 0;
    this.scoring = false;
    this.dead = new Set();
    this.result = null;
    this.botThinking = false;
    this.botQuery = null;
    this.reviewQuery = null;
    this.analyses = new Map();
    this.reviews = new Map();
    this.board = new BoardView($("g-board"));
    this.board.onClick = (p) => this.onClick(p);
    this.board.confirmTap = () => confirmFor(this.game.size);
    this.graph = new WinrateGraph($("g-graph"));
    this.graph.onSelect = (n) => this.gotoReview(n);

    $("g-new").onclick = () => this.newGameDialog();
    $("g-pass").onclick = () => this.humanPass();
    $("g-undo").onclick = () => this.undo();
    $("g-resign").onclick = () => this.resign();
    $("g-hint").onclick = () => this.hint();
    $("g-explain").onclick = () => this.explainCurrent();
    $("g-review").onclick = () => this.reviewGame();
    $("g-score").onclick = () => this.scoreButton();
    $("g-owner").onchange = () => this.toggleOwnership();
    for (const b of document.querySelectorAll("[data-nav]")) {
      b.onclick = () => {
        const k = b.dataset.nav;
        this.goto(k === "first" ? 0 : k === "prev" ? this.view - 1 : k === "next" ? this.view + 1 : this.game.moves.length);
      };
    }
    engine.onChange((ready, text) => { $("g-engine").textContent = text; this.refresh(); });
    $("g-engine").textContent = engine.status;

    const saved = store.get("game/current", null);
    let restored = false;
    if (saved) {
      try {
        const g = loadSgf(saved.sgf);
        this.startGame({ ...this.settings, ...saved.settings }, g, true);
        restored = true;
        this.setText("Партия продолжается с того места, где вы остановились.");
      } catch (e) { console.error(e); }
    }
    if (!restored) {
      this.startGame({ ...this.settings, handicap: 0, human: BLACK });
      this.setText("Добро пожаловать! Вы играете чёрными. Коснитесь пересечения линий, чтобы сделать ход.\n"
        + "Подсказка — ИИ покажет лучший ход и объяснит его. Объяснить ход — разбор хода, который сейчас на доске. "
        + "Разбор партии — поиск всех ошибок после игры.");
    }
  }

  get live() { return this.view === this.game.moves.length; }
  isHumanTurn() { return this.settings.human === 0 || this.game.toPlay === this.settings.human; }
  setText(text) { $("g-text").innerHTML = textToHtml(text); }
  persist() {
    store.set("game/current", { sgf: saveSgf(this.game), settings: this.settings, result: this.result });
  }

  startGame(gs, game = null, restoring = false) {
    this.cancelQueries();
    this.settings = gs;
    this.game = game || new Game(gs.size, gs.komi, gs.rules, gs.handicap);
    this.view = this.game.moves.length;
    this.scoring = false;
    this.dead = new Set();
    this.result = restoring ? (store.get("game/current", {}).result || null) : null;
    this.analyses.clear();
    this.reviews.clear();
    $("g-mistakes").innerHTML = "";
    this.graph.setData(new Map(), 0, new Map());
    this.board.clearMarks();
    this.refresh();
    if (!restoring) this.persist();
    this.maybeBot();
  }

  async newGameDialog() {
    const s = this.settings;
    const opt = (v, cur, label) => `<option value="${v}" ${String(v) === String(cur) ? "selected" : ""}>${label}</option>`;
    const levelOpts = LEVELS.map((l, i) => opt(i, store.get("game/level", DEFAULT_LEVEL), l.name)).join("");
    const html = `
      <label>Размер доски<select id="ng-size">${[9, 13, 19].map((n) => opt(n, store.get("game/size", 9), `${n}×${n}`)).join("")}</select></label>
      <label>Правила подсчёта<select id="ng-rules">${opt("chinese", s.rules, "Китайские (по площади)")}${opt("japanese", s.rules, "Японские (по территории)")}</select></label>
      <div class="small">Китайские: считаются свои камни на доске и окружённые пункты. Японские: окружённые пункты и пленники.</div>
      <label>Коми (очки белым)<input type="number" id="ng-komi" step="0.5" value="${store.get("game/komi", 7.5)}"></label>
      <label>Фора (камни чёрным)<select id="ng-hc">${[0, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => opt(n, store.get("game/handicap", 0), n ? n : "нет")).join("")}</select></label>
      <label>Я играю<select id="ng-color">${opt(0, store.get("game/color_idx", 0), "Чёрными (хожу первым)")}${opt(1, store.get("game/color_idx", 0), "Белыми")}${opt(2, store.get("game/color_idx", 0), "Вдвоём на одном телефоне")}</select></label>
      <label>Сила бота<select id="ng-level">${levelOpts}</select></label>
      <div class="small" id="ng-desc"></div>`;
    const p = modal("Новая партия", html, [["Отмена", false], ["Начать", true, "accent"]]);
    const desc = () => { $("ng-desc").textContent = LEVELS[+$("ng-level").value].description; };
    $("ng-level").onchange = desc; desc();
    $("ng-rules").onchange = () => { $("ng-komi").value = $("ng-rules").value === "chinese" ? 7.5 : 6.5; };
    if (!(await p)) return;
    const colorIdx = +$("ng-color").value;
    const gs = { size: +$("ng-size").value, rules: $("ng-rules").value, komi: parseFloat($("ng-komi").value) || 0,
      handicap: +$("ng-hc").value, human: [BLACK, WHITE, 0][colorIdx], level: +$("ng-level").value };
    store.set("game/size", gs.size); store.set("game/rules", gs.rules); store.set("game/komi", gs.komi);
    store.set("game/handicap", gs.handicap); store.set("game/color_idx", colorIdx); store.set("game/level", gs.level);
    this.startGame(gs);
    if (LEVELS[gs.level].needsEngine && !engine.available()) {
      this.setText("ИИ KataGo пока не запущен, поэтому играет встроенный бот (уровень «Новичок»). Состояние ИИ — во вкладке «Настройки».");
    } else this.setText("Новая партия началась. Удачи!");
  }

  cancelQueries() {
    engine.cancel(this.botQuery);
    engine.cancel(this.reviewQuery);
    this.botQuery = null;
    this.reviewQuery = null;
    this.botThinking = false;
    $("g-progress").classList.add("hidden");
  }

  effectiveLevel() {
    const lv = LEVELS[this.settings.level] || LEVELS[0];
    return lv.needsEngine && !engine.available() ? 0 : this.settings.level;
  }

  refresh() {
    const g = this.game;
    const b = g.boards[this.view];
    const last = this.view > 0 ? g.moves[this.view - 1].point : null;
    this.board.board = b; this.board.lastMove = last;
    this.board.ghostColor = this.live && !this.scoring && !this.result ? g.toPlay : null;
    this.board.interactive = (this.live && !this.botThinking) || this.scoring;
    const caps = g.captures(this.view);
    const rules = g.rules === "chinese" ? "китайские" : "японские";
    const h = this.settings.human;
    const who = h === BLACK ? { [BLACK]: "Вы", [WHITE]: "Бот" } : h === WHITE ? { [BLACK]: "Бот", [WHITE]: "Вы" } : { [BLACK]: "Игрок 1", [WHITE]: "Игрок 2" };
    const lines = [`<b>${g.size}×${g.size}</b>, ${rules}, коми ${fmt(g.komi)}` + (h !== 0 ? ` · бот: ${LEVELS[this.effectiveLevel()].name}` : ""),
      `⚫ ${who[BLACK]}: пленников ${caps[BLACK]} &nbsp; ⚪ ${who[WHITE]}: пленников ${caps[WHITE]}`];
    if (this.result) lines.push(`<b>Итог: ${esc(this.result)}</b>`);
    else if (this.scoring) lines.push(`<b>Подсчёт очков:</b> касайтесь групп, чтобы отметить мёртвые камни, затем «Подтвердить».<br>${esc(this.scoreDetails || "").replace(/\n/g, "<br>")}`);
    else if (this.botThinking) lines.push("Бот думает…");
    else lines.push(`Ход: ${g.toPlay === BLACK ? "чёрных" : "белых"}`);
    $("g-info").innerHTML = lines.join("<br>");
    $("g-move").textContent = `Ход ${this.view} из ${g.moves.length}`;
    this.graph.setCurrent(this.view);
    const playing = !this.result && !this.scoring;
    $("g-pass").disabled = !(playing && this.live && this.isHumanTurn() && !this.botThinking);
    $("g-resign").disabled = !(playing && h !== 0);
    $("g-undo").disabled = !(g.moves.length && !this.botThinking && !this.scoring);
    $("g-score").textContent = this.scoring ? "Подтвердить" : "Подсчёт";
    $("g-score").disabled = !!this.result;
    $("g-review").disabled = !(g.moves.length && engine.available() && this.reviewQuery === null);
    $("g-hint").disabled = !playing;
    $("g-explain").disabled = this.view === 0;
    this.toggleOwnership(true);
    this.board.draw();
  }

  // ------------------------------------------------------------------ ходы
  async onClick(p) {
    if (this.scoring) {
      this.dead = toggleDeadGroup(this.game.board, this.dead, p);
      this.showScoring();
      return;
    }
    if (this.result || this.botThinking) return;
    if (!this.live) {
      if (!(await confirmBox("Продолжить отсюда?", "Вы смотрите старую позицию. Продолжить партию с неё? Последующие ходы будут удалены."))) return;
      while (this.game.moves.length > this.view) this.game.undo();
      this.dropReviewsAfter(this.view);
    }
    if (!this.isHumanTurn()) return;
    try { this.game.play(p); } catch (e) {
      if (e instanceof IllegalMove) { this.setText(`Так ходить нельзя: ${e.message}.`); this.refresh(); return; }
      throw e;
    }
    this.afterMove();
  }

  humanPass() {
    if (!this.live || this.result) return;
    this.game.play(null);
    this.afterMove();
  }

  afterMove() {
    this.view = this.game.moves.length;
    this.board.clearMarks();
    this.dropReviewsAfter(this.view - 1);
    this.persist();
    if (this.game.consecutivePasses() >= 2) { this.refresh(); this.startScoring(); return; }
    const last = this.game.moves[this.game.moves.length - 1];
    if (last.point === null && this.settings.human !== 0 && last.color !== this.settings.human) {
      this.setText("Бот пасует: он считает, что ценных ходов не осталось. Если вы согласны — тоже нажмите «Пас», и начнётся подсчёт очков.");
    }
    this.refresh();
    this.maybeBot();
  }

  dropReviewsAfter(n) {
    for (const k of [...this.reviews.keys()]) if (k > n) this.reviews.delete(k);
    for (const k of [...this.analyses.keys()]) if (k > n) this.analyses.delete(k);
  }

  undo() {
    if (this.botThinking || !this.game.moves.length) return;
    this.result = null;
    this.game.resigned = null;
    this.game.undo();
    if (this.settings.human !== 0 && this.game.moves.length && !this.isHumanTurn()) this.game.undo();
    this.view = this.game.moves.length;
    this.dropReviewsAfter(this.view);
    this.board.clearMarks();
    this.persist();
    this.refresh();
    this.maybeBot();
  }

  async resign() {
    if (!(await confirmBox("Сдаться", "Вы уверены, что хотите сдаться?"))) return;
    const human = this.settings.human;
    this.game.resigned = human;
    this.result = `${human === BLACK ? "Белые" : "Чёрные"} побеждают (сдача)`;
    this.cancelQueries();
    this.persist();
    this.refresh();
    this.setText(this.result + "\nНажмите «Разбор партии», чтобы найти ошибки.");
  }

  // ------------------------------------------------------------------ бот
  maybeBot() {
    if (this.result || this.scoring || !this.live || this.isHumanTurn() || this.botThinking) return;
    this.botThinking = true;
    this.refresh();
    const lv = LEVELS[this.effectiveLevel()];
    const g = this.game;
    const oppPassed = g.moves.length > 0 && g.moves[g.moves.length - 1].point === null;
    if (lv.mode === "simple") { setTimeout(() => this.simpleBotMove(), 300); return; }
    const visits = lv.mode === "search" ? lv.visits : oppPassed ? 40 : 2;
    const gen = g.moves.length;
    const done = (a) => {
      this.botQuery = null;
      if (!this.botThinking || this.game.moves.length !== gen) return;
      if (!a) { this.simpleBotMove(); return; }
      if (!this.analyses.has(gen)) this.analyses.set(gen, a);
      this.botPlay(chooseFromAnalysis(lv, a, g.size, oppPassed));
    };
    try {
      this.botQuery = engine.analyzePosition(g, done, { visits, ownership: false, policy: lv.mode === "policy" });
    } catch { setTimeout(() => this.simpleBotMove(), 300); }
  }

  simpleBotMove() {
    if (!this.botThinking) return;
    const g = this.game;
    this.botPlay(chooseMove(g.board, g.toPlay, g.moves.length ? g.moves[g.moves.length - 1].point : null));
  }

  botPlay(p) {
    this.botThinking = false;
    try { this.game.play(p); } catch { this.game.play(null); }
    this.afterMove();
  }

  // ------------------------------------------------------------------ подсчёт
  scoreButton() {
    if (this.scoring) this.confirmScore();
    else if (!this.botThinking) this.startScoring();
  }

  startScoring() {
    this.scoring = true;
    this.dead = new Set();
    this.view = this.game.moves.length;
    this.refresh();
    if (engine.available()) {
      this.setText("ИИ определяет мёртвые камни…");
      engine.analyzePosition(this.game, (a) => {
        if (a && a.ownership && this.scoring) {
          this.dead = deadFromOwnership(this.game.board, a.ownership);
          this.analyses.set(this.game.moves.length, a);
        }
        this.showScoring();
        this.setText("Подсчёт очков. ИИ отметил мёртвые камни (полупрозрачные). Если вы не согласны, коснитесь группы, "
          + "чтобы изменить её статус. Затем нажмите «Подтвердить».");
      }, { visits: 200 });
    } else {
      this.showScoring();
      this.setText("Подсчёт очков. Коснитесь групп, которые считаются мёртвыми (они не смогут выжить), затем нажмите «Подтвердить».");
    }
  }

  showScoring() {
    const g = this.game;
    const r = score(g.board, g.rules, g.komi, g.captures(), this.dead);
    this.board.dead = new Set(this.dead);
    this.board.territory = new Map(r.owner);
    this.scoreDetails = r.details();
    this.refresh();
  }

  confirmScore() {
    const g = this.game;
    const r = score(g.board, g.rules, g.komi, g.captures(), this.dead);
    this.scoring = false;
    this.result = r.resultString();
    this.board.dead = new Set(this.dead);
    this.board.territory = new Map(r.owner);
    this.persist();
    this.refresh();
    this.setText("Партия окончена\n" + r.details() + "\nНажмите «Разбор партии», чтобы ИИ нашёл ошибки и объяснил их.");
  }

  // ------------------------------------------------------------------ навигация
  goto(n) {
    n = Math.max(0, Math.min(this.game.moves.length, n));
    if (n === this.view) return;
    this.view = n;
    this.board.clearMarks();
    if (this.scoring && n !== this.game.moves.length) this.scoring = false;
    this.refresh();
    if (this.reviews.has(n)) this.showReview(n);
  }

  gotoReview(n) {
    this.goto(n);
    if (this.reviews.has(n)) this.showReview(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  showReview(n) {
    const r = this.reviews.get(n);
    this.setText(r.text);
    this.board.circles.clear();
    this.board.labels.clear();
    if (r.bestMove && r.bestMove.toLowerCase() !== "pass" && r.loss >= 0.5) {
      const size = this.game.size;
      const bp = fromGtp(r.bestMove, size);
      const before = this.game.boards[n - 1];
      this.board.board = before; this.board.lastMove = null; // позиция до хода
      this.board.circles.set(bp, GREEN);
      if (r.point !== null) this.board.circles.set(r.point, RED);
      r.bestPv.slice(0, 6).forEach((mv, i) => {
        const p = fromGtp(mv, size);
        if (p !== null && p !== bp && before.get(p) === EMPTY && !this.board.labels.has(p)) this.board.labels.set(p, [String(i + 1), BLUE]);
      });
      this.board.labels.set(bp, ["1", GREEN]);
    }
    this.board.draw();
  }

  toggleOwnership(quiet = false) {
    const on = $("g-owner").checked;
    const a = this.analyses.get(this.view);
    this.board.ownership = on && a && a.ownership ? a.ownership : null;
    this.board.draw();
    if (on && !a && engine.available()) {
      const n = this.view;
      if (this._ownPending === n) return;
      this._ownPending = n;
      engine.analyzePosition(this.game, (res) => {
        this._ownPending = null;
        if (res) {
          if (!this.analyses.has(n)) this.analyses.set(n, res);
          if (this.view === n && $("g-owner").checked) { this.board.ownership = res.ownership; this.board.draw(); }
        }
      }, { upto: n, visits: 100 });
    } else if (on && !engine.available() && !quiet) {
      this.setText("Карта территории доступна, когда запущен ИИ KataGo (вкладка «Настройки»).");
    }
  }

  // ------------------------------------------------------------------ подсказка и объяснение
  hint() {
    if (!this.live) this.goto(this.game.moves.length);
    const g = this.game;
    if (!engine.available()) {
      const p = chooseMove(g.board, g.toPlay, g.moves.length ? g.moves[g.moves.length - 1].point : null, 1);
      this.board.circles = new Map(p !== null ? [[p, GREEN]] : []);
      this.board.draw();
      if (p !== null) {
        this.setText(`Подсказка встроенного бота: ${toGtp(p, g.size)}\n` + tacticalFacts(g.board, g.toPlay, p).sentences.join(" ")
          + "\nТочную оценку и объяснения даёт ИИ KataGo (вкладка «Настройки»).");
      }
      return;
    }
    this.setText("ИИ ищет лучший ход…");
    const n = g.moves.length, color = g.toPlay;
    engine.analyzePosition(g, (a) => {
      if (!a || this.game.moves.length !== n) return;
      this.analyses.set(n, a);
      this.board.circles.clear();
      this.board.labels.clear();
      const s = color === BLACK ? 1 : -1;
      const top = a.moves.slice(0, 3);
      if (!top.length) return;
      const lines = ["Подсказка ИИ"];
      const bestVal = s * top[0].scoreLead;
      top.forEach((m, i) => {
        const p = fromGtp(m.move, g.size);
        const diff = bestVal - s * m.scoreLead;
        if (p !== null) this.board.labels.set(p, [String(i + 1), i === 0 ? GREEN : BLUE]);
        const tf = p !== null ? tacticalFacts(g.board, color, p) : null;
        const desc = tf && tf.sentences.length ? tf.sentences.join(" ") : "";
        const extra = i === 0 ? "" : diff >= 0.3 ? ` (хуже на ${pointsWord(diff)})` : " (почти так же хорошо)";
        lines.push(`${i + 1}. ${m.move}${extra}: ${desc || "ход укрепляет позицию."}`);
      });
      const b = top[0];
      if (b.pv.length) lines.push("Ожидаемое продолжение: " + pvText(b.pv, color) + ".");
      const wr = color === BLACK ? b.winrate : 1 - b.winrate;
      const lead = s * b.scoreLead;
      lines.push(`Оценка позиции: шансы ${color === BLACK ? "чёрных" : "белых"} ${(wr * 100).toFixed(0)}%, `
        + `${lead >= 0 ? "перевес" : "отставание"} около ${pointsGen(Math.abs(lead))}.`);
      this.setText(lines.join("\n"));
      this.board.draw();
    }, { visits: 300 });
  }

  explainCurrent() {
    const n = this.view;
    if (n === 0) return;
    if (this.reviews.has(n)) { this.showReview(n); return; }
    const g = this.game;
    const m = g.moves[n - 1];
    const before = g.boards[n - 1];
    if (!engine.available()) { this.setText(offlineExplanation(before, m.color, m.point, n)); return; }
    this.setText("ИИ разбирает ход…");
    const got = new Map();
    for (const k of [n - 1, n]) {
      engine.analyzePosition(g, (a) => {
        if (!a) return;
        got.set(k, a);
        if (!this.analyses.has(k)) this.analyses.set(k, a);
        if (got.size === 2 && this.game.moves.length >= n) {
          this.reviews.set(n, reviewMove(before, m.color, m.point, n, got.get(n - 1), got.get(n)));
          if (this.view === n) this.showReview(n);
        }
      }, { upto: k, visits: 300 });
    }
  }

  // ------------------------------------------------------------------ разбор партии
  reviewGame() {
    if (!engine.available() || !this.game.moves.length) return;
    const g = this.game;
    const total = g.moves.length + 1;
    const visits = store.get("katago/review_visits", 60);
    const prog = $("g-progress");
    prog.classList.remove("hidden");
    const setProg = (k) => { prog.firstElementChild.style.width = `${(100 * k) / total}%`; prog.lastElementChild.textContent = `Разбор партии: ${k} из ${total} позиций`; };
    setProg(0);
    const got = new Map();
    const snapshot = g.moves.length;
    this.reviewQuery = engine.analyzeGame(g, (a) => {
      if (this.game.moves.length !== snapshot) return;
      got.set(a.turn, a);
      setProg(got.size);
      if (got.size === total) {
        this.reviewQuery = null;
        prog.classList.add("hidden");
        this.finishReview(got);
      }
    }, visits);
    this.refresh();
  }

  finishReview(got) {
    const g = this.game;
    for (const [k, a] of got) this.analyses.set(k, a);
    const marks = new Map();
    for (let n = 1; n <= g.moves.length; n++) {
      const m = g.moves[n - 1];
      const r = reviewMove(g.boards[n - 1], m.color, m.point, n, got.get(n - 1), got.get(n));
      this.reviews.set(n, r);
      marks.set(n, r.mark);
    }
    this.graph.setData(new Map([...got].map(([n, a]) => [n, a.winrate])), g.moves.length, marks);
    const human = this.settings.human;
    const all = [...this.reviews.values()];
    const bad = all.filter((r) => r.loss >= 1.5).sort((a, b) => a.moveNumber - b.moveNumber);
    const counts = { [BLACK]: [0, 0, 0], [WHITE]: [0, 0, 0] };
    for (const r of all) {
      if (r.mark === "?!") counts[r.color][0]++;
      else if (r.mark === "?") counts[r.color][1]++;
      else if (r.mark === "??") counts[r.color][2]++;
    }
    const ul = $("g-mistakes");
    ul.innerHTML = "";
    for (const r of bad) {
      const li = document.createElement("li");
      const who = r.color === BLACK ? "Ч" : "Б";
      const pt = r.point !== null ? toGtp(r.point, g.size) : "пас";
      li.textContent = `Ход ${r.moveNumber} (${who} ${pt}) ${r.mark} ${r.label}: −${pointsWord(r.loss)}, лучше ${r.bestMove}`;
      li.className = human && r.color !== human ? "other" : r.mark === "??" ? "blunder" : r.mark === "?" ? "mistake" : "";
      li.onclick = () => this.gotoReview(r.moveNumber);
      ul.appendChild(li);
    }
    $("g-review-box").open = true;
    const lines = ["Разбор партии готов"];
    for (const [c, name] of [[BLACK, "Чёрные"], [WHITE, "Белые"]]) {
      const [a, b, cc] = counts[c];
      lines.push(`${name}: неточностей ${a}, ошибок ${b}, грубых ошибок ${cc}.`);
    }
    if (bad.length) {
      const worst = bad.reduce((w, r) => ((!human || r.color === human ? r.loss : -1) > (!human || w.color === human ? w.loss : -1) ? r : w), bad[0]);
      lines.push(`Самый важный момент: ход ${worst.moveNumber}. Коснитесь его в списке ошибок или на графике (ниже), `
        + "чтобы увидеть объяснение. Зелёный кружок — лучший ход, красный — сыгранный, цифры — ожидаемое продолжение.");
    }
    this.setText(lines.join("\n"));
    this.refresh();
  }

  // ------------------------------------------------------------------ файлы
  saveSgfFile() {
    const comments = {};
    for (const [n, r] of this.reviews) comments[n] = r.text;
    saveTextFile("партия.sgf", saveSgf(this.game, "", comments));
  }

  async openSgfFile() {
    const files = await pickFiles(".sgf,application/x-go-sgf,*/*");
    if (!files.length) return;
    try {
      const { decode } = await import("./sgfimport.js");
      const game = loadSgf(decode(new Uint8Array(await files[0].arrayBuffer())));
      this.startGame({ size: game.size, rules: game.rules, komi: game.komi, handicap: game.handicap, human: 0, level: this.settings.level }, game);
      this.setText(`Партия загружена: ${game.moves.length} ходов. Нажмите «Разбор партии», чтобы ИИ нашёл ошибки. `
        + "Партия открыта в режиме «вдвоём», её можно продолжить с любого хода.");
      showTab("game");
    } catch (e) { info("Ошибка", `Не удалось прочитать файл: ${e.message}`); }
  }
}

// ================================================================== Задачи
class ProblemsTab {
  constructor() {
    this.session = null;
    this.index = -1;
    this.levels = [];
    this.problems = [];
    this.board = new BoardView($("p-board"));
    this.board.onClick = (p) => this.onClick(p);
    this.board.confirmTap = () => this.session && confirmFor(this.session.problem.size) && !this.board.view;
    $("p-reset").onclick = () => this.reset();
    $("p-hint").onclick = () => this.hint();
    $("p-solution").onclick = () => this.showSolution();
    $("p-ai").onclick = () => this.aiReview();
    $("p-next").onclick = () => this.openProblem((this.index + 1) % this.problems.length);
    $("p-prev").onclick = () => this.openProblem((this.index - 1 + this.problems.length) % this.problems.length);
    $("p-list-btn").onclick = () => this.showList();
    $("p-list-close").onclick = () => $("p-list").classList.add("hidden");
    engine.onChange(() => this.refresh());
    $("p-title").textContent = "Загружаю задачи…";
  }

  async reload(openId = null) {
    [this.levels, this.problems] = await loadAll();
    this.byLevel = new Map();
    this.problems.forEach((p, i) => {
      if (!this.byLevel.has(p.level)) this.byLevel.set(p.level, []);
      this.byLevel.get(p.level).push(i);
    });
    this.levelById = new Map(this.levels.map((l) => [l.level, l]));
    this.updateProgress();
    const solved = this.solvedSet();
    const lastId = openId || store.get("problems/last", null);
    let idx = lastId ? this.problems.findIndex((p) => p.id === lastId) : -1;
    if (idx < 0) idx = Math.max(0, this.problems.findIndex((p) => !solved.has(p.id)));
    if (this.problems.length) this.openProblem(idx);
    this.treeBuilt = false;
  }

  solvedSet() { return new Set(store.get("problems/solved", [])); }
  markSolved(pid) {
    const s = this.solvedSet();
    s.add(pid);
    store.set("problems/solved", [...s]);
    this.updateProgress();
    const el = document.querySelector(`.prob[data-id="${CSS.escape(pid)}"]`);
    if (el) el.textContent = this.itemText(this.problems.find((p) => p.id === pid), true);
  }

  updateProgress() {
    const solved = this.solvedSet();
    const lib = new Set(this.levels.filter((l) => !isCourse(l.stage || "Основы")).map((l) => l.level));
    const course = this.problems.filter((p) => !lib.has(p.level));
    const extra = this.problems.filter((p) => lib.has(p.level));
    let text = `Курс: ${course.filter((p) => solved.has(p.id)).length} из ${course.length}`;
    if (extra.length) text += ` · Библиотека: ${extra.filter((p) => solved.has(p.id)).length} из ${extra.length.toLocaleString("ru-RU")}`;
    $("p-progress").textContent = text;
    $("p-list-progress").textContent = text;
  }

  itemText(p, solved) {
    if (p.id.startsWith("lib-")) return `${solved ? "✓" : "○"} ${p.title}`;
    const num = p.id.startsWith("imp") ? p.id.split("-").pop() : p.id;
    return `${solved ? "✓" : "○"} ${num}. ${p.title}`;
  }

  // ------------------------------------------------------------------ список задач
  showList() {
    if (!this.treeBuilt) this.buildTree();
    $("p-list").classList.remove("hidden");
    const cur = document.querySelector(".prob.cur");
    if (cur) cur.scrollIntoView({ block: "center" });
  }

  buildTree() {
    const tree = $("p-tree");
    tree.innerHTML = "";
    const order = new Map(STAGE_ORDER.map((s, i) => [s, i]));
    const levels = [...this.levels].sort((a, b) => (order.get(a.stage || "Основы") ?? 50) - (order.get(b.stage || "Основы") ?? 50) || a.level - b.level);
    const stages = new Map();
    const cur = this.problems[this.index];
    for (const lv of levels) {
      const stage = lv.stage || "Основы";
      const ids = this.byLevel.get(lv.level);
      if (!ids || !ids.length) continue;
      if (!stages.has(stage)) {
        const head = document.createElement("div");
        head.className = "stage";
        const body = document.createElement("div");
        const open = isCourse(stage) || (cur && this.levelById.get(cur.level)?.stage === stage);
        head.innerHTML = `<span class="caret">${open ? "▾" : "▸"}</span>${esc(stage)}`;
        body.style.display = open ? "" : "none";
        head.onclick = () => {
          const vis = body.style.display === "none";
          body.style.display = vis ? "" : "none";
          head.firstChild.textContent = vis ? "▾" : "▸";
        };
        tree.appendChild(head); tree.appendChild(body);
        stages.set(stage, body);
      }
      const body = stages.get(stage);
      const lh = document.createElement("div");
      lh.className = "level";
      const course = isCourse(stage);
      const list = document.createElement("div");
      const openLevel = course || (cur && cur.level === lv.level);
      lh.innerHTML = `<span class="caret">${openLevel ? "▾" : "▸"}</span>${esc(course ? lv.title : `${lv.title} — ${ids.length}`)}`;
      const fill = () => {
        if (list.childElementCount) return;
        const solved = this.solvedSet();
        const lesson = document.createElement("div");
        lesson.className = "lesson-link";
        lesson.textContent = "📘 Теория раздела";
        lesson.onclick = () => { $("p-list").classList.add("hidden"); this.showLesson(lv); };
        list.appendChild(lesson);
        for (const i of ids) {
          const p = this.problems[i];
          const el = document.createElement("div");
          el.className = "prob" + (i === this.index ? " cur" : "");
          el.dataset.id = p.id;
          el.textContent = this.itemText(p, solved.has(p.id));
          el.onclick = () => { $("p-list").classList.add("hidden"); this.openProblem(i); };
          list.appendChild(el);
        }
      };
      if (openLevel) fill(); else list.style.display = "none";
      lh.onclick = () => {
        const vis = list.style.display === "none";
        if (vis) fill();
        list.style.display = vis ? "" : "none";
        lh.firstChild.textContent = vis ? "▾" : "▸";
      };
      body.appendChild(lh); body.appendChild(list);
    }
    const imp = document.createElement("button");
    imp.textContent = "Импорт задач (SGF или ZIP)…";
    imp.style.margin = "16px 6px";
    imp.onclick = () => { $("p-list").classList.add("hidden"); importProblems(); };
    tree.appendChild(imp);
    this.treeBuilt = true;
  }

  showLesson(lv) {
    let html = `<h3>${esc(lv.title)}</h3><p>${esc(lv.lesson)}</p>`;
    if (lv.books) html += `<p><i>Что почитать: ${esc(lv.books)}</i></p>`;
    $("p-text").innerHTML = html;
    $("p-text").scrollIntoView({ behavior: "smooth" });
  }

  // ------------------------------------------------------------------ открыть задачу
  openProblem(i) {
    this.index = i;
    const p = this.problems[i];
    this.session = new ProblemSession(p);
    store.set("problems/last", p.id);
    for (const el of document.querySelectorAll(".prob.cur")) el.classList.remove("cur");
    const el = document.querySelector(`.prob[data-id="${CSS.escape(p.id)}"]`);
    if (el) el.classList.add("cur");
    const lv = this.levelById.get(p.level) || { title: "", lesson: "" };
    $("p-title").textContent = `${lv.title} — ${p.title}`;
    $("p-task").textContent = p.task;
    this.setStatus("Ваш ход.", null);
    $("p-text").innerHTML = this.introHtml(p, lv);
    this.setView();
    this.board.clearMarks();
    this.refresh();
  }

  introHtml(p, lv) {
    const parts = [];
    if (p.concept) parts.push(`<p><b>Что изучаем.</b> ${esc(p.concept)}</p>`);
    if (p.why) parts.push(`<p><b>Зачем это в партии.</b> ${esc(p.why)}</p>`);
    if (!parts.length) parts.push(`<p><b>Теория раздела.</b> ${esc(lv.lesson)}</p>`);
    if (p.source) parts.push(`<p style="color:gray"><i>По мотивам: ${esc(p.source)}</i></p>`);
    if (p.kind === "whole") parts.push("<p style='color:gray'>Здесь нет единственного ответа: правильными считаются ходы, которые сильный ИИ оценивает почти одинаково с лучшим. Важно понять идею.</p>");
    return parts.join("");
  }

  // Для угловых задач на большой доске показываем только нужную часть
  setView() {
    const p = this.problems[this.index];
    const b = this.session.game.initial;
    const n = b.size;
    if (n <= 9 || p.kind === "whole") { this.board.view = null; return; }
    const pts = [];
    for (let q = 0; q < b.n; q++) if (b.get(q) !== EMPTY) pts.push(q);
    if (!pts.length) { this.board.view = null; return; }
    const m = 2;
    let x0 = Math.max(0, Math.min(...pts.map((q) => q % n)) - m), x1 = Math.min(n - 1, Math.max(...pts.map((q) => q % n)) + m);
    let y0 = Math.max(0, Math.min(...pts.map((q) => Math.floor(q / n))) - m), y1 = Math.min(n - 1, Math.max(...pts.map((q) => Math.floor(q / n))) + m);
    while (x1 - x0 < 8) { if (x0 > 0) x0--; if (x1 - x0 < 8 && x1 < n - 1) x1++; }
    while (y1 - y0 < 8) { if (y0 > 0) y0--; if (y1 - y0 < 8 && y1 < n - 1) y1++; }
    this.board.view = x1 - x0 >= n - 3 && y1 - y0 >= n - 3 ? null : [x0, y0, x1, y1];
  }

  refresh() {
    const s = this.session;
    if (!s) return;
    const p = s.problem;
    this.board.board = s.board;
    this.board.lastMove = s.game.moves.length ? s.game.moves[s.game.moves.length - 1].point : null;
    this.board.marked = new Set(p.marked.map((m) => fromGtp(m, p.size)).filter((q) => s.board.get(q) !== EMPTY));
    this.board.ghostColor = s.solved || s.failed ? null : s.game.toPlay;
    this.board.interactive = !(s.solved || s.failed);
    $("p-ai").disabled = !engine.available();
    this.board.draw();
  }

  setStatus(text, color) {
    const el = $("p-status");
    el.textContent = text;
    el.style.color = color || "inherit";
  }

  reset() { this.openProblem(this.index); }
  oppName() { return this.session.problem.toPlay === BLACK ? "Белые" : "Чёрные"; }

  // ------------------------------------------------------------------ ходы
  onClick(pt) {
    const s = this.session;
    if (!s || s.solved || s.failed) return;
    const before = s.board.copy();
    const color = s.game.toPlay;
    const ans = s.play(pt);
    if (ans.kind === "illegal") { this.setStatus(ans.comment, "#c66a00"); return; }
    const size = s.problem.size;
    const mv = toGtp(pt, size);
    const tactic = tacticalFacts(before, color, pt, false).sentences.join(" ");
    const opp = this.oppName();
    this.board.clearMarks();
    let parts;
    if (ans.kind === "correct" || ans.kind === "solved") {
      parts = [`<p><b>${mv} — ${ans.kind === "solved" ? "задача решена!" : "правильно."}</b></p>`, `<p>${esc(ans.comment)}</p>`];
      if (ans.reply !== null && ans.reply !== undefined) {
        const rc = esc(ans.replyComment);
        parts.push(`<p>${opp} отвечают ${toGtp(ans.reply, size)}. ${rc}${ans.kind === "correct" ? " Ваш ход." : ""}</p>`);
      }
      if (ans.kind === "solved" && s.problem.concept) parts.push(`<p style="color:#1a7f3c"><b>Запомните:</b> ${esc(s.problem.concept)}</p>`);
      if (ans.kind === "solved") { this.setStatus("✓ Решено!", "#1aa34a"); this.markSolved(s.problem.id); }
      else this.setStatus("Правильно! Продолжайте.", "#1aa34a");
    } else if (ans.kind === "wrong") {
      parts = [`<p><b>${mv} — не получается.</b></p>`, `<p>${esc(ans.comment)}</p>`];
      if (ans.reply !== null && ans.reply !== undefined) parts.push(`<p>Ответ соперника: ${toGtp(ans.reply, size)} (последний ход на доске).</p>`);
      parts.push("<p>Нажмите «Заново», чтобы попробовать ещё раз, или «Решение».</p>");
      this.setStatus("✗ Неверно", "#d93025");
    } else {
      parts = [`<p><b>${mv} — это не решение задачи.</b></p>`];
      if (tactic) parts.push(`<p>Что делает ваш ход: ${esc(tactic)}</p>`);
      parts.push(`<p>Подсказка: ${esc(s.problem.hint)}</p>`);
      if (engine.available()) parts.push("<p>Нажмите «Разбор с ИИ», и KataGo покажет, как соперник опровергает этот ход.</p>");
      parts.push("<p>Нажмите «Заново», чтобы попробовать ещё раз.</p>");
      this.setStatus("✗ Неверно", "#d93025");
    }
    $("p-text").innerHTML = parts.join("");
    this.refresh();
  }

  hint() {
    const s = this.session;
    if (!s) return;
    let html = `<p><b>Подсказка</b></p><p>${esc(s.problem.hint)}</p>`;
    if (s.problem.concept) html += `<p>Вспомните идею: ${esc(s.problem.concept)}</p>`;
    const exp = s.expectedMoves();
    if (exp.length && !(s.solved || s.failed)) html += `<p>Ищите ход ${regionHint(fromGtp(exp[0], s.problem.size), s.problem.size)}.</p>`;
    $("p-text").innerHTML = html;
  }

  showSolution() {
    if (!this.session) return;
    this.reset();
    const s = this.session;
    const line = solutionLine(s.problem);
    if (!line.length) return;
    const size = s.problem.size;
    line.forEach(([mv], i) => {
      const p = fromGtp(mv, size);
      if (p !== null && !this.board.labels.has(p)) this.board.labels.set(p, [String(i + 1), i % 2 === 0 ? GREEN : BLUE]);
    });
    const me = s.problem.toPlay === BLACK ? "Чёрные" : "Белые";
    const opp = this.oppName();
    const parts = ["<p><b>Решение</b> (зелёные цифры — ваши ходы, синие — ответы соперника)</p>"];
    line.forEach(([mv, c], i) => parts.push(`<p><b>${i + 1}. ${i % 2 === 0 ? me : opp} ${mv}.</b> ${esc(c)}</p>`));
    const others = (s.problem.tree.next || []).slice(1).map((n) => n.move);
    if (others.length) parts.push(`<p>Тоже правильно: ${others.join(", ")}.</p>`);
    if (s.problem.concept) parts.push(`<p><b>Идея:</b> ${esc(s.problem.concept)}</p>`);
    $("p-text").innerHTML = parts.join("");
    this.setStatus("Посмотрите решение и попробуйте сами (кнопка «Заново»).", null);
    s.failed = true;
    this.refresh();
  }

  // ------------------------------------------------------------------ ИИ
  aiReview() {
    if (!engine.available() || !this.session) return;
    const s = this.session;
    const game = s.game;
    const color = game.toPlay;
    const board = game.board.copy();
    const refuting = game.moves.length > 0 && color !== s.problem.toPlay;
    const allow = s.problem.kind === "whole" ? null : localRegion(board);
    $("p-text").innerHTML = "<p>ИИ анализирует позицию…</p>";
    const nMoves = game.moves.length;
    const sess = s;
    engine.analyzePosition(game, (a) => {
      if (!a || !a.moves.length || this.session !== sess || sess.game.moves.length !== nMoves) return;
      const who = color !== BLACK ? "белых" : "чёрных";
      const best = a.moves[0];
      const bp = fromGtp(best.move, board.size);
      this.board.clearMarks();
      this.refresh();
      const parts = [refuting ? "<p><b>Как соперник наказывает ваш ход</b></p>" : `<p><b>Разбор ИИ: лучший ход ${who} в этой позиции</b></p>`];
      if (bp !== null) {
        this.board.circles.set(bp, refuting ? RED : GREEN);
        parts.push(`<p><b>${best.move}</b>. ${esc(tacticalFacts(board, color, bp, false).sentences.join(" "))}</p>`);
      }
      const sign = color === BLACK ? 1 : -1;
      const alts = a.moves.slice(1, 4).filter((m) => m.visits >= 5);
      if (s.problem.kind === "whole" && alts.length) {
        const rows = alts.map((m) => { const d = sign * (best.scoreLead - m.scoreLead); return d >= 0.1 ? `${m.move} (−${d.toFixed(1)})` : `${m.move} (так же хорошо)`; });
        parts.push(`<p>Другие ходы: ${rows.join(", ")}.</p>`);
      }
      if (best.pv.length) {
        best.pv.slice(0, 8).forEach((mv, i) => {
          const p = fromGtp(mv, board.size);
          if (p !== null && !this.board.labels.has(p) && board.get(p) === EMPTY) this.board.labels.set(p, [String(i + 1), BLUE]);
        });
        parts.push(`<p>Продолжение: ${pvText(best.pv, color, 8)}.</p>`);
      }
      if (a.ownership && s.problem.kind !== "whole") parts.push("<p><b>Итог по оценке ИИ:</b></p>" + groupSummary(board, a.ownership));
      parts.push("<p>Цифры на доске — ожидаемый порядок ходов.</p>");
      $("p-text").innerHTML = parts.join("");
      this.board.draw();
    }, { visits: 500, allowMoves: allow });
  }
}

function regionHint(p, size) {
  const x = p % size, y = Math.floor(p / size);
  const horiz = x < size / 3 ? "слева" : x >= (2 * size) / 3 ? "справа" : "";
  const vert = y < size / 3 ? "вверху" : y >= (2 * size) / 3 ? "внизу" : "";
  if (!horiz && !vert) return "в центральной части доски";
  return [vert, horiz].filter((t) => t).join(", ");
}

function groupSummary(board, ownership) {
  const rows = [];
  for (const [st] of board.groups()) {
    if (st.size < 3) continue;
    const c = board.get(st.values().next().value);
    let own = 0;
    for (const q of st) own += ownership[q];
    own /= st.size;
    const alive = c === BLACK ? own : -own;
    const state = alive > 0.6 ? "живёт" : alive < -0.6 ? "погибает" : "под вопросом";
    rows.push(`<li>${c === BLACK ? "Чёрная" : "Белая"} группа из ${genitiveStones(st.size)} ${groupArea(st, board.size)}: ${state}</li>`);
  }
  return rows.length ? "<ul>" + rows.join("") + "</ul>" : "";
}

// ================================================================== Импорт задач
async function importProblems() {
  const files = await pickFiles(".sgf,.zip,application/zip,application/x-go-sgf,*/*");
  if (!files.length) return;
  toast("Читаю файлы…");
  const items = [];
  try {
    for (const f of files) {
      const buf = new Uint8Array(await f.arrayBuffer());
      if (f.name.toLowerCase().endsWith(".zip") || (buf[0] === 0x50 && buf[1] === 0x4b)) {
        const base = f.name.replace(/\.zip$/i, "");
        for (const e of await readZip(buf)) {
          if (!e.name.toLowerCase().endsWith(".sgf")) continue;
          const parts = e.name.split("/");
          const name = parts.pop();
          items.push({ name, folder: parts.length ? parts[parts.length - 1] : base, bytes: await inflate(e) });
        }
      } else items.push({ name: f.name, folder: "Выбранные файлы", bytes: buf });
    }
  } catch (e) { info("Импорт", `Не удалось прочитать файлы: ${e.message}`); return; }
  if (!items.length) { info("Импорт", "SGF-файлы не найдены."); return; }
  let data = { levels: [], problems: [] };
  try { const old = await store.getBig("imported_problems"); if (old) data = JSON.parse(old); } catch { /* новый файл */ }
  const [added, skipped] = importInto(data, items);
  await store.setBig("imported_problems", JSON.stringify(data));
  let msg = `Добавлено задач: ${added}.`;
  if (skipped) msg += ` Пропущено файлов (нет решения или это лекция без вопроса): ${skipped}.`;
  await info("Импорт", msg + "\nОни в разделе «Мои сборники».");
  await problemsTab.reload();
  showTab("problems");
}

// ================================================================== Настройки
// Список нейросетей для скачивания (data/models.json готовит сборка на GitHub)
const MODEL_TITLES = { b10: "Быстрая (b10) — встроена", b20: "Сильная (b20) — как в версии для компьютера, думает дольше" };
let MODELS = [];
fetch("data/models.json").then((r) => (r.ok ? r.json() : [])).then((list) => {
  MODELS = list.map((m) => {
    const k = (m.file.match(/-(b\d+)c/) || [])[1];
    return { ...m, title: `${MODEL_TITLES[k] || m.file}, ${Math.round(m.size / 1048576)} МБ` };
  });
}).catch(() => {});

function engineSettings() {
  return { model: store.get("katago/model", ""), threads: store.get("katago/threads", 0) };
}

function renderSettings() {
  const infoObj = engine.getInfo();
  const models = infoObj.models || [];
  const sel = $("s-model");
  const cur = store.get("katago/model", "");
  sel.innerHTML = models.length
    ? models.map((m) => `<option value="${esc(m.name)}" ${m.name === cur ? "selected" : ""}>${esc((MODELS.find((x) => x.file === m.name) || {}).title || `${m.name}, ${Math.round(m.size / 1048576)} МБ`)}</option>`).join("")
    : "<option value=''>нет установленных нейросетей</option>";
  if (!cur && models.length) sel.value = models.reduce((a, b) => (a.size <= b.size ? a : b)).name;
  $("s-models-info").textContent = engine.hasBridge
    ? (infoObj.hasBinary ? `Процессор: ${infoObj.abi}, ядер: ${infoObj.cores}.` : `KataGo не собран для процессора этого устройства (${infoObj.abi}). Работает встроенный бот.`)
    : "Это не Android-приложение: KataGo недоступен.";
  const dl = $("s-downloads");
  dl.innerHTML = "";
  for (const m of MODELS) {
    if (models.some((x) => x.name === m.file)) continue;
    const b = document.createElement("button");
    b.textContent = `Скачать: ${m.title.split(" — ")[0]}`;
    b.onclick = () => {
      if (!engine.hasBridge) return;
      b.disabled = true;
      engine.bridge.downloadModel(m.url, m.file);
    };
    dl.appendChild(b);
  }
  const cores = infoObj.cores || navigator.hardwareConcurrency || 4;
  $("s-threads").innerHTML = [0, 1, 2, 3, 4, 6, 8].filter((n) => n <= Math.max(cores, 2)).map((n) =>
    `<option value="${n}" ${n === store.get("katago/threads", 0) ? "selected" : ""}>${n || "авто"}</option>`).join("");
  $("s-visits").innerHTML = [20, 40, 60, 100, 200, 400].map((n) =>
    `<option value="${n}" ${n === store.get("katago/review_visits", 60) ? "selected" : ""}>${n}${n === 60 ? " (рекомендуется)" : ""}</option>`).join("");
  $("s-engine").textContent = engine.status;
  $("s-confirm19").checked = store.get("confirm19", true);
  $("s-confirm9").checked = store.get("confirm9", false);
  if (engine.hasBridge && engine.bridge.appVersion) $("s-version").textContent = "Версия " + engine.bridge.appVersion();
}

function initSettings() {
  $("s-restart").onclick = () => {
    store.set("katago/model", $("s-model").value);
    store.set("katago/threads", +$("s-threads").value);
    store.set("katago/review_visits", +$("s-visits").value);
    engine.start(engineSettings());
    toast("Перезапускаю ИИ…");
  };
  $("s-visits").onchange = () => store.set("katago/review_visits", +$("s-visits").value);
  $("s-confirm19").onchange = () => store.set("confirm19", $("s-confirm19").checked);
  $("s-confirm9").onchange = () => store.set("confirm9", $("s-confirm9").checked);
  $("s-open").onclick = () => gameTab.openSgfFile();
  $("s-save").onclick = () => gameTab.saveSgfFile();
  $("s-import").onclick = () => importProblems();
  $("s-clear-imported").onclick = async () => {
    if (!(await confirmBox("Импорт", "Удалить все импортированные задачи?"))) return;
    await store.setBig("imported_problems", null);
    await problemsTab.reload();
    toast("Импортированные задачи удалены");
  };
  $("s-reset-progress").onclick = async () => {
    if (!(await confirmBox("Задачи", "Сбросить все отметки о решённых задачах?"))) return;
    store.set("problems/solved", []);
    problemsTab.treeBuilt = false;
    problemsTab.updateProgress();
    toast("Отметки сброшены");
  };
  engine.onChange((ready, text) => { $("s-engine").textContent = text; });
  engine.onDownload = (what, done, total, state) => {
    const box = $("s-dl");
    box.classList.remove("hidden");
    if (state === "progress") {
      box.firstElementChild.style.width = total ? `${(100 * done) / total}%` : "50%";
      box.lastElementChild.textContent = `Скачиваю ${what}: ${Math.round(done / 1048576)} МБ` + (total ? ` из ${Math.round(total / 1048576)} МБ` : "");
    } else {
      box.classList.add("hidden");
      if (state === "done") { store.set("katago/model", what); toast("Нейросеть скачана, перезапускаю ИИ"); engine.start(engineSettings()); }
      else info("Скачивание", `Не получилось скачать: ${done}`);
      renderSettings();
    }
  };
}

// ================================================================== вкладки и запуск
function showTab(name) {
  for (const s of document.querySelectorAll(".tab")) s.classList.toggle("active", s.id === `tab-${name}`);
  for (const b of document.querySelectorAll("nav.tabs button")) b.classList.toggle("active", b.dataset.tab === name);
  if (name === "settings") renderSettings();
  if (name === "game") gameTab.board.resize();
  if (name === "problems") problemsTab.board.resize();
  window.scrollTo(0, 0);
}
for (const b of document.querySelectorAll("nav.tabs button")) b.onclick = () => showTab(b.dataset.tab);

// Кнопка «Назад» Android: закрыть окно/список, иначе вернуться на «Партию»
window.__onBack = () => {
  if (!$("modal").classList.contains("hidden")) { $("modal-buttons").firstElementChild?.click(); return true; }
  if (!$("p-list").classList.contains("hidden")) { $("p-list").classList.add("hidden"); return true; }
  if (!$("tab-game").classList.contains("active")) { showTab("game"); return true; }
  return false;
};

const gameTab = new GameTab();
const problemsTab = new ProblemsTab();
initSettings();
problemsTab.reload().catch((e) => { $("p-title").textContent = "Не удалось загрузить задачи: " + e.message; });
engine.start(engineSettings());
window.__app = { gameTab, problemsTab, engine, showTab };

// Самопроверка для автоматического теста: запрос к KataGo через мост и загрузка задач
if (location.search.includes("selftest")) {
  let done = false;
  engine.onChange((ready) => {
    if (!ready || done) return;
    done = true;
    engine.analyzePosition(gameTab.game, (a) => {
      console.log(`[selftest] analysis ${a && a.moves.length ? "ok " + a.moves[0].move : "FAILED"}; problems ${problemsTab.problems.length}`);
    }, { visits: 20 });
  });
}
