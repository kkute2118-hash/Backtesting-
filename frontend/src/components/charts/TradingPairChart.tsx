"use client";

import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";

interface PriceTick {
  time: UTCTimestamp;
  price: number;
  volume: number;
}

interface TradeMarker {
  time: UTCTimestamp;
  price: number;
  type: "entry" | "exit" | "stop_loss";
  color: string;
  text: string;
}

export function TradingPairChart({
  symbol,
  entry,
  exit,
  stopLoss,
  status,
  height = 300,
}: {
  symbol: string;
  entry?: number;
  exit?: number;
  stopLoss?: number;
  status: "flat" | "awaiting_retest" | "long" | "exit_next";
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [priceHistory, setPriceHistory] = useState<PriceTick[]>([]);

  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme !== "light";

  // Initialize chart
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ink = isDark ? "#e8edf4" : "#171f2e";
    const grid = isDark ? "#2a3242" : "#e3e8ef";
    const surfaceBg = isDark ? "#131820" : "#f9fafb";

    const chart = createChart(container, {
      height,
      layout: {
        background: { color: surfaceBg },
        textColor: isDark ? "#9aa5b6" : "#5b6474",
        fontFamily: "var(--font-sans)",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: grid, style: 1 },
        horzLines: { color: grid, style: 1 },
      },
      rightPriceScale: { borderColor: grid, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: grid, rightOffset: 2, lockRange: false },
      crosshair: {
        mode: 1,
        vertLine: { color: ink, width: 1, style: 2 },
        horzLine: { color: ink, width: 1, style: 2 },
      },
    });

    const line = chart.addLineSeries({
      color: "#3b82f6",
      lineWidth: 2,
    });

    chartRef.current = chart;
    lineRef.current = line;

    // Set initial data
    if (priceHistory.length > 0) {
      line.setData(priceHistory);
      chart.timeScale().fitContent();
    }

    const handleResize = () => {
      if (container.clientWidth) {
        chart.applyOptions({ width: container.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [isDark, height]);

  // Update chart with new prices
  useEffect(() => {
    if (lineRef.current && priceHistory.length > 0) {
      lineRef.current.setData(priceHistory);
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
      }
    }
  }, [priceHistory]);

  // Add trade markers
  useEffect(() => {
    if (!chartRef.current || !lineRef.current) return;

    const markers: TradeMarker[] = [];

    if (entry && priceHistory.length > 0) {
      const lastTime = priceHistory[priceHistory.length - 1].time;
      markers.push({
        time: lastTime,
        price: entry,
        type: "entry",
        color: "#22c55e",
        text: "E",
      });
    }

    if (stopLoss && priceHistory.length > 0) {
      const lastTime = priceHistory[priceHistory.length - 1].time;
      markers.push({
        time: lastTime,
        price: stopLoss,
        type: "stop_loss",
        color: "#ef4444",
        text: "SL",
      });
    }

    if (exit && priceHistory.length > 0) {
      const lastTime = priceHistory[priceHistory.length - 1].time;
      markers.push({
        time: lastTime,
        price: exit,
        type: "exit",
        color: "#f59e0b",
        text: "X",
      });
    }

    lineRef.current.setMarkers(
      markers.map((m) => ({
        time: m.time,
        position: "inBar" as const,
        color: m.color,
        shape: "circle" as const,
        text: m.text,
        size: 2,
      }))
    );
  }, [entry, exit, stopLoss, priceHistory]);

  // Simulate live price updates (in production, connect to WebSocket)
  useEffect(() => {
    const interval = setInterval(() => {
      setPriceHistory((prev) => {
        const newPrice = prev.length > 0 ? prev[prev.length - 1].price * (0.9995 + Math.random() * 0.001) : 100;
        const newTime = (Math.floor(Date.now() / 1000) + Math.random() * 10) as UTCTimestamp;
        const newTick: PriceTick = {
          time: newTime,
          price: newPrice,
          volume: Math.random() * 1000,
        };
        return [...prev.slice(-500), newTick]; // Keep last 500 bars
      });
    }, 5000); // Update every 5 seconds

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <h3 className="font-semibold text-ink">{symbol}</h3>
        <div
          className={`text-xs px-2 py-1 rounded ${
            status === "long"
              ? "bg-positive text-white"
              : status === "awaiting_retest"
                ? "bg-warning text-ink"
                : "bg-surface text-muted"
          }`}
        >
          {status === "flat"
            ? "⏳ Waiting"
            : status === "awaiting_retest"
              ? "🔄 Awaiting"
              : status === "long"
                ? "📈 LONG"
                : "📉 Exit"}
        </div>
      </div>
      <div ref={containerRef} style={{ width: "100%", height }} />
    </div>
  );
}
