"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";

import type { Bar } from "./indicators";

/** Only what a daily swing trader uses: 15m and 1H to time an entry, 1D and 1W to read the trend. */
export const TIMEFRAMES = ["15m", "1H", "1D", "1W"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];
export const INTRADAY: ReadonlySet<Timeframe> = new Set(["15m", "1H"]);
export const TF_SECONDS: Record<Timeframe, number> = { "15m": 900, "1H": 3600, "1D": 86400, "1W": 604800 };

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
    staleTime: INTRADAY.has(tf) ? 60_000 : 10 * 60_000,
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

export type LiveStatus = "connecting" | "live" | "closed" | "paused" | "offline";

const POLL_MS = 5_000;

/**
 * The live quote for one symbol. Fetched once; then, only while the market is
 * open AND the chart is on screen, asked for again every five seconds. The
 * server shares one Dhan quote per symbol among all viewers, and nothing is
 * held open between polls, so an idle or hidden chart costs nothing.
 */
export function useLiveQuote(symbol: string) {
  const [visible, setVisible] = useState(() => typeof document === "undefined" || !document.hidden);
  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const first = useQuery({
    queryKey: ["chart-live", symbol],
    queryFn: () => api.get<LiveQuote>(`/stocks/${encodeURIComponent(symbol)}/live`),
    enabled: Boolean(symbol),
    staleTime: POLL_MS,
    // Poll only while trading is on and someone is looking; stop at the close.
    refetchInterval: (q) => (q.state.data?.market_open && visible ? POLL_MS : false),
    refetchIntervalInBackground: false,
  });

  const data = first.data;
  let status: LiveStatus;
  if (first.isLoading) status = "connecting";
  else if (first.isError && !data) status = "offline";
  else if (!data?.market_open) status = "closed";
  else if (first.isError) status = "offline";
  else if (!visible) status = "paused";
  else status = data.source === "LIVE" ? "live" : "closed";

  return { quote: data ?? null, status, error: first.error, isLoading: first.isLoading };
}
