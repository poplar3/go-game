// Объяснение ходов простым языком.
// 1. Тактический разбор позиции (атари, захват, спасение группы, лестница, глаза,
//    соединение и разрезание). Работает всегда, даже без ИИ.
// 2. Оценка KataGo: сколько очков стоит ход, что было лучше, какие группы живут или умирают.
import { BLACK, EMPTY, other, toGtp, fromGtp, IllegalMove } from "./board.js";

// ---------------------------------------------------------------- числа и слова
export function pyRound(x) { // округление как в Python (к чётному)
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-12) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}
const strip0 = (s) => (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s);

export function areaName(p, size) {
  const x = p % size, y = Math.floor(p / size);
  const edge = size <= 9 ? 3 : size <= 13 ? 4 : 6;
  const left = x < edge, right = x >= size - edge, top = y < edge, bottom = y >= size - edge;
  if (top && left) return "в левом верхнем углу";
  if (top && right) return "в правом верхнем углу";
  if (bottom && left) return "в левом нижнем углу";
  if (bottom && right) return "в правом нижнем углу";
  if (top) return "вверху";
  if (bottom) return "внизу";
  if (left) return "слева";
  if (right) return "справа";
  return "в центре";
}

export function groupArea(stones, size) {
  const arr = [...stones];
  const xs = arr.map((p) => p % size).sort((a, b) => a - b);
  const ys = arr.map((p) => Math.floor(p / size)).sort((a, b) => a - b);
  const m = Math.floor(xs.length / 2);
  return areaName(ys[m] * size + xs[m], size);
}

export function stonesWord(n) {
  if (n % 10 === 1 && n % 100 !== 11) return `${n} камень`;
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return `${n} камня`;
  return `${n} камней`;
}

export function pointsWord(x) {
  const n = pyRound(Math.abs(x));
  let w;
  if (n % 10 === 1 && n % 100 !== 11) w = "очко";
  else if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) w = "очка";
  else w = "очков";
  return Math.abs(x) < 10 ? strip0(Math.abs(x).toFixed(1)) + ` ${w}` : `${n} ${w}`;
}

// Родительный падеж: «около 1 очка», «около 5 очков»
export function pointsGen(x) {
  const n = Math.abs(x);
  const num = n < 10 ? strip0(n.toFixed(1)) : String(pyRound(n));
  return `${num} ${num === "1" || num.includes(".") ? "очка" : "очков"}`;
}

export function lineOf(p, size) {
  const x = p % size, y = Math.floor(p / size);
  return Math.min(x, y, size - 1 - x, size - 1 - y) + 1;
}

export function genitiveStones(n) {
  return n % 10 === 1 && n % 100 !== 11 ? `${n} камня` : `${n} камней`;
}

const first = (set) => set.values().next().value;

// ---------------------------------------------------------------- тактическое чтение
// Можно ли захватить группу с камнем target (лестница/простая погоня)?
export function captureSearch(board, target, attacker, attackerToMove, depth = 0, maxDepth = 80) {
  if (board.get(target) === EMPTY || board.get(target) === attacker) return true;
  if (depth > maxDepth) return false;
  const defender = other(attacker);
  const [stones, libs] = board.group(target);
  if (attackerToMove) {
    if (libs.size === 1) return true;
    if (libs.size >= 3) return false;
    for (const lib of libs) {
      const b = board.copy();
      try { b.play(attacker, lib); } catch { continue; }
      if (captureSearch(b, target, attacker, false, depth + 1, maxDepth)) return true;
    }
    return false;
  }
  if (libs.size >= 3) return false;
  const candidates = new Set(libs);
  // защитник может спастись, захватив окружающие камни, находящиеся в атари
  for (const s of stones) for (const nb of board.neighbors(s)) {
    if (board.get(nb) === attacker) {
      const [, alibs] = board.group(nb);
      if (alibs.size === 1) for (const l of alibs) candidates.add(l);
    }
  }
  for (const mv of candidates) {
    const b = board.copy();
    try { b.play(defender, mv); } catch { continue; }
    if (!captureSearch(b, target, attacker, true, depth + 1, maxDepth)) return false;
  }
  return true;
}

export function eyePoints(board, stones, color) {
  const res = new Set();
  for (const s of stones) for (const nb of board.neighbors(s)) if (board.isEyeLike(nb, color)) res.add(nb);
  return res;
}

function near(stones, p, size, dist = 2) {
  const px = p % size, py = Math.floor(p / size);
  for (const s of stones) if (Math.abs((s % size) - px) + Math.abs(Math.floor(s / size) - py) <= dist) return true;
  return false;
}

function sameSet(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function isCutDiagonal(board, p, opp) {
  const size = board.size, x = p % size, y = Math.floor(p / size);
  const on = (a, b) => a >= 0 && a < size && b >= 0 && b < size;
  for (const [dx, dy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    if (on(x + dx, y) && on(x, y + dy) && on(x + dx, y + dy)) {
      const a = y * size + x + dx, b = (y + dy) * size + x, c = (y + dy) * size + x + dx;
      if (board.get(a) === opp && board.get(b) === opp && board.get(c) === other(opp)) {
        if (!sameSet(board.group(a)[0], board.group(b)[0])) return true;
      }
    }
  }
  return false;
}

function isSnapbackLike(after, p, color) {
  const lib = first(after.group(p)[1]);
  const b = after.copy();
  try { b.play(other(color), lib); } catch { return false; }
  const [st, lb] = b.group(lib);
  return lb.size === 1 && st.size >= 2;
}

export function nom(board, stones) {
  if (stones.size === 1) return `камень ${toGtp(first(stones), board.size)}`;
  return `группа из ${genitiveStones(stones.size)} ${groupArea(stones, board.size)}`;
}
export function gen(board, stones) {
  if (stones.size === 1) return `камня ${toGtp(first(stones), board.size)}`;
  return `группы из ${genitiveStones(stones.size)} ${groupArea(stones, board.size)}`;
}
export function acc(board, stones) {
  if (stones.size === 1) return `камень ${toGtp(first(stones), board.size)}`;
  return `группу из ${genitiveStones(stones.size)} ${groupArea(stones, board.size)}`;
}
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

// Что делает ход с точки зрения тактики
export function tacticalFacts(board, color, p, opening = true) {
  const facts = { sentences: [], captured: 0, atariGroups: [], saved: false, selfAtari: false, fillsOwnEye: false, illegal: null };
  const size = board.size;
  const S = facts.sentences;
  if (p === null || p === undefined) { S.push("Пас: игрок пропускает ход."); return facts; }
  const opp = other(color);
  const after = board.copy();
  let captured;
  try { captured = after.play(color, p); } catch (e) {
    facts.illegal = e.message;
    S.push(`Этот ход невозможен: ${e.message}.`);
    return facts;
  }
  const [myStones, myLibs] = after.group(p);

  if (captured.length) { // захват
    facts.captured = captured.length;
    S.push(`Забирает ${stonesWord(captured.length)} соперника.`);
    if (after.koPoint !== null) S.push("Это ко: соперник не сможет сразу отбить камень и должен сначала сыграть в другом месте (угрозу ко).");
  }
  if (board.isEyeLike(p, color)) { // заполнение собственного глаза
    facts.fillsOwnEye = true;
    S.push("Ход заполняет собственный глаз. Это почти всегда ошибка: группе для жизни нужны два глаза.");
  }
  for (const nb of board.neighbors(p)) { // спасение своих групп из атари
    if (board.get(nb) === color) {
      const [st, lb] = board.group(nb);
      if (lb.size === 1) {
        if (myLibs.size >= 2) {
          if (captureSearch(after, p, opp, true)) {
            S.push(`Пытается спасти ${acc(board, st)} из атари, но это не помогает: соперник всё равно поймает группу в лестницу или сеть.`);
          } else {
            facts.saved = true;
            S.push(`Спасает ${acc(board, st)} из атари: у группы теперь ${myLibs.size} дамэ.`);
          }
        }
        break;
      }
    }
  }
  if (captured.length && !facts.saved) {
    for (const [st, lb] of board.groups(color)) {
      if (lb.size !== 1 || lb.has(p)) continue;
      const afterLibs = after.group(first(st))[1];
      if (afterLibs.size >= 2) {
        S.push(`Захват заодно спасает из атари ${acc(board, st)}.`);
        facts.saved = true;
        break;
      }
    }
  }
  const seen = new Set(); // атари и давление
  for (const nb of after.neighbors(p)) {
    if (after.get(nb) === opp && !seen.has(nb)) {
      const [st, lb] = after.group(nb);
      for (const s of st) seen.add(s);
      const beforeLibs = board.group(nb)[1];
      if (lb.size === 1) {
        facts.atariGroups.push(st);
        if (myLibs.size === 1 && !captured.length) continue;
        if (captureSearch(after, nb, color, false)) {
          S.push(`Ставит атари: ${nom(after, st)} не может убежать — если соперник попробует вытянуть камни, получится лестница или сеть, и он потеряет ещё больше.`);
        } else {
          S.push(`Ставит атари: у ${gen(after, st)} осталось одно дамэ, его нужно срочно спасать.`);
        }
      } else if (lb.size === 2 && beforeLibs.size > 2) {
        if (captureSearch(after, nb, color, false)) {
          S.push(`${cap(nom(after, st))} попадает в ловушку (лестница или сеть): убежать уже не получится.`);
        } else if (st.size >= 2) {
          S.push(`Сокращает дамэ: у ${gen(after, st)} остаётся только 2 дамэ.`);
        }
      } else if (lb.size === 3 && beforeLibs.size > 3 && st.size >= 2) {
        S.push(`Давит на ${acc(after, st)}: у неё остаётся 3 дамэ, ей становится тесно.`);
      }
    }
  }
  if (myLibs.size === 1 && !captured.length) { // самоатари
    facts.selfAtari = true;
    if (myStones.size === 1 && isSnapbackLike(after, p, color)) {
      S.push("Камень жертвуется: соперник может его снять, но тогда сам попадёт под захват (снэпбэк) или потеряет форму. Жертва — важный приём.");
    } else {
      S.push(`Опасно: после хода ${nom(after, myStones)} оказывается в атари, и соперник может это снять.`);
    }
  }
  // соединение и разрезание
  const groupKey = (st) => Math.min(...st);
  const ownGroups = new Map();
  for (const nb of board.neighbors(p)) if (board.get(nb) === color) { const st = board.group(nb)[0]; ownGroups.set(groupKey(st), st); }
  if (ownGroups.size >= 2) S.push(`Соединяет ${ownGroups.size} группы в одну: соединённые камни сильнее и их труднее окружить.`);
  const oppGroups = new Set();
  for (const nb of board.neighbors(p)) if (board.get(nb) === opp) oppGroups.add(groupKey(board.group(nb)[0]));
  if (oppGroups.size >= 2 && !captured.length) S.push("Встаёт между камнями соперника и разрезает их: разделённые группы слабее.");
  else if (isCutDiagonal(board, p, opp)) S.push("Разрезает камни соперника по диагонали.");

  for (const [st] of board.groups(opp)) { // глаза
    if (near(st, p, size)) {
      const eBefore = eyePoints(board, st, opp).size;
      if (after.get(first(st)) !== opp) continue;
      const stAfter = after.group(first(st))[0];
      const eAfter = eyePoints(after, stAfter, opp).size;
      if (eAfter < eBefore) { S.push(`Разрушает глаз у ${gen(after, stAfter)}: без двух глаз группа не может жить.`); break; }
    }
  }
  const union = new Set();
  for (const g of ownGroups.values()) for (const s of g) union.add(s);
  if (union.size) {
    const eBefore = eyePoints(board, union, color).size;
    const eAfter = eyePoints(after, myStones, color).size;
    if (eAfter > eBefore && !facts.fillsOwnEye) S.push("Помогает своей группе сделать глаз.");
  }
  let stonesOnBoard = 0; // дебют
  for (let q = 0; q < board.n; q++) if (board.get(q) !== EMPTY) stonesOnBoard++;
  if (opening && stonesOnBoard < Math.max(6, Math.floor(size / 2)) && !S.length) {
    const line = lineOf(p, size);
    const area = areaName(p, size);
    if (area.includes("угл")) {
      const corner = { "в левом верхнем углу": "левый верхний угол", "в правом верхнем углу": "правый верхний угол",
        "в левом нижнем углу": "левый нижний угол", "в правом нижнем углу": "правый нижний угол" }[area];
      S.push(`Занимает ${corner}: в начале партии углы самые ценные, там территорию окружить легче всего.`);
    }
    if (line === 3) S.push("3-я линия — линия территории: камень надёжно забирает край.");
    else if (line === 4) S.push("4-я линия — линия влияния: камень смотрит в центр, но территория под ним менее надёжна.");
    else if (line <= 2) S.push("В начале партии ходы на 1-й и 2-й линии слишком низкие: они берут мало территории.");
  }
  return facts;
}

// ---------------------------------------------------------------- оценка ИИ
export function verdict(loss) {
  if (loss < 0.5) return ["отличный ход", "!"];
  if (loss < 1.5) return ["хороший ход", ""];
  if (loss < 3.5) return ["неточность", "?!"];
  if (loss < 8) return ["ошибка", "?"];
  return ["грубая ошибка", "??"];
}

const sign = (color) => (color === BLACK ? 1 : -1);
const yours = (board, stones) => (stones.size === 1 ? "ваш " : "ваша ") + nom(board, stones);

export function groupStatusChanges(boardAfter, color, ownRef, ownNew) {
  const S = [];
  for (const [stones] of boardAfter.groups()) {
    const c = boardAfter.get(first(stones));
    const s = sign(c);
    let ref = 0, nw = 0;
    for (const q of stones) { ref += s * ownRef[q]; nw += s * ownNew[q]; }
    ref /= stones.size; nw /= stones.size;
    if (stones.size < 2 && Math.abs(ref - nw) < 1.0) continue;
    if (c === color && ref > 0.25 && nw < -0.25) {
      S.push(`После этого хода погибает ${yours(boardAfter, stones)}, хотя при правильной игре это можно было предотвратить.`);
    } else if (c !== color && ref < -0.25 && nw > 0.25) {
      S.push(`Упущена возможность: лучший ход оставлял без жизни ${acc(boardAfter, stones)} соперника, а теперь соперник успевает спастись.`);
    }
  }
  return S;
}

export function territoryShift(color, ownRef, ownNew, size) {
  const s = sign(color);
  const lost = [];
  let total = 0;
  for (let i = 0; i < size * size; i++) {
    const d = s * (ownNew[i] - ownRef[i]);
    if (d < -0.3) { lost.push(i); total += -d / 2; }
  }
  if (!lost.length) return [0, null];
  return [total, groupArea(new Set(lost), size)];
}

const dist = (a, b, size) => Math.max(Math.abs((a % size) - (b % size)), Math.abs(Math.floor(a / size) - Math.floor(b / size)));

export function pvText(pv, firstColor, limit = 6) {
  const out = [];
  let c = firstColor;
  for (const mv of pv.slice(0, limit)) {
    out.push((c === BLACK ? "Ч " : "Б ") + (mv.toLowerCase() === "pass" ? "пас" : mv));
    c = other(c);
  }
  return out.join(", ");
}

export function infoFor(analysis, gtp) {
  return analysis.moves.find((m) => m.move.toUpperCase() === gtp.toUpperCase()) || null;
}

const lowerFirst = (t) => (t ? t[0].toLowerCase() + t.slice(1) : t);

// Полное объяснение одного хода на основе анализа до и после него
export function reviewMove(boardBefore, color, point, moveNumber, before, after) {
  const size = boardBefore.size;
  const s = sign(color);
  const gtp = toGtp(point, size);
  const best = before.moves[0] || null;
  const bestValue = s * (best ? best.scoreLead : before.scoreLead);
  let playedValue, wrAfter;
  if (after) {
    playedValue = s * after.scoreLead;
    wrAfter = color === BLACK ? after.winrate : 1 - after.winrate;
  } else {
    const info = infoFor(before, gtp);
    playedValue = info ? s * info.scoreLead : bestValue;
    wrAfter = info ? (color === BLACK ? info.winrate : 1 - info.winrate) : 0.5;
  }
  const bestWr = best ? best.winrate : before.winrate;
  const wrBefore = color === BLACK ? bestWr : 1 - bestWr;
  let loss = Math.max(0, bestValue - playedValue);
  const isBest = best !== null && best.move.toUpperCase() === gtp.toUpperCase();
  if (isBest) loss = 0;
  const [label, mark] = verdict(loss);

  const who = color === BLACK ? "Чёрные" : "Белые";
  const lines = [`Ход ${moveNumber}: ${who} ${point !== null ? gtp : "пас"} — ${label}` + (loss >= 0.5 ? ` (потеря около ${pointsGen(loss)})` : "") + "."];
  const facts = tacticalFacts(boardBefore, color, point);
  if (facts.sentences.length) lines.push("Что делает ход: " + facts.sentences.join(" "));

  const bp = best ? fromGtp(best.move, size) : null;
  if (!isBest && loss >= 0.5 && after) {
    const boardAfter = boardBefore.copy();
    try { boardAfter.play(color, point); } catch { /* ignore */ }
    const reasons = [];
    if (before.ownership && after.ownership) reasons.push(...groupStatusChanges(boardAfter, color, before.ownership, after.ownership));
    const threat = after.moves[0] || null; // чем соперник ответит
    const tp = threat ? fromGtp(threat.move, size) : null;
    if (tp !== null) {
      const tf = tacticalFacts(boardAfter, other(color), tp);
      let t = `Теперь соперник может сыграть ${threat.move}`;
      if (tf.sentences.length && !tf.illegal) t += " — " + lowerFirst(tf.sentences.join(" "));
      else t += ` ${areaName(tp, size)} — это самое ценное место на доске сейчас.`;
      reasons.push(t.endsWith(".") ? t : t + ".");
    }
    if (bp !== null && point !== null && dist(bp, point, size) >= 4) reasons.push(`Ход сделан в стороне от главного: важнее всего было играть ${areaName(bp, size)}.`);
    if (bp !== null && tp !== null && dist(bp, tp, size) <= 2 && bp !== point) {
      reasons.push(`Лучший ход ${best.move} занимал этот важный район первым и не давал сопернику сыграть ${threat.move} с такой пользой.`);
    }
    if (before.ownership && after.ownership) {
      const [lost, where] = territoryShift(color, before.ownership, after.ownership, size);
      if (lost >= 1.5 && where) reasons.push(`По оценке ИИ, около ${pointsGen(lost)} ${where} переходит к сопернику.`);
    }
    if (reasons.length) lines.push("Почему это хуже: " + reasons.join(" "));
  }
  if (best && !isBest && loss >= 0.5) {
    const bf = tacticalFacts(boardBefore, color, bp);
    let t = `Лучше было ${best.move}.`;
    if (bf.sentences.length && !bf.illegal) t += " " + bf.sentences.join(" ");
    lines.push(t);
    if (best.pv && best.pv.length) lines.push("Ожидаемое продолжение: " + pvText(best.pv, color) + ".");
  } else if (isBest) {
    lines.push("ИИ считает этот ход лучшим в позиции.");
    if (best && best.pv.length > 1) lines.push("Ожидаемое продолжение: " + pvText(best.pv, color) + ".");
  }
  lines.push(`Шансы на победу (${who.toLowerCase()}): ${(wrBefore * 100).toFixed(0)}% → ${(wrAfter * 100).toFixed(0)}%.`);
  return { moveNumber, color, point, loss, wrBefore, wrAfter, bestMove: best ? best.move : null,
    bestPv: best ? best.pv : [], text: lines.join("\n"), label, mark };
}

// Объяснение без ИИ: только тактический разбор
export function offlineExplanation(boardBefore, color, point, moveNumber) {
  const who = color === BLACK ? "Чёрные" : "Белые";
  const facts = tacticalFacts(boardBefore, color, point);
  const head = `Ход ${moveNumber}: ${who} ${point !== null ? toGtp(point, boardBefore.size) : "пас"}.`;
  const body = facts.sentences.length ? facts.sentences.join(" ")
    : "Явных тактических последствий нет: ход строит позицию. Подробную оценку (сколько очков стоит ход и что было лучше) даёт ИИ KataGo.";
  const warn = ignoredAtari(boardBefore, color, point);
  return [head, body, warn].filter((x) => x).join("\n");
}

function ignoredAtari(board, color, point) {
  const after = board.copy();
  try { after.play(color, point); } catch { return ""; }
  for (const [st, lb] of after.groups(color)) {
    if (lb.size === 1 && st.size >= 2 && (point === null || !st.has(point))) return `Внимание: ${nom(after, st)} остаётся в атари — соперник может её снять.`;
  }
  return "";
}

export { IllegalMove };
