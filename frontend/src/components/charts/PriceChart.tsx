"use client";

import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";

import type { History } from "@/types/api";

const MA_COLOURS: Record<string, string> = {
  ema20: "#3b82f6",
  ema50: "#f59e0b",
  ema200: "#a855f7",
};

function toTime(value: string): UTCTimestamp {
  return (new Date(value).getTime() / 1000) as UTCTimestamp;
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
  }, [history, overlays, height, isDark]);

  return (
    <div className="relative">
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
