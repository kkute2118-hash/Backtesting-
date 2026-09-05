import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export type Tone = "neutral" | "accent" | "up" | "down" | "warn";

const TONES: Record<Tone, string> = {
  neutral: "bg-elevated text-muted border-line",
  accent: "bg-accent-soft text-accent border-accent/30",
  up: "bg-up-soft text-up border-up/30",
  down: "bg-down-soft text-down border-down/30",
  warn: "bg-warn-soft text-warn border-warn/30",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  icon,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  icon?: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5",
        "text-2xs font-medium uppercase tracking-wide whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/**
 * Map an engine verdict to a tone.
 *
 * The badge always carries its text as well as its colour: roughly one in
 * twelve men cannot separate the red from the green, and a stop-loss is not a
 * thing to communicate by hue alone.
 */
export function toneForSafety(status: string | null | undefined): Tone {
  switch ((status ?? "").toUpperCase()) {
    case "ELIGIBLE":
      return "up";
    case "CAUTION":
      return "warn";
    case "REJECT":
      return "down";
    default:
      return "neutral";
  }
}

export function toneForRegime(regime: string | null | undefined): Tone {
  const value = (regime ?? "").toUpperCase();
  if (value.includes("STRONG BULL")) return "up";
  if (value.includes("BULL")) return "up";
  if (value.includes("BEAR")) return "down";
  if (value.includes("RECOVERY") || value.includes("SIDEWAYS")) return "warn";
  return "neutral";
}

export function toneForScore(score: number | null | undefined): Tone {
  if (score === null || score === undefined) return "neutral";
  if (score >= 90) return "up";
  if (score >= 80) return "accent";
  if (score >= 70) return "warn";
  return "neutral";
}

export function toneForOutcome(outcome: string | null | undefined): Tone {
  const value = (outcome ?? "").toUpperCase();
  if (value === "WIN" || value === "TARGET") return "up";
  if (value === "LOSS" || value === "STOP") return "down";
  if (value === "TIMEOUT" || value === "EXPIRED") return "warn";
  return "neutral";
}
