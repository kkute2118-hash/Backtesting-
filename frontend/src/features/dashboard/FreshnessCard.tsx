"use client";

import { CheckCircle2, CircleAlert, Clock } from "lucide-react";

import { Banner } from "@/components/ui/Misc";
import { errorMessage } from "@/lib/api";
import type { Freshness } from "@/types/api";
import { date } from "@/lib/format";

/**
 * Data freshness, given prominence on purpose.
 *
 * Scanning a stale candle store ranks yesterday's prices and produces late
 * entries. That was the single most consequential thing the old UI let you do
 * without noticing, so it is a banner here rather than a caption.
 */
export function FreshnessBanner({
  freshness,
  error,
  action,
}: {
  freshness?: Freshness;
  error?: unknown;
  action?: React.ReactNode;
}) {
  if (error) {
    return (
      <Banner tone="warn" title={
        <span className="flex items-center gap-1.5">
          <CircleAlert className="h-3.5 w-3.5" aria-hidden />
          Could not check data freshness
        </span>
      }>
        {errorMessage(error)}
      </Banner>
    );
  }
  if (!freshness) return null;

  if (freshness.severity === "ok") {
    return (
      <Banner tone="up" title={
        <span className="flex items-center gap-1.5">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          Data current
        </span>
      }>
        Stored candles are complete through {date(freshness.latest)} — the last
        completed session. {freshness.universe_size.toLocaleString("en-IN")} stocks checked.
      </Banner>
    );
  }

  if (freshness.severity === "unknown") {
    return (
      <Banner tone="warn" title={
        <span className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          Freshness unknown
        </span>
      }>
        {freshness.message}
      </Banner>
    );
  }

  return (
    <Banner
      tone="down"
      action={action}
      title={
        <span className="flex items-center gap-1.5">
          <CircleAlert className="h-3.5 w-3.5" aria-hidden />
          {freshness.latest ? "Stale data" : "No local data"}
        </span>
      }
    >
      {freshness.message}
    </Banner>
  );
}
