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

export const STRATEGY_OPTIONS = [
  { value: 1, label: "S1 · Monthly base", hint: "Monthly base continuation" },
  { value: 2, label: "S2 · Tight pullback", hint: "Tight pullback in an uptrend" },
  { value: 3, label: "S3 · EMA50 pullback", hint: "Liquid pullback to EMA50" },
  { value: 4, label: "S4 · SEPA", hint: "Minervini-style stage analysis" },
  { value: 5, label: "S5 · Pocket pivot", hint: "O'Neil pocket pivot, volatility-filtered — no quality score" },
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
  // S4 + S5 is the measured best portfolio - see the engine's
  // DEFAULT_STRATEGIES and research/SECTOR_TIMING_FINDINGS.md addendum 4.
  // The other three stay selectable.
  strategies: [4, 5],
  // Kept so saved presets still load; the engine ignores it. Selection is the
  // entry evidence filter now, not the score.
  min_score: 0,
  use_live_prices: false,
  limit: null,
};
