/**
 * Indicator maths for the interactive chart. Pure functions over the bars the
 * chart already holds: every output is aligned to the input (one value per
 * bar, null while the indicator is still warming up), so a series can be fed
 * to the chart as-is and its last point updated on a live tick.
 */

export interface Bar {
  time: number;          // India wall-clock epoch seconds (see backend services/charting.py)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Series = (number | null)[];

export function sma(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = values.slice(0, period).reduce((a, b) => a + b, 0) / period;   // seeded with the SMA
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Wilder's RSI, as every charting terminal draws it. */
export function rsi(values: number[], period = 14): Series {
  const out: Series = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  gain /= period;
  loss /= period;
  out[period] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export function macd(values: number[], fast = 12, slow = 26, signal = 9) {
  const f = ema(values, fast);
  const s = ema(values, slow);
  const line: Series = values.map((_, i) => (f[i] !== null && s[i] !== null ? (f[i] as number) - (s[i] as number) : null));
  const start = line.findIndex((v) => v !== null);
  const sig: Series = new Array(values.length).fill(null);
  if (start >= 0) {
    const tail = ema(line.slice(start) as number[], signal);
    tail.forEach((v, i) => { sig[start + i] = v; });
  }
  const hist: Series = line.map((v, i) => (v !== null && sig[i] !== null ? v - (sig[i] as number) : null));
  return { line, signal: sig, hist };
}

export function bollinger(values: number[], period = 20, mult = 2) {
  const mid = sma(values, period);
  const upper: Series = new Array(values.length).fill(null);
  const lower: Series = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const m = mid[i] as number;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += (values[j] - m) ** 2;
    const sd = Math.sqrt(v / period);
    upper[i] = m + mult * sd;
    lower[i] = m - mult * sd;
  }
  return { mid, upper, lower };
}

/**
 * VWAP. Intraday: resets each session, as a trader reads it. On daily and
 * longer bars a session VWAP is just the typical price, so it is a rolling
 * `period`-bar volume-weighted average instead.
 */
export function vwap(bars: Bar[], intraday: boolean, period = 20): Series {
  const out: Series = new Array(bars.length).fill(null);
  if (intraday) {
    let pv = 0;
    let vol = 0;
    let day = -1;
    bars.forEach((b, i) => {
      const d = Math.floor(b.time / 86_400);
      if (d !== day) { day = d; pv = 0; vol = 0; }
      const tp = (b.high + b.low + b.close) / 3;
      pv += tp * b.volume;
      vol += b.volume;
      out[i] = vol > 0 ? pv / vol : tp;
    });
    return out;
  }
  for (let i = period - 1; i < bars.length; i++) {
    let pv = 0;
    let vol = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const b = bars[j];
      pv += ((b.high + b.low + b.close) / 3) * b.volume;
      vol += b.volume;
    }
    out[i] = vol > 0 ? pv / vol : null;
  }
  return out;
}

/** Supertrend with Wilder's ATR. `up` is true while the trend is up. */
export function supertrend(bars: Bar[], period = 10, mult = 3) {
  const n = bars.length;
  const line: Series = new Array(n).fill(null);
  const up: (boolean | null)[] = new Array(n).fill(null);
  if (n <= period) return { line, up };
  const tr = bars.map((b, i) => (i === 0 ? b.high - b.low
    : Math.max(b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close))));
  let atr = tr.slice(1, period + 1).reduce((a, b) => a + b, 0) / period;
  let finalUpper = 0;
  let finalLower = 0;
  let trendUp = true;
  for (let i = period; i < n; i++) {
    if (i > period) atr = (atr * (period - 1) + tr[i]) / period;
    const mid = (bars[i].high + bars[i].low) / 2;
    const basicUpper = mid + mult * atr;
    const basicLower = mid - mult * atr;
    const prevClose = bars[i - 1].close;
    finalUpper = i === period || basicUpper < finalUpper || prevClose > finalUpper ? basicUpper : finalUpper;
    finalLower = i === period || basicLower > finalLower || prevClose < finalLower ? basicLower : finalLower;
    if (trendUp && bars[i].close < finalLower) trendUp = false;
    else if (!trendUp && bars[i].close > finalUpper) trendUp = true;
    line[i] = trendUp ? finalLower : finalUpper;
    up[i] = trendUp;
  }
  return { line, up };
}

/**
 * Support and resistance: the most recent swing highs and lows (a bar whose
 * high/low is the extreme of `span` bars either side), merged when within
 * 0.5% of each other. Returns at most `count` levels nearest the last close.
 */
export function supportResistance(bars: Bar[], span = 5, count = 6) {
  const levels: { price: number; kind: "support" | "resistance" }[] = [];
  for (let i = span; i < bars.length - span; i++) {
    let hi = true;
    let lo = true;
    for (let j = i - span; j <= i + span; j++) {
      if (bars[j].high > bars[i].high) hi = false;
      if (bars[j].low < bars[i].low) lo = false;
    }
    if (hi) levels.push({ price: bars[i].high, kind: "resistance" });
    if (lo) levels.push({ price: bars[i].low, kind: "support" });
  }
  const last = bars.length ? bars[bars.length - 1].close : 0;
  const merged: typeof levels = [];
  for (const lvl of levels.reverse()) {                       // newest first
    if (!merged.some((m) => Math.abs(m.price - lvl.price) / lvl.price < 0.005)) merged.push(lvl);
  }
  return merged
    .map((l) => ({ ...l, kind: (l.price >= last ? "resistance" : "support") as "support" | "resistance" }))
    .sort((a, b) => Math.abs(a.price - last) - Math.abs(b.price - last))
    .slice(0, count);
}
