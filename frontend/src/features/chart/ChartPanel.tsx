"use client";

import {
  ArrowUpRight, ChevronDown, Maximize2, Minimize2, Minus, MousePointer2, MoveVertical,
  RotateCcw, Slash, Trash2, X, ZoomIn, ZoomOut,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/ui/States";
import { useDismiss } from "@/components/ui/Inputs";
import { useQuote } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { compact, inr, signed } from "@/lib/format";
import { cn } from "@/lib/utils";

import { INTRADAY, TIMEFRAMES, useCandles, useLiveQuote, type Timeframe } from "./data";
import {
  DEFAULT_INDICATORS, TradingChart,
  type DrawTool, type IndicatorConfig, type TradingChartHandle,
} from "./TradingChart";

const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw ? ({ ...fallback, ...JSON.parse(raw) } as T) : fallback;
    } catch { return fallback; }
  },
  set(key: string, value: unknown) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage off */ }
  },
};

const LIVE_LABEL: Record<string, string> = {
  live: "Live", connecting: "Connecting…", polling: "Live (polling)", closed: "Market closed", offline: "Offline",
};

/**
 * The chart terminal for one stock. Opened from any stock name in the app
 * (see ChartProvider); fills the screen on a phone, slides over from the right
 * on larger screens.
 */
export function ChartPanel({ symbol, onClose }: { symbol: string; onClose(): void }) {
  const [tf, setTf] = useState<Timeframe>(() => store.get<{ tf: Timeframe }>("chart-prefs", { tf: "1D" }).tf);
  const [indicators, setIndicators] = useState<IndicatorConfig>(() => {
    const saved = store.get<Partial<IndicatorConfig>>("chart-indicators", {});
    return Object.fromEntries(Object.entries(DEFAULT_INDICATORS).map(([k, v]) =>
      [k, { ...v, ...(saved as Record<string, object>)[k] }])) as unknown as IndicatorConfig;
  });
  const [tool, setTool] = useState<DrawTool>("cursor");
  const [levels, setLevels] = useState(false);
  const [full, setFull] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<TradingChartHandle>(null);
  const { resolvedTheme } = useTheme();

  const info = useQuote(symbol, false);                   // name and exchange; no Dhan call
  const live = useLiveQuote(symbol);
  const candles = useCandles(symbol, tf);
  const available = candles.meta?.timeframes;
  const q = live.quote;

  useEffect(() => store.set("chart-prefs", { tf }), [tf]);
  useEffect(() => store.set("chart-indicators", indicators), [indicators]);

  // A saved intraday choice on a server without the Dhan feed: fall back to daily.
  useEffect(() => {
    const err = candles.error;
    if (err instanceof ApiError && err.isNotConfigured && INTRADAY.has(tf)) setTf("1D");
  }, [candles.error, tf]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Browsers usually swallow Escape to leave full screen themselves; where
      // the page does see it, leave full screen first and close on the next.
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      else onClose();
    };
    const onFs = () => setFull(Boolean(document.fullscreenElement));
    document.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onFs);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFs);
    };
  }, [onClose]);

  async function toggleFullscreen() {
    const el = panelRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (el.requestFullscreen) await el.requestFullscreen();
      else setFull((v) => !v);
    } catch {
      setFull((v) => !v);                                  // e.g. iOS: fall back to the panel filling the screen
    }
  }

  const up = (q?.change ?? 0) >= 0;
  const name = info.data?.name && info.data.name !== symbol ? info.data.name : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true"
      aria-label={`${symbol} chart`}>
      <button className="absolute inset-0 hidden bg-black/50 lg:block" aria-label="Close chart" onClick={onClose} />
      <div ref={panelRef} data-testid="chart-panel"
        className={cn("relative flex h-dvh w-full flex-col bg-canvas shadow-pop animate-fade-in",
          full ? "lg:w-full" : "lg:w-[min(1280px,94vw)] lg:border-l lg:border-line")}>

        {/* ----------------------------------------------------------- header */}
        <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 border-b border-line px-3 py-2 sm:px-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h2 className="text-base font-semibold text-ink sm:text-lg" data-testid="chart-symbol">{symbol}</h2>
              <span className="text-2xs text-faint">{info.data?.exchange ?? "NSE"} · {info.data?.segment ?? "Cash"}</span>
              <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs",
                live.status === "live" ? "bg-up-soft text-up" : live.status === "offline" ? "bg-down-soft text-down" : "bg-elevated text-muted")}
                data-testid="chart-live-status">
                <span className={cn("h-1.5 w-1.5 rounded-full", live.status === "live" ? "animate-pulse bg-up" : "bg-faint")} />
                {LIVE_LABEL[live.status] ?? live.status}
              </span>
            </div>
            {name ? <p className="truncate text-2xs text-muted">{name}</p> : null}
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
              <span className="tabular text-2xl font-semibold text-ink" data-testid="chart-ltp">{q ? inr(q.ltp) : "—"}</span>
              <span className={cn("tabular text-sm font-medium", up ? "text-up" : "text-down")}>
                {q?.change !== null && q?.change !== undefined ? `${signed(q.change)} (${signed(q.change_pct)}%)` : ""}
              </span>
              {q && q.source !== "LIVE" ? <span className="text-2xs text-faint">close of {q.session}</span> : null}
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-x-5 gap-y-0.5 text-2xs sm:grid-cols-5">
            {[["Open", inr(q?.open)], ["High", inr(q?.high)], ["Low", inr(q?.low)],
              ["Prev close", inr(q?.prev_close)], ["Volume", compact(q?.volume)]].map(([k, v]) => (
              <div key={k} className="flex flex-col">
                <dt className="text-faint">{k}</dt>
                <dd className="tabular font-medium text-ink">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="absolute right-2 top-2 flex items-center gap-1 sm:static">
            <Link href={`/stocks/${encodeURIComponent(symbol)}`} onClick={onClose}
              className="hidden items-center gap-1 rounded-md px-2 py-1 text-2xs text-muted hover:bg-elevated hover:text-ink sm:inline-flex">
              Full details <ArrowUpRight className="h-3 w-3" />
            </Link>
            <IconBtn label="Close chart" onClick={onClose}><X className="h-4 w-4" /></IconBtn>
          </div>
        </header>

        {/* ---------------------------------------------------------- toolbar */}
        <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-2 py-1.5 sm:px-3" role="toolbar" aria-label="Chart tools">
          <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label="Timeframe">
            {TIMEFRAMES.map((k) => {
              const ok = !available || available.includes(k);
              return (
                <button key={k} type="button" disabled={!ok} onClick={() => setTf(k)}
                  title={ok ? `${k} candles` : "Intraday needs the Dhan feed on this server"}
                  aria-pressed={tf === k} data-testid={`tf-${k}`}
                  className={cn("h-7 rounded px-2 text-xs font-medium tabular",
                    tf === k ? "bg-accent text-white" : "text-muted hover:bg-elevated hover:text-ink",
                    !ok && "cursor-not-allowed opacity-40 hover:bg-transparent")}>
                  {k}
                </button>
              );
            })}
          </div>
          <Sep />
          <IndicatorMenu value={indicators} onChange={setIndicators} />
          <Sep />
          <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label="Drawing tools">
            {([["cursor", "Pointer", MousePointer2], ["hline", "Horizontal line", Minus],
              ["trend", "Trend line (two clicks)", Slash], ["vline", "Vertical line", MoveVertical]] as const).map(([k, label, Icon]) => (
              <IconBtn key={k} label={label} active={tool === k} onClick={() => setTool(k)} testId={`tool-${k}`}>
                <Icon className="h-4 w-4" />
              </IconBtn>
            ))}
            <button type="button" onClick={() => setLevels((v) => !v)} aria-pressed={levels}
              title="Support and resistance from recent swing highs and lows"
              className={cn("h-7 rounded px-2 text-xs font-medium", levels ? "bg-accent-soft text-accent" : "text-muted hover:bg-elevated hover:text-ink")}>
              S/R
            </button>
            <IconBtn label="Clear drawings" onClick={() => chartRef.current?.clearDrawings()}><Trash2 className="h-4 w-4" /></IconBtn>
          </div>
          <Sep />
          <div className="flex shrink-0 items-center gap-0.5">
            <IconBtn label="Zoom in" onClick={() => chartRef.current?.zoomIn()}><ZoomIn className="h-4 w-4" /></IconBtn>
            <IconBtn label="Zoom out" onClick={() => chartRef.current?.zoomOut()}><ZoomOut className="h-4 w-4" /></IconBtn>
            <IconBtn label="Reset chart" onClick={() => chartRef.current?.reset()}><RotateCcw className="h-4 w-4" /></IconBtn>
            <IconBtn label={full ? "Exit full screen" : "Full screen"} onClick={toggleFullscreen}>
              {full ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </IconBtn>
          </div>
        </div>

        {/* ------------------------------------------------------------ chart */}
        <div className="relative min-h-0 flex-1">
          {candles.isLoading ? (
            <div className="absolute inset-0 grid place-items-center text-xs text-muted">Loading {tf} candles…</div>
          ) : candles.error ? (
            <div className="absolute inset-0 grid place-items-center p-4">
              <div className="w-full max-w-md">
                <ErrorState error={candles.error} onRetry={() => candles.refetch()} compact />
                {tf !== "1D" ? (
                  <button type="button" className="mt-2 w-full text-center text-2xs text-accent hover:underline"
                    onClick={() => setTf("1D")}>Show the daily chart instead</button>
                ) : null}
              </div>
            </div>
          ) : !candles.bars.length ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-xs text-muted">
              No {tf} candles for {symbol} yet{INTRADAY.has(tf) ? " (intraday bars appear after the market opens)" : ""}.
            </div>
          ) : (
            <TradingChart
              ref={chartRef}
              symbol={symbol}
              tf={tf}
              bars={candles.bars}
              live={q}
              indicators={indicators}
              tool={tool}
              showLevels={levels}
              dark={resolvedTheme !== "light"}
              hasMore={Boolean(candles.hasNextPage)}
              loadingOlder={candles.isFetchingNextPage}
              onNeedOlder={() => { void candles.fetchNextPage(); }}
              onToolDone={() => setTool("cursor")}
            />
          )}
        </div>
        <footer className="flex flex-wrap justify-between gap-2 border-t border-line px-3 py-1 text-2xs text-faint">
          <span>{candles.meta?.source ?? ""}{tool === "trend" ? " · click two points to draw a trend line" : tool !== "cursor" ? " · click the chart to place it" : ""}</span>
          <span>Times in IST · scroll or pinch to zoom, drag to pan</span>
        </footer>
      </div>
    </div>
  );
}

function Sep() {
  return <span className="mx-1 h-5 w-px shrink-0 bg-line" aria-hidden />;
}

function IconBtn({ label, onClick, active, children, testId }: {
  label: string; onClick(): void; active?: boolean; children: React.ReactNode; testId?: string;
}) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label} aria-pressed={active}
      data-testid={testId}
      className={cn("grid h-7 w-7 shrink-0 place-items-center rounded",
        active ? "bg-accent-soft text-accent" : "text-muted hover:bg-elevated hover:text-ink")}>
      {children}
    </button>
  );
}

// ------------------------------------------------------------ indicators
const IND_ROWS: { key: keyof IndicatorConfig; label: string; params: [string, string][] }[] = [
  { key: "volume", label: "Volume", params: [] },
  { key: "sma", label: "SMA", params: [["period", "Period"]] },
  { key: "ema", label: "EMA", params: [["period", "Period"]] },
  { key: "vwap", label: "VWAP", params: [["period", "Bars (daily)"]] },
  { key: "bb", label: "Bollinger Bands", params: [["period", "Period"], ["mult", "Std dev"]] },
  { key: "supertrend", label: "Supertrend", params: [["period", "ATR"], ["mult", "Factor"]] },
  { key: "rsi", label: "RSI", params: [["period", "Period"]] },
  { key: "macd", label: "MACD", params: [["fast", "Fast"], ["slow", "Slow"], ["signal", "Signal"]] },
];

function IndicatorMenu({ value, onChange }: { value: IndicatorConfig; onChange(v: IndicatorConfig): void }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(() => setOpen(false));
  const count = Object.values(value).filter((v) => v.on).length;
  const set = (key: keyof IndicatorConfig, patch: Record<string, number | boolean>) =>
    onChange({ ...value, [key]: { ...value[key], ...patch } });
  return (
    <div ref={ref} className="relative shrink-0">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} data-testid="indicator-menu"
        className="inline-flex h-7 items-center gap-1 rounded px-2 text-xs font-medium text-muted hover:bg-elevated hover:text-ink">
        Indicators <span className="rounded bg-elevated px-1 tabular text-2xs">{count}</span>
        <ChevronDown className="h-3 w-3" />
      </button>
      {open ? (
        <div className="fixed left-2 right-2 top-28 z-[60] max-h-[70vh] overflow-y-auto rounded-card border border-line bg-surface p-2 shadow-pop sm:absolute sm:left-0 sm:right-auto sm:top-8 sm:w-80">
          {IND_ROWS.map(({ key, label, params }) => {
            const cfg = value[key] as unknown as Record<string, number | boolean>;
            return (
              <div key={key} className="flex flex-wrap items-center gap-2 rounded px-2 py-1.5 hover:bg-elevated">
                <label className="flex min-w-[8.5rem] flex-1 items-center gap-2 text-xs text-ink">
                  <input type="checkbox" checked={Boolean(cfg.on)} data-testid={`ind-${key}`}
                    onChange={(e) => set(key, { on: e.target.checked })} className="accent-[hsl(var(--accent))]" />
                  {label}
                </label>
                {params.map(([p, plabel]) => (
                  <label key={p} className="flex items-center gap-1 text-2xs text-faint">
                    {plabel}
                    <input type="number" inputMode="decimal" min={p === "mult" ? 0.5 : 1} max={500}
                      step={p === "mult" ? 0.5 : 1} value={Number(cfg[p])} id={`ind-${key}-${p}`}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        if (Number.isFinite(v) && v > 0) set(key, { [p]: v });
                      }}
                      className="h-6 w-14 rounded border border-line bg-canvas px-1 text-right tabular text-xs text-ink" />
                  </label>
                ))}
              </div>
            );
          })}
          <p className="px-2 pt-1 text-2xs text-faint">RSI and MACD open in their own panes below the price.</p>
        </div>
      ) : null}
    </div>
  );
}
