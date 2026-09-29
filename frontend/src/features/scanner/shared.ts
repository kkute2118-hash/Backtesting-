import type { Row } from "@/types/api";

/** Typed reads from the engine's loosely-typed result rows. */
export function num(row: Row, key: string): number | null {
  const value = row[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function str(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

// All six scanner strategies (the engine's DEFAULT_STRATEGIES). S1-S3 came back
// on 29 Sep 2026 with S6's market gate: they only fire while market breadth is
// at least 0.50, the stock is 60%+ above its 52-week low and within 15% of its
// 52-week high (research/S123_IMPROVED.md).
export const STRATEGY_OPTIONS = [
  { value: 1, label: "S1 · Monthly trend", hint: "Monthly trend continuation; only while market breadth ≥ 0.50" },
  { value: 2, label: "S2 · EMA momentum", hint: "EMA momentum; only while market breadth ≥ 0.50" },
  { value: 3, label: "S3 · 50-EMA pullback", hint: "Pullback to the 50 EMA; only while market breadth ≥ 0.50" },
  { value: 4, label: "S4 · SEPA", hint: "Minervini-style stage analysis" },
  { value: 5, label: "S5 · Pocket pivot", hint: "O'Neil pocket pivot, volatility-filtered — no quality score" },
  { value: 6, label: "S6 · Breadth breakout", hint: "Fresh 50-day high while the market breaks out with it; 3×ATR stop, 20% trail" },
];

export interface ScanFormState {
  universes: string[];
  strategies: number[];
  min_score: number;
  use_live_prices: boolean;
  limit: number | null;
}

export const DEFAULT_SCAN: ScanFormState = {
  universes: ["Nifty 500"],
  // All six scanner strategies - see the engine's DEFAULT_STRATEGIES.
  strategies: [1, 2, 3, 4, 5, 6],
  // Kept so saved presets still load; the engine ignores it. Selection is the
  // entry evidence filter now, not the score.
  min_score: 0,
  use_live_prices: false,
  limit: null,
};
