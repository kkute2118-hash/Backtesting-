"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { api, ApiError, errorMessage } from "@/lib/api";

interface TrendStats {
  equity: number;
  trades: number;
  total_r: number;
  avg_r: number;
  return_multiple: number;
  paper_start: string;
  updated: string;
  markets: Record<string, any>;
}

interface EquityCurve {
  trade_num: number;
  equity: number;
  timestamp: string;
}

interface Trade {
  symbol: string;
  entry_time: string;
  exit_time: string;
  entry: number;
  exit: number;
  why: string;
  r: number;
}

export default function CryptoTradingPage() {
  const [stats, setStats] = useState<TrendStats | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [, setEquity] = useState<EquityCurve[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const empty = (err: unknown) => {
          if (err instanceof ApiError && err.isNotFound) return null;
          throw err;
        };
        const [statsData, tradesData, equityData] = await Promise.all([
          api.get<TrendStats>("/crypto/stats"),
          api.get<{ trades: Trade[] }>("/crypto/trades").catch(empty),
          api.get<{ curve: EquityCurve[] }>("/crypto/equity").catch(empty),
        ]);

        setStats(statsData);
        setTrades(tradesData?.trades ?? []);
        setEquity(equityData?.curve ?? []);
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError && err.isNotFound
          ? "The paper book has not run yet. It runs every 5 minutes on the server."
          : errorMessage(err));
      } finally {
        setLoading(false);
      }
    };

    fetchData();

    if (autoRefresh) {
      const interval = setInterval(fetchData, 30000); // Refresh every 30 seconds
      return () => clearInterval(interval);
    }
  }, [autoRefresh]);

  if (loading) {
    return (
      <div className="p-8">
        <h1 className="text-3xl font-bold mb-4">Crypto Trading (4h breakout)</h1>
        <div className="text-lg text-muted">Loading trading data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <h1 className="text-3xl font-bold mb-4">Crypto Trading (4h breakout)</h1>
        <Card>
          <CardBody>
            <p className="text-down">⚠️ {error}</p>
                      </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-3xl font-bold text-ink">Crypto Trading (4h breakout)</h1>
          <p className="text-muted mt-2">
            4h breakout 40/30, 1.5 ATR stop, 1% risk a trade, on BTC, ETH, SOL and gold perpetuals
          </p>
        </div>
        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={`px-4 py-2 rounded ${
            autoRefresh ? "bg-accent text-white" : "bg-surface text-ink border border-line"
          }`}
        >
          {autoRefresh ? "🔄 Auto-refresh ON" : "⏸️ Auto-refresh OFF"}
        </button>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader title="Current Equity" />
          <CardBody>
            <div className="text-2xl font-bold">Rs {stats?.equity?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
            <p className="text-xs text-muted mt-1">Started: Rs 10,000</p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Return Multiple" />
          <CardBody>
            <div className="text-2xl font-bold">{stats?.return_multiple?.toFixed(1)}x</div>
            <p className="text-xs text-muted mt-1">Growth factor</p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Trades" />
          <CardBody>
            <div className="text-2xl font-bold">{stats?.trades}</div>
            <p className="text-xs text-muted mt-1">Since {stats?.paper_start?.substring(0, 10)}</p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Avg R" />
          <CardBody>
            <div className={`text-2xl font-bold ${stats?.avg_r && stats.avg_r > 0 ? "text-up" : "text-down"}`}>
              {stats?.avg_r?.toFixed(2)}R
            </div>
            <p className="text-xs text-muted mt-1">Risk-adjusted return</p>
          </CardBody>
        </Card>
      </div>

      {/* Markets Status */}
      <Card className="mb-6">
        <CardHeader title="Live Markets Status" />
        <CardBody>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {stats?.markets &&
              Object.entries(stats.markets).map(([symbol, market]: [string, any]) => (
                <div key={symbol} className="border border-line rounded p-3 bg-surface">
                  <div className="font-bold text-sm text-ink">{symbol}</div>
                  <div className="text-xs text-muted mt-1">
                    {market.status === "flat" && "⏳ Waiting for breakout"}
                    {market.status === "enter_next" && `🔄 Buying at the next open (broke ${market.level?.toFixed(4) ?? "the 40-bar high"})`}
                    {market.status === "long" && `📈 LONG from ${market.entry?.toFixed(4)}${market.stop ? `, stop ${market.stop.toFixed(4)}` : ""}`}
                    {market.status === "exit_next" && "📉 Selling at next open"}
                  </div>
                </div>
              ))}
          </div>
        </CardBody>
      </Card>

      {/* Recent Trades */}
      <Card>
        <CardHeader title="Recent Closed Trades" />
        <CardBody>
          {trades.length === 0 ? (
            <p className="text-muted">No trades closed yet. Waiting for first breakout signal...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface border-b border-line">
                  <tr>
                    <th className="text-left p-2 text-ink font-semibold">Symbol</th>
                    <th className="text-left p-2 text-ink font-semibold">Entry Time</th>
                    <th className="text-right p-2 text-ink font-semibold">Entry</th>
                    <th className="text-right p-2 text-ink font-semibold">Exit</th>
                    <th className="text-left p-2 text-ink font-semibold">Why</th>
                    <th className="text-right p-2 text-ink font-semibold">R</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 20).map((trade, i) => (
                    <tr key={i} className="border-b border-line hover:bg-surface">
                      <td className="p-2 font-bold text-ink">{trade.symbol}</td>
                      <td className="p-2 text-xs text-muted">{new Date(trade.entry_time).toLocaleString()}</td>
                      <td className="p-2 text-right text-ink">{trade.entry?.toFixed(4)}</td>
                      <td className="p-2 text-right text-ink">{trade.exit?.toFixed(4)}</td>
                      <td className="p-2 text-muted">{trade.why}</td>
                      <td className={`p-2 text-right font-bold ${trade.r > 0 ? "text-up" : "text-down"}`}>
                        {trade.r?.toFixed(2)}R
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      <p className="text-xs text-muted mt-4">
        Last updated: {stats?.updated && !Number.isNaN(Date.parse(stats.updated)) ? new Date(stats.updated).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : (stats?.updated ?? "–")} IST | Strategy: 4h breakout 40/30, 1.5 ATR stop, 1% risk
      </p>
    </div>
  );
}
