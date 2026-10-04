"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
  const [equipty, setEquity] = useState<EquityCurve[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, tradesRes, equityRes] = await Promise.all([
          fetch("/api/v1/crypto/stats"),
          fetch("/api/v1/crypto/trades"),
          fetch("/api/v1/crypto/equity"),
        ]);

        if (!statsRes.ok || !tradesRes.ok || !equityRes.ok) {
          throw new Error("Failed to fetch crypto data");
        }

        const statsData = await statsRes.json();
        const tradesData = await tradesRes.json();
        const equityData = await equityRes.json();

        setStats(statsData);
        setTrades(tradesData.trades || []);
        setEquity(equityData.curve || []);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
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
        <h1 className="text-3xl font-bold mb-4">🚀 Crypto Trading (4H Retest Entry)</h1>
        <div className="text-lg text-gray-600">Loading trading data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <h1 className="text-3xl font-bold mb-4">🚀 Crypto Trading (4H Retest Entry)</h1>
        <Card className="border-red-300 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-800">⚠️ {error}</p>
            <p className="text-sm text-red-600 mt-2">The trend_paper.py job may not have run yet. Check Oracle logs.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-3xl font-bold">🚀 Crypto Trading (4H Retest Entry)</h1>
          <p className="text-gray-600 mt-2">
            Retest entry + Dynamic leverage on 9 pairs (4 crypto + 5 forex)
          </p>
        </div>
        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={`px-4 py-2 rounded ${
            autoRefresh ? "bg-green-600 text-white" : "bg-gray-300 text-gray-700"
          }`}
        >
          {autoRefresh ? "🔄 Auto-refresh ON" : "⏸️ Auto-refresh OFF"}
        </button>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Current Equity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">Rs {stats?.equity?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
            <p className="text-xs text-gray-500 mt-1">Started: Rs 10,000</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Return Multiple</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.return_multiple?.toFixed(1)}x</div>
            <p className="text-xs text-gray-500 mt-1">Growth factor</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Trades</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.trades}</div>
            <p className="text-xs text-gray-500 mt-1">Over {stats?.paper_start?.substring(0, 10)}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-600">Avg R</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${stats?.avg_r && stats.avg_r > 0 ? "text-green-600" : "text-red-600"}`}>
              {stats?.avg_r?.toFixed(2)}R
            </div>
            <p className="text-xs text-gray-500 mt-1">Risk-adjusted return</p>
          </CardContent>
        </Card>
      </div>

      {/* Markets Status */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Live Markets Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {stats?.markets &&
              Object.entries(stats.markets).map(([symbol, market]: [string, any]) => (
                <div key={symbol} className="border rounded p-3 bg-gray-50">
                  <div className="font-bold text-sm">{symbol}</div>
                  <div className="text-xs text-gray-600 mt-1">
                    {market.status === "flat" && "⏳ Waiting for breakout"}
                    {market.status === "awaiting_retest" && "🔄 Awaiting retest"}
                    {market.status === "long" && `📈 LONG from ${market.entry?.toFixed(4)}`}
                    {market.status === "exit_next" && "📉 Selling at next open"}
                  </div>
                </div>
              ))}
          </div>
        </CardContent>
      </Card>

      {/* Recent Trades */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Closed Trades</CardTitle>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <p className="text-gray-600">No trades closed yet. Waiting for first breakout signal...</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-100">
                  <tr>
                    <th className="text-left p-2">Symbol</th>
                    <th className="text-left p-2">Entry Time</th>
                    <th className="text-right p-2">Entry</th>
                    <th className="text-right p-2">Exit</th>
                    <th className="text-left p-2">Why</th>
                    <th className="text-right p-2">R</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 20).map((trade, i) => (
                    <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                      <td className="p-2 font-bold">{trade.symbol}</td>
                      <td className="p-2 text-xs">{new Date(trade.entry_time).toLocaleString()}</td>
                      <td className="p-2 text-right">{trade.entry?.toFixed(4)}</td>
                      <td className="p-2 text-right">{trade.exit?.toFixed(4)}</td>
                      <td className="p-2">{trade.why}</td>
                      <td className={`p-2 text-right font-bold ${trade.r > 0 ? "text-green-600" : "text-red-600"}`}>
                        {trade.r?.toFixed(2)}R
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-gray-500 mt-4">
        Last updated: {stats?.updated} IST | Strategy: Retest entry + Dynamic leverage (3x-8x)
      </p>
    </div>
  );
}
