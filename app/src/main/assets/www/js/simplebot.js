// Простой встроенный бот на эвристиках. Используется, когда KataGo недоступен.
// Играет слабо (уровень новичка), но соблюдает правила и понимает базовую тактику.
import { EMPTY, other } from "./board.js";

export function makeRng(seed) {
  if (seed === null || seed === undefined) return Math.random;
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function line(p, size) {
  const x = p % size, y = Math.floor(p / size);
  return Math.min(x, y, size - 1 - x, size - 1 - y) + 1;
}

function region(board, p) {
  const reg = new Set([p]);
  const borders = new Set();
  const stack = [p];
  while (stack.length) {
    const q = stack.pop();
    for (const nb of board.neighbors(q)) {
      const c = board.get(nb);
      if (c === EMPTY) { if (!reg.has(nb)) { reg.add(nb); stack.push(nb); } }
      else borders.add(c);
    }
  }
  return [reg.size, borders];
}

export function evaluateMove(board, color, p, last, rng) {
  if (board.get(p) !== EMPTY) return null;
  if (board.isEyeLike(p, color)) return null; // свой глаз не заполняем
  const [regionSize, borders] = region(board, p);
  const size = board.size;
  if (borders.size === 1 && borders.has(color) && regionSize < Math.floor((size * size) / 3)) return null;
  const b = board.copy();
  let captured;
  try { captured = b.play(color, p); } catch { return null; }
  const opp = other(color);
  let score = rng() * 2.0;
  score += 12 * captured.length; // 1. захват
  for (const nb of board.neighbors(p)) { // 2. спасение своих групп из атари
    if (board.get(nb) === color) {
      const [stones, libs] = board.group(nb);
      if (libs.size === 1 && b.group(p)[1].size >= 2) score += 10 * stones.size;
    }
  }
  for (const nb of b.neighbors(p)) { // 3. атари и давление
    if (b.get(nb) === opp) {
      const [stones, libs] = b.group(nb);
      if (libs.size === 1) score += 4 + 2 * stones.size;
      else if (libs.size === 2) score += 1;
    }
  }
  const [st, lb] = b.group(p); // 4. не ставим атари сами себе
  if (lb.size === 1 && !captured.length) score -= 15 + 3 * st.size;
  else if (lb.size === 2) score -= 1;
  let moveNo = 0; // 5. дебют: 3-я и 4-я линии
  for (let q = 0; q < board.n; q++) if (board.get(q) !== EMPTY) moveNo++;
  const ln = line(p, size);
  if (moveNo < size * 1.5) score += ({ 1: -6, 2: -2, 3: 3, 4: 3 })[ln] ?? 1;
  else if (ln === 1) score -= 2;
  let nearOpp = 0, nearOwn = 0; // 6. рядом с камнями и последним ходом
  for (const q of board.neighbors(p)) { if (board.get(q) === opp) nearOpp++; else if (board.get(q) === color) nearOwn++; }
  score += 0.6 * nearOpp - 0.3 * Math.max(0, nearOwn - 1);
  if (last !== null && last !== undefined) {
    const d = Math.abs((last % size) - (p % size)) + Math.abs(Math.floor(last / size) - Math.floor(p / size));
    if (d <= 3) score += 1.5;
  }
  if (nearOpp >= 3 && !captured.length) score -= 4; // 7. не лезть в чужую территорию
  if (borders.size === 1 && borders.has(opp) && regionSize <= 6 && !captured.length) score -= 6;
  return score;
}

export function chooseMove(board, color, last = null, seed = null) {
  const rng = makeRng(seed);
  let best = null, bestScore = 0; // если ничего не лучше нуля — пас
  for (let p = 0; p < board.n; p++) {
    const s = evaluateMove(board, color, p, last, rng);
    if (s !== null && s > bestScore) { best = p; bestScore = s; }
  }
  return best;
}
