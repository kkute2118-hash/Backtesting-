"use client";

import { Activity, RefreshCw, Radio, Wallet } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Page, PageHeader } from "@/components/layout/PageShell";
import { Badge, toneForOutcome } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Toggle } from "@/components/ui/Inputs";
import { Change, Note, ScoreBar, Stat, SymbolLink } from "@/components/ui/Misc";
import { EmptyState, ErrorState, SkeletonCards, SkeletonTable } from "@/components/ui/States";
import {
  useConfig, useForwardPositions, useForwardResults, useForwardSummary, useLiveForward,
  useRefreshForward, useScannerSignals, useStartLiveFeed, useStopLiveFeed,
} from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { date, inr, int, num, pct, relativeTime, signed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Row } from "@/types/api";

function n(row: Row, key: string): number | null {
  const value = row[key];
  return typeof value === "number" ? value : null;
}
function s(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

type Tab = "open" | "closed" | "signals" | "live";

export function ForwardPage() {
  const [tab, setTab] = useState<Tab>("open");
  const [useLive, setUseLive] = useState(true);

  const positions = useForwardPositions(useLive);
  const summary = useForwardSummary();
  const results = useForwardResults();
  const signals = useScannerSignals();
  const refresh = useRefreshForward();

  const totals = summary.data?.totals;
  const meta = positions.data?.meta;

  async function resolve() {
    try {
      const outcome = await refresh.mutateAsync();
      toast.success(
        `${outcome.checked} position${outcome.checked === 1 ? "" : "s"} checked, ` +
        `${outcome.closed} resolved.`,
      );
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  // forward_positions_view() returns display-cased columns ("Ticker", "Status",
  // "Gain/Loss %"), not the raw SQL names — these keys must match it exactly or
  // the table silently renders an empty book.
  const openRows = (positions.data?.rows ?? []).filter((row) => s(row, "Status") === "ACTIVE");

  const openColumns: Column<Row>[] = [
    { key: "Ticker", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={s(row, "Ticker")} />,
      value: (row) => s(row, "Ticker") },
    { key: "Strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{s(row, "Strategy")}</Badge>,
      value: (row) => s(row, "Strategy") },
    { key: "Alert", header: "Alert", sortable: false,
      render: (row) => <span className="text-2xs">{s(row, "Alert") || "—"}</span>,
      value: (row) => s(row, "Alert"),
      description: "Raised when a live price touches a level. Resolution still happens only " +
        "on a completed daily candle." },
    { key: "Signal Date", header: "Signal date", render: (row) => date(s(row, "Signal Date")),
      value: (row) => s(row, "Signal Date") },
    { key: "Score", header: "Score", align: "right",
      render: (row) => <ScoreBar score={n(row, "Score")} />, value: (row) => n(row, "Score") },
    { key: "Entry", header: "Entry", align: "right", render: (row) => inr(n(row, "Entry")),
      value: (row) => n(row, "Entry") },
    { key: "Current Price", header: "Current", align: "right",
      render: (row) => inr(n(row, "Current Price")), value: (row) => n(row, "Current Price") },
    { key: "Gain/Loss %", header: "P/L %", align: "right",
      render: (row) => <Change value={n(row, "Gain/Loss %")} />,
      value: (row) => n(row, "Gain/Loss %") },
    { key: "Gain/Loss ₹", header: "P/L ₹", align: "right", optional: true,
      render: (row) => inr(n(row, "Gain/Loss ₹")), value: (row) => n(row, "Gain/Loss ₹") },
    { key: "Unrealized R", header: "Unrealised R", align: "right",
      render: (row) => {
        const value = n(row, "Unrealized R");
        return (
          <span className={cn(value !== null && value > 0 && "text-up",
            value !== null && value < 0 && "text-down")}>
            {value === null ? "—" : num(value, 2)}
          </span>
        );
      },
      value: (row) => n(row, "Unrealized R"),
      description: "Move against this position's own risk (entry − stop)." },
    { key: "Stop", header: "Stop", align: "right",
      render: (row) => <span className="text-down">{inr(n(row, "Stop"))}</span>,
      value: (row) => n(row, "Stop") },
    { key: "Target", header: "Target", align: "right",
      render: (row) => <span className="text-up">{inr(n(row, "Target"))}</span>,
      value: (row) => n(row, "Target") },
    { key: "To Target %", header: "To target", align: "right", optional: true,
      render: (row) => pct(n(row, "To Target %"), 1), value: (row) => n(row, "To Target %") },
    { key: "To Stop %", header: "To stop", align: "right", optional: true,
      render: (row) => pct(n(row, "To Stop %"), 1), value: (row) => n(row, "To Stop %") },
    { key: "Progress to Target %", header: "Progress", align: "right",
      render: (row) => {
        const value = n(row, "Progress to Target %");
        if (value === null) return <span className="text-faint">—</span>;
        return (
          <span className="inline-flex items-center justify-end gap-2">
            <span className="tabular">{num(value, 0)}%</span>
            <span className="h-1 w-10 overflow-hidden rounded-full bg-elevated" aria-hidden>
              <span className="block h-full rounded-full bg-accent"
                style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
            </span>
          </span>
        );
      },
      value: (row) => n(row, "Progress to Target %") },
    { key: "MFE %", header: "MFE", align: "right", optional: true,
      render: (row) => pct(n(row, "MFE %"), 1), value: (row) => n(row, "MFE %") },
    { key: "MAE %", header: "MAE", align: "right", optional: true,
      render: (row) => pct(n(row, "MAE %"), 1), value: (row) => n(row, "MAE %") },
    { key: "Days Held", header: "Days held", align: "right", optional: true,
      render: (row) => int(n(row, "Days Held")), value: (row) => n(row, "Days Held") },
    { key: "Regime", header: "Regime", optional: true,
      render: (row) => <span className="text-2xs">{s(row, "Regime") || "—"}</span>,
      value: (row) => s(row, "Regime") },
    { key: "Price Source", header: "Price source", optional: true,
      render: (row) => (
        <span className="text-2xs text-muted">{s(row, "Price Source") || "—"}</span>),
      value: (row) => s(row, "Price Source"),
      description: "Where the current price came from, so a stale price is never mistaken " +
        "for a live one." },
    { key: "Price As Of", header: "Price as of", optional: true,
      render: (row) => (
        <span className="text-2xs text-faint">{relativeTime(s(row, "Price As Of"))}</span>),
      value: (row) => s(row, "Price As Of") },
  ];

  const closedColumns: Column<Row>[] = [
    { key: "symbol", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={s(row, "symbol")} />,
      value: (row) => s(row, "symbol") },
    { key: "strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{s(row, "strategy")}</Badge>,
      value: (row) => s(row, "strategy") },
    { key: "outcome", header: "Outcome",
      render: (row) => (
        <Badge tone={toneForOutcome(s(row, "outcome"))}>{s(row, "outcome") || "—"}</Badge>),
      value: (row) => s(row, "outcome") },
    { key: "signal_date", header: "Signal", render: (row) => date(s(row, "signal_date")),
      value: (row) => s(row, "signal_date") },
    { key: "closed_at", header: "Closed", render: (row) => date(s(row, "closed_at")),
      value: (row) => s(row, "closed_at") },
    { key: "entry", header: "Entry", align: "right", render: (row) => inr(n(row, "entry")),
      value: (row) => n(row, "entry") },
    { key: "exit_price", header: "Exit", align: "right",
      render: (row) => inr(n(row, "exit_price")), value: (row) => n(row, "exit_price") },
    { key: "return_pct", header: "Return", align: "right",
      render: (row) => <Change value={n(row, "return_pct")} />,
      value: (row) => n(row, "return_pct") },
    { key: "result_r", header: "R", align: "right",
      render: (row) => {
        const value = n(row, "result_r");
        return (
          <span className={cn("font-semibold", value !== null && value > 0 && "text-up",
            value !== null && value <= 0 && "text-down")}>
            {value === null ? "—" : signed(value, 2)}
          </span>
        );
      },
      value: (row) => n(row, "result_r") },
    { key: "holding_bars", header: "Bars held", align: "right",
      render: (row) => int(n(row, "holding_bars")), value: (row) => n(row, "holding_bars") },
    { key: "mfe_pct", header: "MFE %", align: "right", optional: true,
      render: (row) => pct(n(row, "mfe_pct"), 1), value: (row) => n(row, "mfe_pct") },
    { key: "mae_pct", header: "MAE %", align: "right", optional: true,
      render: (row) => pct(n(row, "mae_pct"), 1), value: (row) => n(row, "mae_pct") },
  ];

  const signalColumns: Column<Row>[] = [
    { key: "symbol", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={s(row, "symbol")} />,
      value: (row) => s(row, "symbol") },
    { key: "signal_date", header: "Date", render: (row) => date(s(row, "signal_date")),
      value: (row) => s(row, "signal_date") },
    { key: "strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{s(row, "strategy")}</Badge>,
      value: (row) => s(row, "strategy") },
    { key: "score", header: "Score", align: "right",
      render: (row) => <ScoreBar score={n(row, "score")} />, value: (row) => n(row, "score") },
    { key: "selected_for_forward", header: "At gate",
      render: (row) => n(row, "selected_for_forward")
        ? <Badge tone="up">Recorded</Badge>
        : <span className="text-2xs text-faint">Below gate</span>,
      value: (row) => n(row, "selected_for_forward") },
    { key: "entry", header: "Entry", align: "right", render: (row) => inr(n(row, "entry")),
      value: (row) => n(row, "entry") },
    { key: "regime", header: "Regime",
      render: (row) => <span className="text-2xs">{s(row, "regime") || "—"}</span>,
      value: (row) => s(row, "regime") },
    { key: "safety_status", header: "Safety",
      render: (row) => <span className="text-2xs">{s(row, "safety_status") || "—"}</span>,
      value: (row) => s(row, "safety_status") },
  ];

  return (
    <Page>
      <PageHeader
        title="Forward tests"
        description="Signals recorded at the gate and tracked from there. Target and stop
          resolution happens only on completed daily candles — a live price touching a level
          raises an alert here, it does not close the record."
        actions={
          <Button variant="primary" size="sm" loading={refresh.isPending} onClick={resolve}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Resolve positions
          </Button>
        }
      />

      {summary.isLoading ? (
        <SkeletonCards />
      ) : totals ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <Stat label="Open" value={int(totals.open)} icon={<Activity className="h-3.5 w-3.5" />} />
          <Stat label="Closed" value={int(totals.closed)}
            sub={`${totals.wins} won · ${totals.losses} lost`} />
          <Stat label="Win rate"
            value={totals.win_rate === null ? "—" : `${num(totals.win_rate, 1)}%`}
            tone={totals.win_rate === null ? undefined : totals.win_rate >= 50 ? "up" : "down"}
            sub={totals.wins + totals.losses === 0 ? "Nothing has resolved yet" : undefined} />
          <Stat label="Average R" value={signed(totals.avg_r, 3)}
            tone={(totals.avg_r ?? 0) > 0 ? "up" : (totals.avg_r ?? 0) < 0 ? "down" : undefined} />
          <Stat label="Total R" value={signed(totals.total_r)}
            icon={<Wallet className="h-3.5 w-3.5" />}
            tone={(totals.total_r ?? 0) > 0 ? "up"
              : (totals.total_r ?? 0) < 0 ? "down" : undefined} />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-0.5 rounded-md border border-line bg-elevated p-0.5"
          role="tablist" aria-label="Forward test views">
          {([
            ["open", `Open (${openRows.length})`],
            ["closed", `Closed (${(results.data?.rows ?? []).length})`],
            ["signals", "Signal log"],
            ["live", "Live monitor"],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                tab === key ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "open" ? (
          <div className="flex items-center gap-4">
            {meta ? (
              <span className="flex items-center gap-1.5 text-2xs text-faint">
                <Radio className={cn("h-3 w-3", meta.live_symbols > 0 && "text-accent")}
                  aria-hidden />
                {meta.live_symbols > 0
                  ? `${meta.live_symbols} live price${meta.live_symbols === 1 ? "" : "s"}`
                  : `Prices from ${meta.source.toLowerCase()}`}
              </span>
            ) : null}
            <Toggle checked={useLive} onChange={setUseLive} label="Use live prices" />
          </div>
        ) : null}
      </div>

      <Card className="overflow-hidden">
        {tab === "open" ? (
          positions.isLoading ? (
            <SkeletonTable rows={5} cols={8} />
          ) : positions.error ? (
            <ErrorState error={positions.error} onRetry={() => positions.refetch()} />
          ) : (
            <>
              <DataTable
                rows={openRows}
                columns={openColumns}
                getRowId={(row) => s(row, "id") || `${s(row, "Ticker")}-${s(row, "Signal Date")}`}
                exportName="forward-open"
                emptyTitle="No open forward tests"
                emptyMessage="Send a qualifying setup from a scan result and it will be tracked
                  here from the day it was recorded."
              />
              <div className="border-t border-line px-3 py-2.5">
                <Note>
                  Unrealised R is the move divided by this position&apos;s own risk, so a 1R gain
                  means the trade has made back what it was risking. Price source and
                  &ldquo;price as of&rdquo; columns say exactly where each number came from.
                </Note>
              </div>
            </>
          )
        ) : tab === "closed" ? (
          results.isLoading ? (
            <SkeletonTable rows={5} cols={8} />
          ) : (
            <DataTable
              rows={results.data?.rows ?? []}
              columns={closedColumns}
              getRowId={(row) => `${s(row, "symbol")}-${s(row, "signal_date")}-${s(row, "strategy")}`}
              exportName="forward-closed"
              emptyTitle="Nothing has resolved yet"
              emptyMessage="A forward test closes when a completed daily candle reaches its stop
                or its target."
            />
          )
        ) : tab === "live" ? (
          <LiveMonitor />
        ) : signals.isLoading ? (
          <SkeletonTable rows={5} cols={7} />
        ) : (
          <DataTable
            rows={signals.data?.rows ?? []}
            columns={signalColumns}
            getRowId={(row) => s(row, "signal_key") || String(row.signal_id)}
            exportName="scanner-signals"
            emptyTitle="No signals recorded"
            emptyMessage="Every qualifying setup a scan produces is recorded here, whether or not
              it reached the forward-test gate."
          />
        )}
      </Card>

      {summary.data && (summary.data.rows ?? []).length > 0 ? (
        <Card>
          <CardHeader
            title="Strategy scorecard"
            description="Built from forward-test records only — the reality check on the
              backtests."
          />
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-2xs uppercase tracking-wide text-faint">
                  <th scope="col" className="px-4 py-2 text-left font-semibold">Strategy</th>
                  <th scope="col" className="px-4 py-2 text-left font-semibold">Status</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Records</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Open</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Closed</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Win %</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Avg R</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Total R</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Avg MFE</th>
                  <th scope="col" className="px-4 py-2 text-right font-semibold">Avg MAE</th>
                </tr>
              </thead>
              <tbody>
                {(summary.data.rows ?? []).map((row, index) => (
                  <tr key={index} className="border-b border-line/60 last:border-0">
                    <td className="px-4 py-2 font-medium">{s(row, "Strategy")}</td>
                    <td className="px-4 py-2">
                      <Badge tone={
                        s(row, "Status") === "STRONG" ? "up"
                        : s(row, "Status") === "WEAK" ? "down"
                        : s(row, "Status") === "BUILDING SAMPLE" ? "neutral" : "warn"
                      }>
                        {s(row, "Status")}
                      </Badge>
                    </td>
                    <td className="tabular px-4 py-2 text-right">{int(n(row, "Records"))}</td>
                    <td className="tabular px-4 py-2 text-right">{int(n(row, "Open"))}</td>
                    <td className="tabular px-4 py-2 text-right">{int(n(row, "Closed"))}</td>
                    <td className="tabular px-4 py-2 text-right">
                      {n(row, "Win %") === null ? "—" : `${num(n(row, "Win %"), 1)}%`}
                    </td>
                    <td className="tabular px-4 py-2 text-right">{signed(n(row, "AvgR"), 3)}</td>
                    <td className="tabular px-4 py-2 text-right">{signed(n(row, "TotalR"))}</td>
                    <td className="tabular px-4 py-2 text-right">{num(n(row, "AvgMFE"), 2)}</td>
                    <td className="tabular px-4 py-2 text-right">{num(n(row, "AvgMAE"), 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="border-t border-line px-4 py-2.5">
            <Note>
              &ldquo;Building sample&rdquo; means fewer than three trades have closed for that
              strategy. Read nothing into an average R until the sample is large enough to mean
              something.
            </Note>
          </div>
        </Card>
      ) : null}
    </Page>
  );
}


/**
 * The persistent Dhan WebSocket.
 *
 * It streams only the symbols with an open forward test rather than the whole
 * market — that is the entire point of the live layer: track the candidates,
 * re-rank them from ticks, and never rebuild two thousand histories a minute.
 */
function LiveMonitor() {
  const { data: config } = useConfig();
  const [streaming, setStreaming] = useState(false);
  const start = useStartLiveFeed();
  const stop = useStopLiveFeed();
  const live = useLiveForward(streaming);

  const configured = config?.providers.dhan.configured ?? false;

  const columns: Column<Row>[] = [
    { key: "symbol", header: "Symbol", sticky: true, width: "7.5rem",
      render: (row) => <SymbolLink symbol={s(row, "symbol")} />,
      value: (row) => s(row, "symbol") },
    { key: "strategy", header: "Strategy",
      render: (row) => <Badge tone="accent">{s(row, "strategy")}</Badge>,
      value: (row) => s(row, "strategy") },
    { key: "ltp", header: "Last tick", align: "right", render: (row) => inr(n(row, "ltp")),
      value: (row) => n(row, "ltp") },
    { key: "entry", header: "Entry", align: "right", render: (row) => inr(n(row, "entry")),
      value: (row) => n(row, "entry") },
    { key: "sl", header: "Stop", align: "right",
      render: (row) => <span className="text-down">{inr(n(row, "sl"))}</span>,
      value: (row) => n(row, "sl") },
    { key: "target", header: "Target", align: "right",
      render: (row) => <span className="text-up">{inr(n(row, "target"))}</span>,
      value: (row) => n(row, "target") },
    { key: "ts", header: "Tick time", align: "right",
      render: (row) => <span className="text-2xs text-faint">{relativeTime(s(row, "ts"))}</span>,
      value: (row) => s(row, "ts") },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line
        px-3 py-2.5">
        <p className="text-2xs leading-relaxed text-muted">
          {configured
            ? "Streams the open forward-test symbols from Dhan's live feed. A tick raises an " +
              "alert; it never closes a record — resolution happens on completed daily candles."
            : "Dhan is not configured, so there is no live feed to start."}
        </p>
        <div className="flex items-center gap-2">
          {streaming ? (
            <Button size="sm" variant="secondary" loading={stop.isPending}
              onClick={() => stop.mutate(undefined, {
                onSuccess: () => { setStreaming(false); toast.success("Live feed stopped"); },
                onError: (error) => toast.error(errorMessage(error)),
              })}>
              Stop feed
            </Button>
          ) : (
            <Button size="sm" variant="primary" disabled={!configured} loading={start.isPending}
              onClick={() => start.mutate([], {
                onSuccess: (result) => {
                  setStreaming(true);
                  toast.success(`Streaming ${result.count} symbol${result.count === 1 ? "" : "s"}`);
                },
                onError: (error) => toast.error(errorMessage(error)),
              })}>
              <Radio className="h-3.5 w-3.5" aria-hidden />
              Start feed
            </Button>
          )}
        </div>
      </div>

      <DataTable
        rows={live.data?.rows ?? []}
        columns={columns}
        getRowId={(row) => `${s(row, "symbol")}-${s(row, "strategy")}`}
        emptyTitle={streaming ? "Waiting for ticks" : "Feed not running"}
        emptyMessage={
          streaming
            ? "Connected. Ticks appear as the exchange publishes them; outside session hours " +
              "there are none."
            : "Start the feed to stream live prices for your open forward tests."
        }
      />
    </div>
  );
}
