"use client";

import { useEffect, useState } from "react";

import { Badge, type Tone } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";

interface StrategyRow {
  id: string;
  book: string;
  strategy: string;
  markets: string;
  since?: string | null;
  open: number;
  pending?: number;
  closed: number;
  wins: number;
  losses: number;
  win_pct: number | null;
  avg_r: number | null;
  total_r: number;
  pnl_rs: number | null;
  expected_r: number | null;
  source?: string | null;
  verdict: string;
}

interface Trade {
  book: string;
  strategy: string;
  symbol?: string;
  side: string;
  entry_time?: string;
  exit_time?: string;
  r?: number;
  why?: string;
}

interface Scorecard {
  rows: StrategyRow[];
  recent_trades: Trade[];
  errors: Record<string, string>;
  min_trades: number;
}

const REFRESH_MS = 60 * 1000;

function shortDate(v?: string | null) {
  if (!v) return "–";
  const d = new Date(v.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return v.slice(0, 10);
  return d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "2-digit" });
}

function r(v: number | null | undefined, digits = 2) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}R`;
}

function rs(v: number | null | undefined) {
  if (v == null) return "–";
  return `${v >= 0 ? "+" : "−"}Rs ${Math.abs(v).toLocaleString("en-IN")}`;
}

function tone(verdict: string): Tone {
  if (verdict === "On track") return "up";
  if (verdict.startsWith("Losing")) return "down";
  if (verdict === "Below backtest") return "warn";
  return "neutral";
}

function signColor(v: number | null | undefined) {
  if (v == null || v === 0) return "text-muted";
  return v > 0 ? "text-up" : "text-down";
}

export default function FrontTestPage() {
  const [data, setData] = useState<Scorecard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get<Scorecard>("/front-test")
        .then((res) => { if (!cancelled) { setData(res); setError(null); } })
        .catch((err) => { if (!cancelled) setError(errorMessage(err)); });
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const rows = data?.rows ?? [];
  const errors = Object.entries(data?.errors ?? {});

  return (
    <div className="space-y-6">
      <div className="border-b border-line pb-4">
        <h1 className="text-2xl font-semibold text-ink">Front Test</h1>
        <p className="text-muted mt-1 text-sm">
          Every strategy being paper traded live, next to what its backtest expects on the 2025-26 hold-out.
          A verdict needs at least {data?.min_trades ?? 20} closed trades.
        </p>
      </div>

      {error ? <Card><CardBody><p className="text-down text-sm">{error}</p></CardBody></Card> : null}
      {errors.length ? (
        <Card><CardBody>
          {errors.map(([k, v]) => <p key={k} className="text-warn text-xs">{k}: {v}</p>)}
        </CardBody></Card>
      ) : null}

      <Card>
        <CardHeader title="Strategy scorecard"
          description="Live R is after costs. P&L is on a Rs 10,000 account at 1% risk (crypto compounds). NSE rows are the S1-S6 forward book." />
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2">Strategy</th>
                <th className="px-3 py-2">Since</th>
                <th className="px-3 py-2 text-right">Open</th>
                <th className="px-3 py-2 text-right">Closed</th>
                <th className="px-3 py-2 text-right">Win %</th>
                <th className="px-3 py-2 text-right">Live avg</th>
                <th className="px-3 py-2 text-right">Backtest avg</th>
                <th className="px-3 py-2 text-right">Total</th>
                <th className="px-3 py-2 text-right">P&amp;L</th>
                <th className="px-4 py-2">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && !error ? (
                <tr><td colSpan={10} className="px-4 py-6 text-center text-muted">Loading…</td></tr>
              ) : null}
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-ink">{row.strategy}</div>
                    <div className="text-2xs text-muted">{row.book} · {row.markets}</div>
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-muted">{shortDate(row.since)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {row.open}{row.pending ? <span className="text-2xs text-muted"> +{row.pending} pending</span> : null}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {row.closed}
                    {row.closed ? <span className="text-2xs text-muted"> ({row.wins}W/{row.losses}L)</span> : null}
                  </td>
                  <td className="px-3 py-2.5 text-right">{row.win_pct == null ? "–" : `${row.win_pct.toFixed(0)}%`}</td>
                  <td className={`px-3 py-2.5 text-right ${signColor(row.avg_r)}`}>{r(row.avg_r)}</td>
                  <td className="px-3 py-2.5 text-right text-muted" title={row.source ?? undefined}>{r(row.expected_r)}</td>
                  <td className={`px-3 py-2.5 text-right ${signColor(row.total_r)}`}>{r(row.total_r)}</td>
                  <td className={`px-3 py-2.5 text-right whitespace-nowrap ${signColor(row.pnl_rs)}`}>{rs(row.pnl_rs)}</td>
                  <td className="px-4 py-2.5"><Badge tone={tone(row.verdict)}>{row.verdict}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardHeader title="Latest closed trades" description="Crypto, gold and forex paper books, newest first." />
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-line text-left text-2xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2">Closed</th>
                <th className="px-3 py-2">Market</th>
                <th className="px-3 py-2">Side</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2 text-right">Result</th>
                <th className="px-4 py-2">Exit</th>
              </tr>
            </thead>
            <tbody>
              {(data?.recent_trades ?? []).length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">No closed trades yet.</td></tr>
              ) : null}
              {(data?.recent_trades ?? []).map((t, i) => (
                <tr key={`${t.symbol}-${t.exit_time}-${i}`} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2 whitespace-nowrap text-muted">{shortDate(t.exit_time)}</td>
                  <td className="px-3 py-2 font-medium text-ink">{t.symbol}</td>
                  <td className="px-3 py-2"><Badge tone={t.side === "short" ? "down" : "up"}>{t.side}</Badge></td>
                  <td className="px-3 py-2 text-muted">{t.strategy}</td>
                  <td className={`px-3 py-2 text-right ${signColor(t.r)}`}>{r(t.r)}</td>
                  <td className="px-4 py-2 text-xs text-muted">{t.why ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
