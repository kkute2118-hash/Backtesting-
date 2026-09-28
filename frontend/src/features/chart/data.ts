"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, apiUrl } from "@/lib/api";

import type { Bar } from "./indicators";

export const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export const INTRADAY: ReadonlySet<Timeframe> = new Set(["1m", "5m", "15m", "30m", "1H", "4H"]);
export const TF_SECONDS: Record<Timeframe, number> = {
  "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400,
  "1D": 86400, "1W": 604800, "1M": 2592000,
};

export interface CandlePage {
  symbol: string;
  tf: Timeframe;
  candles: Bar[];
  has_more: boolean;
  next_before: number | null;
  source: string;
  timeframes: Timeframe[];
  market_open: boolean;
}

export interface LiveQuote {
  symbol: string;
  ltp: number;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  session: string;
  source: "LIVE" | "LAST TRADE" | "STORED CLOSE";
  ts: string | null;
  market_open: boolean;
}

/**
 * Candles for one symbol and timeframe, a page at a time. The first page is
 * the recent past; `fetchNextPage` fetches the next OLDER page, which the
 * chart asks for only when the user scrolls to the left edge.
 */
export function useCandles(symbol: string, tf: Timeframe) {
  const query = useInfiniteQuery({
    queryKey: ["chart-candles", symbol, tf],
    queryFn: ({ pageParam }) =>
      api.get<CandlePage>(`/stocks/${encodeURIComponent(symbol)}/candles`, { tf, before: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.has_more && last.next_before ? last.next_before : undefined),
    staleTime: INTRADAY.has(tf) ? 30_000 : 5 * 60_000,
    enabled: Boolean(symbol),
  });
  // Pages arrive newest-first; the chart wants one ascending, de-duplicated array.
  const bars = useMemo(() => {
    const seen = new Set<number>();
    const out: Bar[] = [];
    for (const page of [...(query.data?.pages ?? [])].reverse()) {
      for (const c of page.candles) {
        if (!seen.has(c.time)) { seen.add(c.time); out.push(c); }
      }
    }
    return out.sort((a, b) => a.time - b.time);
  }, [query.data]);
  const first = query.data?.pages[0];
  return { ...query, bars, meta: first };
}

export type LiveStatus = "connecting" | "live" | "closed" | "polling" | "offline";

/**
 * The live quote for one symbol: fetched once, then streamed while the market
 * is open. Exactly one EventSource per open chart, closed on unmount or when
 * the server says the session has closed. If streaming fails (a proxy that
 * buffers, a dropped connection twice in a row) it falls back to polling every
 * five seconds rather than hammering reconnects.
 */
export function useLiveQuote(symbol: string) {
  const initial = useQuery({
    queryKey: ["chart-live", symbol],
    queryFn: () => api.get<LiveQuote>(`/stocks/${encodeURIComponent(symbol)}/live`),
    enabled: Boolean(symbol),
    staleTime: 2_000,
  });
  const [quote, setQuote] = useState<LiveQuote | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const failures = useRef(0);

  useEffect(() => { if (initial.data) setQuote(initial.data); }, [initial.data]);

  const marketOpen = initial.data?.market_open;
  useEffect(() => {
    if (!symbol || marketOpen === undefined) return;
    if (!marketOpen) { setStatus("closed"); return; }
    let source: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;
    failures.current = 0;

    const startPolling = () => {
      setStatus("polling");
      poll = setInterval(async () => {
        try {
          const q = await api.get<LiveQuote>(`/stocks/${encodeURIComponent(symbol)}/live`);
          if (!cancelled) setQuote(q);
          if (!q.market_open && poll) { clearInterval(poll); setStatus("closed"); }
        } catch {
          if (!cancelled) setStatus("offline");
        }
      }, 5_000);
    };

    if (typeof EventSource === "undefined") {
      startPolling();
    } else {
      setStatus("connecting");
      source = new EventSource(apiUrl(`/stocks/${encodeURIComponent(symbol)}/stream`));
      source.onmessage = (event) => {
        failures.current = 0;
        try {
          const q = JSON.parse(event.data) as LiveQuote;
          if (!cancelled) { setQuote(q); setStatus(q.market_open ? "live" : "closed"); }
        } catch { /* a malformed frame is skipped, the next one replaces it */ }
      };
      source.addEventListener("closed", () => {
        source?.close();
        if (!cancelled) setStatus("closed");
      });
      source.onerror = () => {
        failures.current += 1;
        if (failures.current >= 2) {
          source?.close();
          source = null;
          if (!cancelled) startPolling();
        } else if (!cancelled) {
          setStatus("connecting");                // EventSource retries once by itself
        }
      };
    }
    return () => {
      cancelled = true;
      source?.close();
      if (poll) clearInterval(poll);
    };
  }, [symbol, marketOpen]);

  return { quote: quote ?? initial.data ?? null, status, error: initial.error, isLoading: initial.isLoading };
}
