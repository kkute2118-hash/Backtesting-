"use client";

import dynamic from "next/dynamic";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// The chart code (lightweight-charts, indicators) loads the first time a chart
// is opened, not with every page.
const ChartPanel = dynamic(() => import("./ChartPanel").then((m) => m.ChartPanel), {
  ssr: false,
  loading: () => (
    <div className="fixed inset-0 z-50 grid place-items-center bg-canvas/80 text-xs text-muted">Opening chart…</div>
  ),
});

const SYMBOL_RE = /^[A-Z0-9&_-]{1,30}$/;
const ChartContext = createContext<((symbol: string) => void) | null>(null);

/** Opens the chart for a symbol, or null outside the provider. */
export function useOpenChart() {
  return useContext(ChartContext);
}

function readParam(): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get("chart");
  const sym = value ? value.toUpperCase() : null;
  return sym && SYMBOL_RE.test(sym) ? sym : null;
}

function withParam(symbol: string | null) {
  const url = new URL(window.location.href);
  if (symbol) url.searchParams.set("chart", symbol);
  else url.searchParams.delete("chart");
  return url.toString();
}

/**
 * One chart panel for the whole app. Any stock name calls `useOpenChart()`;
 * the open symbol lives in the URL (?chart=RELIANCE), so a chart can be linked
 * and the phone's back button closes it.
 */
export function ChartProvider({ children }: { children: ReactNode }) {
  const [symbol, setSymbol] = useState<string | null>(null);
  const pushed = useRef(false);

  useEffect(() => {
    setSymbol(readParam());
    const onPop = () => { pushed.current = false; setSymbol(readParam()); };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = useCallback((raw: string) => {
    const sym = String(raw).toUpperCase().replace(/\.NS$/, "").trim();
    if (!SYMBOL_RE.test(sym)) return;
    if (readParam()) window.history.replaceState(window.history.state, "", withParam(sym));
    else { window.history.pushState(window.history.state, "", withParam(sym)); pushed.current = true; }
    setSymbol(sym);
  }, []);

  const close = useCallback(() => {
    if (pushed.current) { pushed.current = false; window.history.back(); }
    else window.history.replaceState(window.history.state, "", withParam(null));
    setSymbol(null);
  }, []);

  return (
    <ChartContext.Provider value={open}>
      {children}
      {symbol ? <ChartPanel key={symbol} symbol={symbol} onClose={close} /> : null}
    </ChartContext.Provider>
  );
}
