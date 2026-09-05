"use client";

import { Eye, Plus, ShieldCheck, TrendingUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { PriceChart } from "@/components/charts/PriceChart";
import { RsiChart } from "@/components/charts/RsiChart";
import { Badge, toneForRegime, toneForSafety } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Change, Note, ScoreBar, Stat } from "@/components/ui/Misc";
import { EmptyState, ErrorState, Skeleton, SkeletonCards } from "@/components/ui/States";
import {
  useAddToWatchlist, useConditions, useConfig, useHistory, useIndicators, useQuote,
  useSafety, useStockSignals, useWatchlists,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { compact, date, inr, inrCompact, int, num, relativeTime, signed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Row } from "@/types/api";

import { ConditionMatrix } from "./ConditionMatrix";
import { IndicatorPanel } from "./IndicatorPanel";
import { FundamentalsCard, StockDnaCard } from "./StockExtras";

const TIMEFRAMES = ["3M", "6M", "1Y", "2Y", "5Y", "MAX"] as const;
const OVERLAY_OPTIONS = ["ema20", "ema50", "ema200"] as const;

function n(row: Row, key: string): number | null {
  const value = row[key];
  return typeof value === "number" ? value : null;
}
function s(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

export function StockPage({ symbol }: { symbol: string }) {
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("1Y");
  const [overlays, setOverlays] = useState<string[]>(["ema20", "ema50", "ema200"]);

  const quote = useQuote(symbol);
  const history = useHistory(symbol, timeframe);
  const indicators = useIndicators(symbol);
  const conditions = useConditions(symbol);
  const signals = useStockSignals(symbol);
  const safety = useSafety(symbol);
  const config = useConfig();

  if (quote.isLoading) {
    return (
      <Page>
        <Skeleton className="h-16 w-full" />
        <SkeletonCards />
        <Skeleton className="h-96 w-full rounded-card" />
      </Page>
    );
  }

  if (quote.error || !quote.data) {
    return (
      <Page>
        <PageHeader title={symbol} />
        <ErrorState error={quote.error} onRetry={() => quote.refetch()} />
      </Page>
    );
  }

  const q = quote.data;
  const isLive = q.price_source !== "STORED CLOSE";

  return (
    <Page>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
              {q.symbol}
            </h1>
            <Badge tone="neutral">{q.exchange} · {q.segment}</Badge>
            <Badge tone={q.market_open ? "up" : "neutral"}>
              {q.market_open ? "Session open" : "Session closed"}
            </Badge>
          </div>
          {q.name ? <p className="mt-0.5 truncate text-xs text-muted">{q.name}</p> : null}

          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <span className="tabular text-3xl font-semibold leading-none text-ink">
              {inr(q.price)}
            </span>
            <Change value={q.change_pct} className="text-sm" />
            <span className="tabular text-sm text-muted">{signed(q.change)}</span>
          </div>

          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-faint">
            <span className={cn("flex items-center gap-1", isLive && "text-accent")}>
              <span className={cn("h-1.5 w-1.5 rounded-full",
                isLive ? "bg-accent animate-pulse" : "bg-faint")} aria-hidden />
              {q.price_source.replace("_", " ").toLowerCase()}
            </span>
            <span>as of {date(q.price_as_of, isLive)}</span>
            <span>{int(q.bars_stored)} bars stored</span>
          </p>
        </div>

        <AddToWatchlist symbol={q.symbol} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Open" value={inr(q.open)} />
        <Stat label="Day high" value={inr(q.high)} />
        <Stat label="Day low" value={inr(q.low)} />
        <Stat label="Volume" value={compact(q.volume)} />
        <Stat
          label="Safety"
          value={safety.data ? String(safety.data.score) : "—"}
          sub={safety.data?.status ?? "Assessing liquidity and volatility"}
          tone={
            safety.data?.status === "ELIGIBLE" ? "up"
            : safety.data?.status === "REJECT" ? "down"
            : safety.data?.status === "CAUTION" ? "warn" : undefined
          }
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
        />
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title="Price"
          description="Daily candles from the local store, with the exact moving averages the
            strategies use."
          action={
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-0.5" role="group"
                aria-label="Moving average overlays">
                {OVERLAY_OPTIONS.map((key) => {
                  const active = overlays.includes(key);
                  return (
                    <button
                      key={key}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setOverlays((current) =>
                          active ? current.filter((entry) => entry !== key) : [...current, key])
                      }
                      className={cn(
                        "rounded px-1.5 py-0.5 text-2xs font-medium transition-colors",
                        active ? "bg-accent-soft text-accent" : "text-faint hover:text-ink",
                      )}
                    >
                      {key.toUpperCase()}
                    </button>
                  );
                })}
              </div>
              <div className="flex items-center gap-0.5 rounded-md border border-line bg-elevated
                p-0.5" role="group" aria-label="Chart timeframe">
                {TIMEFRAMES.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={timeframe === option}
                    onClick={() => setTimeframe(option)}
                    className={cn(
                      "rounded px-2 py-0.5 text-2xs font-medium transition-colors",
                      timeframe === option
                        ? "bg-surface text-ink shadow-sm"
                        : "text-faint hover:text-ink",
                    )}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
          }
        />
        {history.isLoading ? (
          <Skeleton className="m-4 h-96" />
        ) : history.error ? (
          <ErrorState error={history.error} onRetry={() => history.refetch()} compact />
        ) : history.data ? (
          <>
            <PriceChart history={history.data} overlays={overlays} />
            {history.data.overlays.rsi14 ? (
              <div className="border-t border-line px-2 pb-2 pt-1">
                <p className="px-2 pb-1 text-2xs font-medium uppercase tracking-wide text-faint">
                  RSI(14)
                </p>
                <RsiChart data={history.data.overlays.rsi14} />
              </div>
            ) : null}
          </>
        ) : null}
      </Card>

      {indicators.isLoading ? (
        <SkeletonCards />
      ) : indicators.error ? (
        <ErrorState error={indicators.error} compact />
      ) : indicators.data ? (
        <IndicatorPanel indicators={indicators.data} />
      ) : null}

      {conditions.isLoading ? (
        <Skeleton className="h-64 w-full rounded-card" />
      ) : conditions.error ? (
        <ErrorState error={conditions.error} compact />
      ) : conditions.data ? (
        <ConditionMatrix strategies={conditions.data.strategies} />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Scanner history"
            description="Every time this stock passed a full strategy rule set."
            icon={<TrendingUp className="h-3.5 w-3.5 text-accent" />}
          />
          {(signals.data?.signals ?? []).length === 0 ? (
            <EmptyState
              title="Never qualified"
              message="This stock has not passed every rule of any strategy in the recorded
                history. That is the normal case."
            />
          ) : (
            <div className="max-h-80 overflow-auto scroll-thin">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Date</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Strategy</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Score</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Entry</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Regime</th>
                  </tr>
                </thead>
                <tbody>
                  {(signals.data?.signals ?? []).map((row, index) => (
                    <tr key={index} className="border-b border-line/60 last:border-0">
                      <td className="px-4 py-1.5">{date(s(row, "signal_date"))}</td>
                      <td className="px-4 py-1.5">
                        <Badge tone="accent">{s(row, "strategy")}</Badge>
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <ScoreBar score={n(row, "score")} />
                      </td>
                      <td className="tabular px-4 py-1.5 text-right">{inr(n(row, "entry"))}</td>
                      <td className="px-4 py-1.5">
                        <Badge tone={toneForRegime(s(row, "regime"))}>
                          {s(row, "regime") || "—"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Risk assessment"
            description="Liquidity, volatility, gaps and circuit-like behaviour."
            icon={<ShieldCheck className="h-3.5 w-3.5 text-accent" />}
          />
          {safety.isLoading ? (
            <Skeleton className="m-4 h-40" />
          ) : safety.error ? (
            <ErrorState error={safety.error} compact />
          ) : safety.data ? (
            <CardBody className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="tabular text-2xl font-semibold text-ink">
                  {safety.data.score}
                </span>
                <Badge tone={toneForSafety(safety.data.status)}>{safety.data.status}</Badge>
                <span className="ml-auto text-2xs text-faint">
                  20d traded value {inrCompact(safety.data.metrics.avg_traded_value_20d)}
                </span>
              </div>

              {safety.data.flags.length === 0 ? (
                <p className="text-xs text-up">No risk flags raised.</p>
              ) : (
                <ul className="space-y-1">
                  {safety.data.flags.map((flag) => (
                    <li key={flag}
                      className="flex items-start gap-2 rounded-md border border-warn/25
                        bg-warn-soft/30 px-2.5 py-1.5 text-xs text-ink">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-warn" aria-hidden />
                      {flag}
                    </li>
                  ))}
                </ul>
              )}

              {!safety.data.news.available ? (
                <Note>
                  News and fundamental risk need Twelve Data. Without it this score reflects price
                  and volume behaviour only.
                </Note>
              ) : null}
            </CardBody>
          ) : null}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <StockDnaCard symbol={symbol} />
        <FundamentalsCard symbol={symbol}
          available={config.data?.providers.twelvedata.configured ?? false} />
      </div>

      {(signals.data?.forward_tests ?? []).length > 0 ? (
        <Card>
          <CardHeader title="Forward tests on this stock"
            description="Recorded signals and how they resolved." />
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                  <th scope="col" className="px-4 py-2 text-left font-semibold">Signal date</th>
                  <th scope="col" className="px-4 py-2 text-left font-semibold">Strategy</th>
                  <th scope="col" className="px-4 py-2 text-left font-semibold">Status</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Entry</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Stop</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Target</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">R</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody>
                {(signals.data?.forward_tests ?? []).map((row, index) => (
                  <tr key={index} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-1.5">{date(s(row, "signal_date"))}</td>
                    <td className="px-4 py-1.5">{s(row, "strategy")}</td>
                    <td className="px-4 py-1.5">
                      <Badge tone={
                        s(row, "status") === "TARGET" ? "up"
                        : s(row, "status") === "STOP" ? "down"
                        : s(row, "status") === "ACTIVE" ? "accent" : "warn"
                      }>
                        {s(row, "status")}
                      </Badge>
                    </td>
                    <td className="tabular px-4 py-1.5 text-right">{inr(n(row, "entry"))}</td>
                    <td className="tabular px-4 py-1.5 text-right">{inr(n(row, "sl"))}</td>
                    <td className="tabular px-4 py-1.5 text-right">{inr(n(row, "target"))}</td>
                    <td className={cn("tabular px-4 py-1.5 text-right font-medium",
                      (n(row, "result_r") ?? 0) > 0 ? "text-up"
                        : (n(row, "result_r") ?? 0) < 0 ? "text-down" : "")}>
                      {n(row, "result_r") === null ? "—" : num(n(row, "result_r"), 2)}
                    </td>
                    <td className="px-4 py-1.5 text-right text-faint">
                      {relativeTime(s(row, "updated_at"))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </Page>
  );
}

function AddToWatchlist({ symbol }: { symbol: string }) {
  const { data: watchlists } = useWatchlists(false);
  const addToWatchlist = useAddToWatchlist();
  const [open, setOpen] = useState(false);

  const lists = watchlists ?? [];
  const containing = lists.filter((list) =>
    list.items.some((item) => item.symbol === symbol));

  async function add(id: number, name: string) {
    try {
      await addToWatchlist.mutateAsync({ id, symbols: [symbol] });
      toast.success(`${symbol} added to ${name}`);
      setOpen(false);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  if (lists.length === 0) {
    return (
      <a
        href="/watchlist"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-elevated
          px-3 text-xs font-medium text-ink hover:border-strongline"
      >
        <Eye className="h-3.5 w-3.5" aria-hidden />
        Create a watchlist
      </a>
    );
  }

  return (
    <div className="relative">
      <Button size="sm" onClick={() => setOpen((current) => !current)}
        aria-expanded={open} aria-haspopup="true">
        <Plus className="h-3.5 w-3.5" aria-hidden />
        {containing.length > 0 ? `In ${containing.length} watchlist` : "Add to watchlist"}
      </Button>
      {open ? (
        <div className="absolute right-0 top-9 z-30 w-56 rounded-md border border-line bg-surface
          p-1 shadow-pop animate-fade-in">
          {lists.map((list) => {
            const has = list.items.some((item) => item.symbol === symbol);
            return (
              <button
                key={list.id}
                type="button"
                disabled={has}
                onClick={() => add(list.id, list.name)}
                className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5
                  text-left text-xs text-muted hover:bg-elevated hover:text-ink
                  disabled:opacity-50"
              >
                <span className="truncate">{list.name}</span>
                {has ? <span className="text-2xs text-up">Added</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
