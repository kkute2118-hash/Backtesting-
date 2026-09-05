/**
 * Number formatting for a dense financial table.
 *
 * Two rules run through all of it. A missing value renders as an em dash, never
 * as 0 — the difference between "no data" and "zero" matters when the number is
 * a stop-loss. And every figure is compact enough to scan a column vertically:
 * ₹1.24Cr, not ₹12,400,000.
 */

const EM_DASH = "—";

type Nullable = number | null | undefined;

function isMissing(value: Nullable): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value);
}

export function num(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function int(value: Nullable): string {
  if (isMissing(value)) return EM_DASH;
  return Math.round(value).toLocaleString("en-IN");
}

/** Indian price convention: two decimals, rupee symbol, grouped 2-2-3. */
export function inr(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  return `₹${num(value, digits)}`;
}

/** Compact rupees using Indian units, which is how the market quotes size. */
export function inrCompact(value: Nullable): string {
  if (isMissing(value)) return EM_DASH;
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${num(value / 1e7, 2)} Cr`;
  if (abs >= 1e5) return `₹${num(value / 1e5, 2)} L`;
  if (abs >= 1e3) return `₹${num(value / 1e3, 1)} K`;
  return `₹${num(value, 0)}`;
}

export function compact(value: Nullable): string {
  if (isMissing(value)) return EM_DASH;
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${num(value / 1e7, 2)}Cr`;
  if (abs >= 1e5) return `${num(value / 1e5, 2)}L`;
  if (abs >= 1e3) return `${num(value / 1e3, 1)}K`;
  return num(value, 0);
}

export function pct(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  return `${num(value, digits)}%`;
}

/** A change always carries its sign — "+1.20%" reads differently from "1.20%". */
export function signedPct(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  const sign = value > 0 ? "+" : "";
  return `${sign}${num(value, digits)}%`;
}

export function signed(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  const sign = value > 0 ? "+" : "";
  return `${sign}${num(value, digits)}`;
}

export function ratio(value: Nullable, digits = 2): string {
  if (isMissing(value)) return EM_DASH;
  return `${num(value, digits)}x`;
}

export function direction(value: Nullable): "up" | "down" | "flat" {
  if (isMissing(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

export function date(value: string | null | undefined, withTime = false): string {
  if (!value) return EM_DASH;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return EM_DASH;
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return value;
  const seconds = Math.round((Date.now() - parsed) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function duration(seconds: Nullable): string {
  if (isMissing(seconds)) return EM_DASH;
  if (seconds < 60) return `${num(seconds, 1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export const DASH = EM_DASH;
