"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { TradingPairChart, type MarketStatus } from "@/components/charts/TradingPairChart";
import { api, ApiError, errorMessage } from "@/lib/api";

interface MarketState {
  status?: MarketStatus;
  entry?: number;
  stop?: number;
  level?: number;
  size_x?: number;
}

interface TrendLatest {
  updated: string;
  paper_start: string;
  equity: number;
  trades: number;
  total_r: number;
  markets: Record<string, MarketState>;
  recent_events: string[];
  sources: Record<string, string>;
}

const MARKETS = [
  { symbol: "BTCUSDT", name: "Bitcoin" },
  { symbol: "ETHUSDT", name: "Ethereum" },
  { symbol: "SOLUSDT", name: "Solana" },
  { symbol: "XAUUSDT", name: "Gold" },
];

const REFRESH_MS = 60 * 1000;

function istTime(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export default function TradingPage() {
  const [latest, setLatest] = useState<TrendLatest | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get<TrendLatest>("/crypto/trend-latest")
        .then((res) => { if (!cancelled) { setLatest(res); setError(null); } })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof ApiError && err.isNotFound
            ? "The paper book has not run yet. It runs every 5 minutes on the server."
            : errorMessage(err));
        });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const markets = latest?.markets ?? {};
  const count = (s: MarketStatus[]) =>
    Object.values(markets).filter((m) => m.status && s.includes(m.status)).length;
  const events = [...(latest?.recent_events ?? [])].reverse().slice(0, 25);

  return (
    <div className="space-y-6">
      <div className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Live Signals</h1>
        <p className="text-muted mt-1 text-sm">
          4h breakout 40/30 · 1.5 ATR stop · 1% risk · BTC, ETH, SOL, gold · paper book
          {latest ? ` · updated ${istTime(latest.updated)} IST` : ""}
        </p>
      </div>

      {error ? (
        <Card><CardBody><p className="text-down text-sm">{error}</p></CardBody></Card>
      ) : null}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Long", value: count(["long", "exit_next"]), tone: "text-up" },
          { label: "Buying at next open", value: count(["enter_next"]), tone: "text-warn" },
          { label: "Closed trades", value: latest?.trades ?? "–", tone: "text-ink" },
          {
            label: "Paper equity",
            value: latest ? `Rs ${latest.equity.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "–",
            tone: "text-ink",
          },
        ].map((s) => (
          <div key={s.label} className="p-3 rounded-card border border-line bg-surface">
            <div className={`text-xl font-semibold tabular-nums ${s.tone}`}>{s.value}</div>
            <div className="text-xs text-muted mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <Card>
        <CardHeader title="Markets (4h candles)" />
        <CardBody>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {MARKETS.map((m) => {
              const st = markets[m.symbol] ?? {};
              return (
                <TradingPairChart
                  key={m.symbol}
                  symbol={m.symbol}
                  name={m.name}
                  status={st.status ?? "flat"}
                  entry={st.entry}
                  stopLoss={st.stop}
                  level={st.level}
                />
              );
            })}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Recent signals" />
        <CardBody>
          {events.length === 0 ? (
            <p className="text-sm text-muted">No signals yet. Breakouts, entries and exits appear here.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {events.map((e, i) => (
                <li key={i} className="border-b border-line pb-2 text-ink">{e}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted mt-4">
            Phone alerts: the ntfy topic is on the{" "}
            <a className="underline" href="/reports/trend.html">paper book page</a>.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
