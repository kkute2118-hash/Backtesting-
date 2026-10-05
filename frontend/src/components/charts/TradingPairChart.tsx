"use client";

import {
  createChart, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { api, errorMessage } from "@/lib/api";

export type MarketStatus =
  | "flat" | "enter_next" | "awaiting_retest" | "long" | "exit_next" | "pending";

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface CandleResponse {
  symbol: string;
  source: string;
  candles: Candle[];
  stale?: boolean;
}

const STATUS_LABEL: Record<MarketStatus, string> = {
  flat: "Waiting",
  enter_next: "Buy at next open",
  awaiting_retest: "Awaiting retest",
  long: "Long",
  exit_next: "Exit next open",
  pending: "Pending",
};

const STATUS_CLASS: Record<MarketStatus, string> = {
  flat: "bg-surface text-muted",
  enter_next: "bg-warn-soft text-warn",
  awaiting_retest: "bg-warn-soft text-warn",
  long: "bg-up-soft text-up",
  exit_next: "bg-down-soft text-down",
  pending: "bg-surface text-muted",
};

const REFRESH_MS = 5 * 60 * 1000;

export function TradingPairChart({
  symbol,
  name,
  status,
  entry,
  stopLoss,
  level,
  height = 260,
}: {
  symbol: string;
  name: string;
  status: MarketStatus;
  entry?: number;
  stopLoss?: number;
  level?: number;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const [data, setData] = useState<CandleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get<CandleResponse>(`/crypto/candles/${symbol}`, { bars: 120 })
        .then((res) => { if (!cancelled) { setData(res); setError(null); } })
        .catch((err) => { if (!cancelled) setError(errorMessage(err)); });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [symbol]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const grid = isDark ? "#2a3242" : "#e3e8ef";
    const chart = createChart(container, {
      height,
      width: container.clientWidth,
      layout: {
        background: { color: "transparent" },
        textColor: isDark ? "#9aa5b6" : "#5b6474",
        fontSize: 10,
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: true, rightOffset: 2 },
    });
    const series = chart.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", borderVisible: false,
      wickUpColor: "#16a34a", wickDownColor: "#dc2626",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    linesRef.current = [];
    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [isDark, height]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !data) return;
    series.setData(data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })));
    linesRef.current.forEach((line) => series.removePriceLine(line));
    const lines: IPriceLine[] = [];
    const add = (price: number | undefined, color: string, title: string) => {
      if (price && Number.isFinite(price)) {
        lines.push(series.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, title, axisLabelVisible: true }));
      }
    };
    if (status === "long" || status === "exit_next") {
      add(entry, "#16a34a", "Entry");
      add(stopLoss, "#dc2626", "Stop");
    } else if (status === "awaiting_retest" || status === "enter_next") {
      add(level, "#d97706", "Breakout level");
    }
    linesRef.current = lines;
    chartRef.current?.timeScale().fitContent();
  }, [data, status, entry, stopLoss, level, isDark, height]);

  const last = data?.candles.at(-1)?.close;

  return (
    <div className="space-y-2 min-w-0">
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="min-w-0">
          <div className="font-semibold text-ink">{symbol}</div>
          <div className="text-xs text-muted truncate">
            {name}{last !== undefined ? ` · ${last.toLocaleString("en-IN", { maximumSignificantDigits: 6 })}` : ""}
          </div>
        </div>
        <span className={`text-xs px-2 py-1 rounded shrink-0 ${STATUS_CLASS[status] ?? STATUS_CLASS.flat}`}>
          {STATUS_LABEL[status] ?? status}
        </span>
      </div>
      <div ref={containerRef} style={{ width: "100%", height }} />
      <div className="text-[11px] text-muted px-1">
        {error ? <span title={error}>Prices unavailable right now</span>
          : data ? `4h candles · ${data.source}${data.stale ? " (cached)" : ""}` : "Loading prices…"}
      </div>
    </div>
  );
}
