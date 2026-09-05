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
  strategies: [1, 2, 3, 4],
  min_score: 85,
  use_live_prices: false,
  limit: null,
};
