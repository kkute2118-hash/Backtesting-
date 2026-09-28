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
