"use client";

import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { compact, DASH, inr, num, pct, ratio } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Indicators } from "@/types/api";

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down" | "muted";
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="text-2xs text-muted">{label}</dt>
      <dd
        className={cn(
          "tabular text-xs font-medium",
          tone === "up" && "text-up",
          tone === "down" && "text-down",
          tone === "muted" && "text-faint",
          !tone && "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function toneForDistance(value: number | null | undefined) {
  if (value === null || value === undefined) return "muted" as const;
  return value >= 0 ? ("up" as const) : ("down" as const);
}

/**
 * Every indicator the engine actually computes, grouped by timeframe.
 *
 * Nothing here is derived in the browser: these are the exact values the
 * strategies were evaluated against, which is what makes the condition matrix
 * beside it verifiable by eye.
 */
export function IndicatorPanel({ indicators }: { indicators: Indicators }) {
  const { daily, weekly, monthly, range } = indicators;
  const compression = indicators.compression as Record<string, number | null | undefined>;

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card>
        <CardHeader title="Daily" />
        <CardBody className="pt-2">
          <dl className="divide-y divide-line/60">
            <Row label="Close" value={inr(daily.close)} />
            <Row label="RSI(14)" value={num(daily.rsi14, 1)}
              tone={daily.rsi14 !== null && daily.rsi14 !== undefined
                ? (daily.rsi14 >= 50 ? "up" : "down") : "muted"} />
            <Row label="ATR(14)" value={num(daily.atr14, 2)} />
            <Row label="Relative volume" value={ratio(daily.relvol)}
              tone={daily.relvol !== null && daily.relvol !== undefined && daily.relvol >= 1.5
                ? "up" : undefined} />
            <Row label="Avg volume (20d)" value={compact(daily.vol20)} />
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Moving averages" />
        <CardBody className="pt-2">
          <dl className="divide-y divide-line/60">
            <Row label="EMA 20" value={num(daily.ema20, 2)} />
            <Row label="EMA 50" value={num(daily.ema50, 2)} />
            <Row label="EMA 200" value={num(daily.ema200, 2)} />
            <Row label="vs EMA 20" value={pct(daily.dist_ema20_pct)}
              tone={toneForDistance(daily.dist_ema20_pct)} />
            <Row label="vs EMA 50" value={pct(daily.dist_ema50_pct)}
              tone={toneForDistance(daily.dist_ema50_pct)} />
            <Row label="vs EMA 200" value={pct(daily.dist_ema200_pct)}
              tone={toneForDistance(daily.dist_ema200_pct)} />
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Weekly & monthly" description="Higher-timeframe state." />
        <CardBody className="pt-2">
          <dl className="divide-y divide-line/60">
            <Row label="Weekly RSI" value={num(weekly.rsi14, 1)}
              tone={weekly.rsi14 !== null && weekly.rsi14 !== undefined
                ? (weekly.rsi14 >= 50 ? "up" : "down") : "muted"} />
            <Row label="Weekly EMA 20" value={num(weekly.ema20, 2)} />
            <Row label="Monthly RSI" value={num(monthly.rsi14, 1)}
              tone={monthly.rsi14 !== null && monthly.rsi14 !== undefined
                ? (monthly.rsi14 >= 50 ? "up" : "down") : "muted"} />
            <Row label="Monthly momentum" value={pct(monthly.momentum_pct)}
              tone={toneForDistance(monthly.momentum_pct)} />
            <Row label="Monthly EMA 10 / 20"
              value={
                monthly.ema10 === null || monthly.ema20 === null
                  ? DASH
                  : `${num(monthly.ema10, 1)} / ${num(monthly.ema20, 1)}`
              } />
            <Row label="Bull crosses (20m)" value={num(monthly.bull_crosses_20m, 0)} />
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Range & compression"
          description="Expansion tends to follow contraction." />
        <CardBody className="pt-2">
          <dl className="divide-y divide-line/60">
            <Row label="52-week high" value={inr(range.high_52w)} />
            <Row label="52-week low" value={inr(range.low_52w)} />
            <Row label="From 52w high" value={pct(range.pct_from_52w_high)}
              tone={toneForDistance(range.pct_from_52w_high)} />
            {typeof compression.range_percentile === "number" ? (
              <Row label="Range percentile (120d)"
                value={pct(compression.range_percentile, 0)}
                tone={compression.range_percentile <= 25 ? "up" : undefined} />
            ) : null}
            {typeof compression.inside_bars === "number" ? (
              <Row label="Consecutive inside bars" value={num(compression.inside_bars, 0)} />
            ) : null}
            {typeof compression.nr7 === "number" ? (
              <Row label="NR7" value={compression.nr7 ? "Yes" : "No"} />
            ) : null}
          </dl>
        </CardBody>
      </Card>
    </div>
  );
}
