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
  price?: number;
  buy_above?: number;
  sell_below?: number;
}

type LivePrices = Record<string, { price?: number; source?: string; at?: number; stale?: boolean; error?: string }>;

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
const LIVE_REFRESH_MS = 15 * 1000;

function fmt(v?: number) {
  return v == null ? "–" : v.toLocaleString("en-US", { maximumSignificantDigits: 6 });
}

/** The next 4h candle close (00, 04, 08, 12, 16, 20 UTC), when a signal can fire. */
function next4hClose(now = new Date()) {
  const t = new Date(now);
  t.setUTCMinutes(0, 0, 0);
  t.setUTCHours(Math.floor(now.getUTCHours() / 4) * 4 + 4);
  return t;
}

function pctAway(from?: number, to?: number) {
  if (from == null || to == null || !from) return "";
  const p = ((to - from) / from) * 100;
  return ` (${p >= 0 ? "+" : ""}${p.toFixed(1)}%)`;
}

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

  const [live, setLive] = useState<LivePrices>({});
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get<LivePrices>("/crypto/live")
        .then((res) => { if (!cancelled) setLive(res); })
        .catch(() => undefined);
    load();
    const timer = setInterval(load, LIVE_REFRESH_MS);
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
        <CardHeader title="Live prices and entry levels" />
        <CardBody>
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-line">
                  <th className="py-2 pr-3">Market</th>
                  <th className="py-2 pr-3 text-right">Live price</th>
                  <th className="py-2 pr-3">Position</th>
                  <th className="py-2 pr-3">What triggers the next trade</th>
                </tr>
              </thead>
              <tbody>
                {MARKETS.map((m) => {
                  const st = markets[m.symbol] ?? {};
                  const lp = live[m.symbol];
                  const px = lp?.price ?? st.price;
                  const status = st.status ?? "flat";
                  let action = "–";
                  if (status === "long") {
                    action = `Holding from ${fmt(st.entry)}. Stop ${fmt(st.stop)}${pctAway(px, st.stop)}; sell if a 4h candle closes below ${fmt(st.sell_below)}${pctAway(px, st.sell_below)}`;
                  } else if (status === "exit_next") {
                    action = "Selling at the next 15-minute open";
                  } else if (status === "enter_next") {
                    action = "BUY NOW at market (breakout confirmed)";
                  } else if (st.buy_above != null) {
                    action = `BUY if a 4h candle closes above ${fmt(st.buy_above)}${pctAway(px, st.buy_above)}`;
                  }
                  return (
                    <tr key={m.symbol} className="border-b border-line">
                      <td className="py-2 pr-3 text-ink font-medium">{m.name}</td>
                      <td className="py-2 pr-3 text-right text-ink">
                        {fmt(px)}
                        <div className="text-xs text-muted">
                          {lp?.price != null && !lp.stale ? "live" : st.price != null ? "last 15m close" : lp?.error ? "no price" : ""}
                        </div>
                      </td>
                      <td className={`py-2 pr-3 ${status === "long" ? "text-up" : status === "enter_next" ? "text-warn" : "text-muted"}`}>
                        {status === "long" || status === "exit_next" ? "Long" : status === "enter_next" ? "Buying" : "Flat"}
                      </td>
                      <td className="py-2 pr-3 text-ink">{action}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted mt-3">
            Prices refresh every 15 seconds. Signals are checked on 4h candle closes only: the next is at{" "}
            {next4hClose().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })} IST
            (05:30, 09:30, 13:30, 17:30, 21:30, 01:30). A phone alert goes out within 5 minutes of a signal.
          </p>
        </CardBody>
      </Card>

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
