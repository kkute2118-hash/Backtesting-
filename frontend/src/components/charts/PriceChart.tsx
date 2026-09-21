"use client";

import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";

import type { History } from "@/types/api";
import { cn } from "@/lib/utils";

const MA_COLOURS: Record<string, string> = {
  ema20: "#3b82f6",
  ema50: "#f59e0b",
  ema200: "#a855f7",
};

function toTime(value: string): UTCTimestamp {
  return (new Date(value).getTime() / 1000) as UTCTimestamp;
}

const TURNOVER_LOOKBACK = 20;

/** Traded value in Rs crore: price x shares, which is the money that changed
 *  hands. Volume alone cannot be compared across stocks; turnover can. */
function turnoverCr(close: number, volume: number): number {
  return (close * volume) / 1e7;
}

function formatCr(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--";
  if (value >= 1000) return `${Math.round(value).toLocaleString("en-IN")} cr`;
  if (value >= 100) return `${value.toFixed(0)} cr`;
  if (value >= 10) return `${value.toFixed(1)} cr`;
  return `${value.toFixed(2)} cr`;
}

type TurnoverRow = {
  time: UTCTimestamp;
  day: number;
  avg: number | null;
  ratio: number | null;
};

/** Per-bar turnover and its trailing average.
 *
 *  The average is over 20 bars because that is the only lookback the source
 *  ever names, and he names it twice - "almost 250 crores on an average for
 *  the 20 days", "80 crores average turnover last 20 days".
 *
 *  It is TRAILING and EXCLUDES the bar itself. Including today would let a
 *  single huge day lift its own benchmark and quietly shrink the very spike
 *  you are trying to see.
 */
function buildTurnover(candles: History["candles"]): TurnoverRow[] {
  const day = candles.map((c) => turnoverCr(c.close, c.volume));
  let running = 0;
  return candles.map((candle, i) => {
    if (i > 0) running += day[i - 1];
    if (i > TURNOVER_LOOKBACK) running -= day[i - 1 - TURNOVER_LOOKBACK];
    const avg = i >= TURNOVER_LOOKBACK ? running / TURNOVER_LOOKBACK : null;
    return {
      time: toTime(candle.time),
      day: day[i],
      avg,
      ratio: avg && avg > 0 ? day[i] / avg : null,
    };
  });
}

/**
 * The price chart: candles, volume and the moving averages the strategies use.
 *
 * lightweight-charts rather than a general plotting library because this is a
 * price chart specifically — it gets crosshair, log scale, pan and zoom, and
 * correct candle rendering at a few thousand bars without any of it being
 * rebuilt here.
 *
 * The overlays drawn are exactly the EMAs the engine computes (20/50/200), so
 * what is on the chart is what the rules were evaluated against.
 */
export function PriceChart({
  history,
  overlays,
  height = 420,
}: {
  history: History;
  overlays: string[];
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";

  const turnover = useMemo(() => buildTurnover(history.candles), [history.candles]);
  // What the readout shows when the pointer is off the chart: the newest bar.
  const [hovered, setHovered] = useState<TurnoverRow | null>(null);
  const latest = turnover.length ? turnover[turnover.length - 1] : null;
  const shown = hovered ?? latest;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ink = isDark ? "#e8edf4" : "#171f2e";
    const grid = isDark ? "#2a3242" : "#e3e8ef";
    const chart = createChart(container, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: isDark ? "#9aa5b6" : "#5b6474",
        fontFamily: "var(--font-sans)",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: grid, style: 1 },
        horzLines: { color: grid, style: 1 },
      },
      rightPriceScale: { borderColor: grid, scaleMargins: { top: 0.08, bottom: 0.26 } },
      timeScale: { borderColor: grid, rightOffset: 4 },
      crosshair: {
        mode: 1,
        vertLine: { color: ink, width: 1, style: 2, labelBackgroundColor: "#2563eb" },
        horzLine: { color: ink, width: 1, style: 2, labelBackgroundColor: "#2563eb" },
      },
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
    });
    chartRef.current = chart;

    const candles: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candles.setData(
      history.candles.map((candle) => ({
        time: toTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );

    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      history.candles.map((candle) => ({
        time: toTime(candle.time),
        value: candle.volume,
        color: candle.close >= candle.open
          ? "rgba(34,197,94,0.32)"
          : "rgba(239,68,68,0.32)",
      })),
    );

    for (const key of overlays) {
      const series = history.overlays[key];
      if (!series) continue;
      const line = chart.addLineSeries({
        color: MA_COLOURS[key] ?? "#94a3b8",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(
        series
          .filter((point) => point.value !== null)
          .map((point) => ({ time: toTime(point.time), value: point.value as number })),
      );
    }

    // The readout follows the crosshair, so the average can be read at the bar
    // that matters rather than only at the right-hand edge.
    const byTime = new Map(turnover.map((row) => [row.time as number, row]));
    chart.subscribeCrosshairMove((param) => {
      const t = param.time as number | undefined;
      setHovered(t === undefined ? null : byTime.get(t) ?? null);
    });

    chart.timeScale().fitContent();

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width });
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [history, overlays, height, isDark, turnover]);

  // Plain description of the reading, with no claim about who was buying.
  // A high multiple says money moved, not that it was smart money; a big
  // candle on an average day's turnover is the one that deserves suspicion.
  const ratio = shown?.ratio ?? null;
  const tone =
    ratio === null ? "text-muted"
    : ratio >= 2 ? "text-up"
    : ratio >= 1.2 ? "text-ink"
    : ratio < 0.7 ? "text-down"
    : "text-muted";
  const verdict =
    ratio === null ? ""
    : ratio >= 3 ? "money flooded in"
    : ratio >= 2 ? "clear money flow"
    : ratio >= 1.2 ? "above its own average"
    : ratio >= 0.7 ? "ordinary day"
    : "thin - move has no money behind it";

  return (
    <div className="relative">
      {/* Turnover, top-left, the way his charts carry it. Follows the
          crosshair so it can be read at the bar being studied. */}
      <div className="pointer-events-none absolute left-3 top-2 z-10 rounded-md border
        border-line bg-surface/85 px-2.5 py-1.5 shadow-card backdrop-blur-sm">
        <p className="text-2xs uppercase tracking-wide text-faint">
          Turnover{hovered ? "" : " (latest)"}
        </p>
        <p className="font-mono text-xs font-medium text-ink">{formatCr(shown?.day ?? null)}</p>
        <p className="font-mono text-2xs text-muted">
          {TURNOVER_LOOKBACK}D avg {formatCr(shown?.avg ?? null)}
        </p>
        <p className={cn("text-2xs font-medium", tone)}>
          {ratio === null
            ? `needs ${TURNOVER_LOOKBACK} bars`
            : `${ratio.toFixed(2)}x avg - ${verdict}`}
        </p>
      </div>
      <div ref={containerRef} className="w-full" role="img"
        aria-label={`Daily candlestick chart for ${history.symbol}`} />
      <div className="flex flex-wrap items-center gap-3 px-3 pb-2 pt-1">
        {overlays.map((key) => (
          <span key={key} className="flex items-center gap-1.5 text-2xs text-muted">
            <span className="h-0.5 w-4 rounded-full"
              style={{ background: MA_COLOURS[key] ?? "#94a3b8" }} aria-hidden />
            {key.toUpperCase()}
          </span>
        ))}
      </div>
    </div>
  );
}
