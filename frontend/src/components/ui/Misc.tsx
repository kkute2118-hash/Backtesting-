"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { direction, signedPct } from "@/lib/format";

/** A single headline figure. Label above, value large, context below. */
export function Stat({
  label,
  value,
  sub,
  tone,
  icon,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "up" | "down" | "warn" | "accent";
  icon?: ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "up" ? "text-up"
    : tone === "down" ? "text-down"
    : tone === "warn" ? "text-warn"
    : tone === "accent" ? "text-accent"
    : "text-ink";
  return (
    <div className={cn("rounded-card border border-line bg-surface p-3.5 shadow-card", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-2xs font-medium uppercase tracking-wide text-faint">{label}</p>
        {icon ? <span className="text-faint" aria-hidden>{icon}</span> : null}
      </div>
      <p className={cn("tabular mt-1.5 text-xl font-semibold leading-none", toneClass)}>{value}</p>
      {sub ? <p className="mt-1.5 text-2xs leading-relaxed text-muted">{sub}</p> : null}
    </div>
  );
}

/** A percentage change, coloured and signed, with an arrow glyph for contrast. */
export function Change({
  value,
  className,
  showArrow = true,
}: {
  value: number | null | undefined;
  className?: string;
  showArrow?: boolean;
}) {
  const dir = direction(value);
  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-0.5 font-medium",
        dir === "up" && "text-up",
        dir === "down" && "text-down",
        dir === "flat" && "text-muted",
        className,
      )}
    >
      {showArrow && dir !== "flat" ? (
        <span aria-hidden>{dir === "up" ? "▲" : "▼"}</span>
      ) : null}
      {signedPct(value)}
    </span>
  );
}

/** A 0-100 quality score: the number, plus a bar so a column scans at a glance. */
export function ScoreBar({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return <span className="text-faint">—</span>;
  const clamped = Math.max(0, Math.min(100, score));
  const tone =
    clamped >= 90 ? "bg-up" : clamped >= 80 ? "bg-accent" : clamped >= 70 ? "bg-warn" : "bg-faint";
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="tabular font-semibold">{clamped.toFixed(0)}</span>
      <span className="h-1 w-10 overflow-hidden rounded-full bg-elevated" aria-hidden>
        <span className={cn("block h-full rounded-full", tone)}
          style={{ width: `${clamped}%` }} />
      </span>
    </span>
  );
}

export function SymbolLink({ symbol, className }: { symbol: string; className?: string }) {
  return (
    <Link
      href={`/stocks/${encodeURIComponent(symbol)}`}
      onClick={(event) => event.stopPropagation()}
      className={cn("font-semibold text-ink hover:text-accent hover:underline", className)}
    >
      {symbol}
    </Link>
  );
}

/**
 * A short, honest note about what a number means.
 *
 * Used a lot in this product: a score is a ranking, not a probability, and
 * saying so beside the number is better than saying it once in a footnote.
 */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("flex items-start gap-1.5 text-2xs leading-relaxed text-faint", className)}>
      <Info className="mt-px h-3 w-3 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

export function Banner({
  tone = "accent",
  title,
  children,
  action,
}: {
  tone?: "accent" | "up" | "down" | "warn";
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    accent: "border-accent/30 bg-accent-soft/50 text-ink",
    up: "border-up/30 bg-up-soft/50 text-ink",
    down: "border-down/40 bg-down-soft/50 text-ink",
    warn: "border-warn/40 bg-warn-soft/50 text-ink",
  } as const;
  const dot = {
    accent: "bg-accent", up: "bg-up", down: "bg-down", warn: "bg-warn",
  } as const;
  return (
    <div
      role={tone === "down" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-card border px-3.5 py-2.5", tones[tone])}
    >
      <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", dot[tone])} aria-hidden />
      <div className="min-w-0 flex-1 text-xs leading-relaxed">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={cn(title && "mt-0.5", "text-muted")}>{children}</div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold tracking-tight text-ink">{children}</h2>
      {action}
    </div>
  );
}
