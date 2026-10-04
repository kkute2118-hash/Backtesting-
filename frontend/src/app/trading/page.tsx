"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { TradingPairChart } from "@/components/charts/TradingPairChart";

interface TradeAlert {
  id: string;
  symbol: string;
  type: "entry" | "exit" | "breakout" | "retest";
  message: string;
  timestamp: string;
  read: boolean;
}

interface MarketData {
  symbol: string;
  status: "flat" | "awaiting_retest" | "long" | "exit_next";
  entry?: number;
  exit?: number;
  stopLoss?: number;
  currentPrice?: number;
  leverage?: number;
}

const TRADING_SYMBOLS = [
  { symbol: "BTCUSDT", name: "Bitcoin" },
  { symbol: "ETHUSDT", name: "Ethereum" },
  { symbol: "SOLUSDT", name: "Solana" },
  { symbol: "XAUUSDT", name: "Gold" },
  { symbol: "EURUSD", name: "EUR/USD" },
  { symbol: "GBPUSD", name: "GBP/USD" },
  { symbol: "USDCAD", name: "USD/CAD" },
  { symbol: "USDJPY", name: "USD/JPY" },
  { symbol: "AUDUSD", name: "AUD/USD" },
];

export default function TradingPage() {
  const [marketData, setMarketData] = useState<Record<string, MarketData>>({});
  const [alerts, setAlerts] = useState<TradeAlert[]>([]);
  const [showAlerts, setShowAlerts] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);

  // Fetch initial market data
  useEffect(() => {
    const fetchMarketData = async () => {
      try {
        const res = await fetch("/api/v1/crypto/stats");
        const stats = await res.json();

        const newMarketData: Record<string, MarketData> = {};
        TRADING_SYMBOLS.forEach((sym) => {
          const market = stats.markets?.[sym.symbol];
          newMarketData[sym.symbol] = {
            symbol: sym.symbol,
            status: market?.status || "flat",
            entry: market?.entry,
            leverage: market?.leverage,
            stopLoss: market?.entry && market?.entry * 0.98, // Simplified: 2% stop loss
          };
        });

        setMarketData(newMarketData);
      } catch (error) {
        console.error("Failed to fetch market data:", error);
      }
    };

    fetchMarketData();
  }, []);

  // Request notification permission
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // Simulate receiving trade alerts from backend
  useEffect(() => {
    const simulateAlerts = () => {
      // In production, this would be a WebSocket connection to the backend
      const symbols = TRADING_SYMBOLS.map((s) => s.symbol);
      const randomSymbol = symbols[Math.floor(Math.random() * symbols.length)];
      const alertTypes: Array<"entry" | "exit" | "breakout" | "retest"> = ["breakout", "retest", "entry"];
      const randomType = alertTypes[Math.floor(Math.random() * alertTypes.length)];

      if (Math.random() > 0.9) {
        // 10% chance to generate an alert every poll
        const newAlert: TradeAlert = {
          id: `${Date.now()}`,
          symbol: randomSymbol,
          type: randomType,
          message:
            randomType === "breakout"
              ? `${randomSymbol}: Breakout detected - wait for retest`
              : randomType === "retest"
                ? `${randomSymbol}: RETEST ENTRY NOW - Market entry ready`
                : `${randomSymbol}: Entry confirmed - position opened`,
          timestamp: new Date().toLocaleTimeString("en-IN"),
          read: false,
        };

        setAlerts((prev) => [newAlert, ...prev.slice(0, 19)]);
        setUnreadCount((prev) => prev + 1);

        // Browser notification
        if (Notification.permission === "granted") {
          new Notification(`⚠️ ${randomSymbol} Signal`, {
            body: newAlert.message,
            badge: "/icon.svg",
            tag: randomSymbol,
            requireInteraction: randomType === "entry",
          });
        }

        // Update market data to reflect new signal
        setMarketData((prev) => ({
          ...prev,
          [randomSymbol]: {
            ...prev[randomSymbol],
            status: randomType === "entry" ? "long" : "awaiting_retest",
          },
        }));
      }
    };

    const interval = setInterval(simulateAlerts, 30000); // Check every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const handleAlertRead = () => {
    setAlerts((prev) => prev.map((a) => ({ ...a, read: true })));
    setUnreadCount(0);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 border-b border-line pb-4">
        <div>
          <h1 className="text-3xl font-bold text-ink">📊 Live Trading Signals</h1>
          <p className="text-muted mt-1">9 Pairs • Retest Entry + Dynamic Leverage • Real-time Charts</p>
        </div>
        <button
          onClick={() => setShowAlerts(!showAlerts)}
          className={`px-4 py-2 rounded font-medium text-sm ${
            showAlerts ? "bg-positive text-white" : "bg-surface text-ink"
          }`}
        >
          🔔 Alerts {unreadCount > 0 && <span className="ml-2 badge">{unreadCount}</span>}
        </button>
      </div>

      {/* Alerts Panel */}
      {showAlerts && alerts.length > 0 && (
        <Card>
          <CardHeader title="Recent Signals" action={<button onClick={handleAlertRead}>Mark read</button>} />
          <CardBody>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {alerts.map((alert) => (
                <div
                  key={alert.id}
                  className={`p-3 rounded border ${
                    alert.read
                      ? "border-line bg-surface text-muted"
                      : "border-positive bg-positive/10 text-ink font-medium"
                  }`}
                >
                  <div className="flex justify-between items-start gap-2">
                    <div className="flex-1">
                      <div className="font-semibold">{alert.symbol}</div>
                      <div className="text-sm mt-1">{alert.message}</div>
                    </div>
                    <div className="text-xs text-muted shrink-0">{alert.timestamp}</div>
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Live Charts Grid */}
      <Card>
        <CardHeader title="Live Price Charts (4H Timeframe)" />
        <CardBody>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {TRADING_SYMBOLS.map((sym) => (
              <TradingPairChart
                key={sym.symbol}
                symbol={sym.symbol}
                status={marketData[sym.symbol]?.status || "flat"}
                entry={marketData[sym.symbol]?.entry}
                stopLoss={marketData[sym.symbol]?.stopLoss}
                height={250}
              />
            ))}
          </div>
        </CardBody>
      </Card>

      {/* Stats Footer */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
        <div className="p-3 rounded border border-line">
          <div className="text-2xl font-bold text-positive">
            {Object.values(marketData).filter((m) => m.status === "long").length}
          </div>
          <div className="text-xs text-muted mt-1">Active Positions</div>
        </div>
        <div className="p-3 rounded border border-line">
          <div className="text-2xl font-bold text-warning">
            {Object.values(marketData).filter((m) => m.status === "awaiting_retest").length}
          </div>
          <div className="text-xs text-muted mt-1">Awaiting Retest</div>
        </div>
        <div className="p-3 rounded border border-line">
          <div className="text-2xl font-bold text-ink">{alerts.length}</div>
          <div className="text-xs text-muted mt-1">Signals Today</div>
        </div>
        <div className="p-3 rounded border border-line">
          <div className="text-2xl font-bold text-critical">{unreadCount}</div>
          <div className="text-xs text-muted mt-1">Unread Alerts</div>
        </div>
      </div>
    </div>
  );
}
