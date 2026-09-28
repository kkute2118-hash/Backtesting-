"use client";

import {
  createChart, CrosshairMode, LineStyle,
  type IChartApi, type IPriceLine, type ISeriesApi, type LogicalRange, type MouseEventParams,
  type Time, type UTCTimestamp,
} from "lightweight-charts";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef } from "react";

import { INTRADAY, TF_SECONDS, type LiveQuote, type Timeframe } from "./data";
import {
  bollinger, ema, macd, rsi, sma, supertrend, supportResistance, vwap,
  type Bar, type Series,
} from "./indicators";

// ------------------------------------------------------------------ config
export interface IndicatorConfig {
  volume: { on: boolean };
  sma: { on: boolean; period: number };
  ema: { on: boolean; period: number };
  vwap: { on: boolean; period: number };
  bb: { on: boolean; period: number; mult: number };
  supertrend: { on: boolean; period: number; mult: number };
  rsi: { on: boolean; period: number };
  macd: { on: boolean; fast: number; slow: number; signal: number };
}

export const DEFAULT_INDICATORS: IndicatorConfig = {
  volume: { on: true },
  sma: { on: false, period: 20 },
  ema: { on: true, period: 50 },
  vwap: { on: false, period: 20 },
  bb: { on: false, period: 20, mult: 2 },
  supertrend: { on: false, period: 10, mult: 3 },
  rsi: { on: false, period: 14 },
  macd: { on: false, fast: 12, slow: 26, signal: 9 },
};

export type DrawTool = "cursor" | "hline" | "trend" | "vline";

interface Drawing {
  id: string;
  kind: "hline" | "trend" | "vline";
  a: { time: number; price: number };
  b?: { time: number; price: number };
}

export interface TradingChartHandle {
  zoomIn(): void;
  zoomOut(): void;
  reset(): void;
  clearDrawings(): void;
}

const IST = 19_800;
const COLORS = {
  up: "#22c55e", down: "#ef4444", sma: "#f59e0b", ema: "#3b82f6", vwap: "#a855f7",
  bb: "#64748b", stUp: "#22c55e", stDown: "#ef4444", rsi: "#8b5cf6", macd: "#3b82f6",
  signal: "#f59e0b", draw: "#f59e0b", support: "#22c55e", resistance: "#ef4444",
};

const t = (sec: number) => sec as UTCTimestamp;

// ------------------------------------------------------------- live bars
/** Fold the live quote into the bar it belongs to (or a new one), for any timeframe. */
interface LiveState { key: string; cumVol: number | null; bar: Bar | null }

function mergeLive(server: Bar[], q: LiveQuote | null, tf: Timeframe, state: LiveState): Bar[] {
  if (!q || q.source !== "LIVE" || !server.length) return server;
  // Start from the live bar built so far, so its volume keeps accumulating when
  // an older page arrives and the server bars are re-merged.
  let bars = server;
  const kept = state.bar;
  const tail = server[server.length - 1];
  if (kept && kept.time >= tail.time) {
    bars = kept.time === tail.time ? [...server.slice(0, -1), kept] : [...server, kept];
  }
  const nowWall = Math.floor(Date.now() / 1000) + IST;
  const day = Math.floor(nowWall / 86_400) * 86_400;
  const last = bars[bars.length - 1];
  const ltp = q.ltp;
  let bucket: number;
  if (tf === "1D") bucket = day;
  else if (tf === "1W" || tf === "1M") {
    const d = new Date(last.time * 1000);
    const n = new Date(day * 1000);
    const same = tf === "1M"
      ? d.getUTCFullYear() === n.getUTCFullYear() && d.getUTCMonth() === n.getUTCMonth()
      : Math.floor((day / 86_400 + 3) / 7) === Math.floor((last.time / 86_400 + 3) / 7);   // weeks from Monday
    bucket = same ? last.time : day;
  } else {
    const open = day + 9 * 3600 + 15 * 60;
    if (nowWall < open) return bars;
    bucket = tf === "4H"
      ? (nowWall < day + 13 * 3600 + 15 * 60 ? open : day + 13 * 3600 + 15 * 60)
      : open + Math.floor((nowWall - open) / TF_SECONDS[tf]) * TF_SECONDS[tf];
  }
  const dayVol = q.volume ?? 0;
  const delta = state.cumVol === null ? 0 : Math.max(0, dayVol - state.cumVol);
  state.cumVol = dayVol;
  const out = bars.slice();
  if (last.time === bucket) {
    out[out.length - 1] = {
      ...last,
      high: Math.max(last.high, ltp, tf === "1D" && q.high ? q.high : ltp),
      low: Math.min(last.low, ltp, tf === "1D" && q.low ? q.low : ltp),
      close: ltp,
      volume: tf === "1D" && q.volume ? q.volume : last.volume + delta,
    };
  } else if (bucket > last.time) {
    out.push({
      time: bucket,
      open: tf === "1D" && q.open ? q.open : ltp,
      high: tf === "1D" && q.high ? q.high : ltp,
      low: tf === "1D" && q.low ? q.low : ltp,
      close: ltp,
      volume: tf === "1D" && q.volume ? q.volume : delta,
    });
  }
  state.bar = out[out.length - 1];
  return out;
}

// ------------------------------------------------------------ component
interface Props {
  symbol: string;
  tf: Timeframe;
  bars: Bar[];
  live: LiveQuote | null;
  indicators: IndicatorConfig;
  tool: DrawTool;
  showLevels: boolean;
  dark: boolean;
  hasMore: boolean;
  loadingOlder: boolean;
  onNeedOlder(): void;
  onToolDone(): void;
}

export const TradingChart = forwardRef<TradingChartHandle, Props>(function TradingChart(
  { symbol, tf, bars, live, indicators, tool, showLevels, dark, hasMore, loadingOlder, onNeedOlder, onToolDone },
  ref,
) {
  const mainEl = useRef<HTMLDivElement>(null);
  const rsiEl = useRef<HTMLDivElement>(null);
  const macdEl = useRef<HTMLDivElement>(null);
  const svgEl = useRef<SVGSVGElement>(null);
  const legendEl = useRef<HTMLDivElement>(null);

  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlays = useRef<Record<string, ISeriesApi<"Line">>>({});
  const rsiChart = useRef<IChartApi | null>(null);
  const rsiSeries = useRef<ISeriesApi<"Line"> | null>(null);
  const macdChart = useRef<IChartApi | null>(null);
  const macdSeries = useRef<{ line: ISeriesApi<"Line">; signal: ISeriesApi<"Line">; hist: ISeriesApi<"Histogram"> } | null>(null);
  const levelLines = useRef<IPriceLine[]>([]);
  const drawLines = useRef<Record<string, IPriceLine>>({});

  const shown = useRef<Bar[]>([]);               // what the chart currently holds, live bar included
  const liveState = useRef<LiveState>({ key: "", cumVol: null, bar: null });
  const pending = useRef<{ time: number; price: number } | null>(null);
  const moreRef = useRef({ hasMore, loadingOlder, onNeedOlder });
  moreRef.current = { hasMore, loadingOlder, onNeedOlder };
  const toolRef = useRef({ tool, onToolDone });
  toolRef.current = { tool, onToolDone };

  const storageKey = `chart-drawings:${symbol}`;
  const drawings = useRef<Drawing[]>([]);

  const intraday = INTRADAY.has(tf);
  const merged = useMemo(() => {
    const key = `${symbol}|${tf}`;
    if (liveState.current.key !== key) liveState.current = { key, cumVol: null, bar: null };
    return mergeLive(bars, live, tf, liveState.current);
  }, [bars, live, tf, symbol]);

  // ----------------------------------------------------- create the charts
  useEffect(() => {
    const el = mainEl.current;
    if (!el) return;
    const text = dark ? "#9aa5b6" : "#5b6474";
    const grid = dark ? "rgba(42,50,66,0.6)" : "rgba(227,232,239,0.9)";
    const base = {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: text, fontFamily: "var(--font-sans)", fontSize: 11 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: intraday, secondsVisible: false, rightOffset: 6 },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, pinch: true, mouseWheel: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    } as const;
    const c = createChart(el, base);
    chart.current = c;
    candles.current = c.addCandlestickSeries({
      upColor: COLORS.up, downColor: COLORS.down, borderUpColor: COLORS.up, borderDownColor: COLORS.down,
      wickUpColor: COLORS.up, wickDownColor: COLORS.down,
    });
    c.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });

    const onRange = (range: LogicalRange | null) => {
      const m = moreRef.current;
      if (range && range.from < 15 && m.hasMore && !m.loadingOlder) m.onNeedOlder();
      redrawSvg();
    };
    c.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    c.subscribeCrosshairMove(onCrosshair);
    // A native listener rather than subscribeClick: the library folds two
    // quick clicks into a double-click and drops the second, which loses the
    // end point of a trend line drawn at speed.
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const onUp = (e: PointerEvent) => {
      const start = down;
      down = null;
      if (!start || Math.hypot(e.clientX - start.x, e.clientY - start.y) > 5) return;   // a drag pans
      const r = el.getBoundingClientRect();
      onClick(e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    const ro = new ResizeObserver(() => redrawSvg());
    ro.observe(el);
    return () => {
      ro.disconnect();
      c.unsubscribeCrosshairMove(onCrosshair);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      c.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      c.remove();
      chart.current = null;
      candles.current = null;
      volume.current = null;
      overlays.current = {};
      levelLines.current = [];
      drawLines.current = {};
      shown.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, intraday, symbol, tf]);

  // ----------------------------------------------- oscillator panes (lazy)
  const makePane = useCallback((el: HTMLDivElement) => {
    const text = dark ? "#9aa5b6" : "#5b6474";
    const grid = dark ? "rgba(42,50,66,0.6)" : "rgba(227,232,239,0.9)";
    const p = createChart(el, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: text, fontSize: 10, fontFamily: "var(--font-sans)" },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal, horzLine: { visible: false, labelVisible: false } },
      rightPriceScale: { borderColor: grid, minimumWidth: 64 },
      timeScale: { visible: false, rightOffset: 6 },
      handleScroll: false,
      handleScale: false,
    });
    return p;
  }, [dark]);

  useEffect(() => {
    if (!indicators.rsi.on || !rsiEl.current) return;
    const p = makePane(rsiEl.current);
    rsiChart.current = p;
    rsiSeries.current = p.addLineSeries({ color: COLORS.rsi, lineWidth: 1, priceLineVisible: false });
    rsiSeries.current.createPriceLine({ price: 70, color: "#64748b", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    rsiSeries.current.createPriceLine({ price: 30, color: "#64748b", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    syncPane(p);
    return () => { p.remove(); rsiChart.current = null; rsiSeries.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indicators.rsi.on, makePane, symbol, tf]);

  useEffect(() => {
    if (!indicators.macd.on || !macdEl.current) return;
    const p = makePane(macdEl.current);
    macdChart.current = p;
    macdSeries.current = {
      hist: p.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false }),
      line: p.addLineSeries({ color: COLORS.macd, lineWidth: 1, priceLineVisible: false }),
      signal: p.addLineSeries({ color: COLORS.signal, lineWidth: 1, priceLineVisible: false }),
    };
    syncPane(p);
    return () => { p.remove(); macdChart.current = null; macdSeries.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indicators.macd.on, makePane, symbol, tf]);

  function syncPane(p: IChartApi) {
    const c = chart.current;
    if (!c) return;
    const range = c.timeScale().getVisibleLogicalRange();
    if (range) p.timeScale().setVisibleLogicalRange(range);
    c.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (r) {
        try { p.timeScale().setVisibleLogicalRange(r); } catch { /* pane already removed */ }
      }
    });
  }

  // ------------------------------------------------------------ the data
  useEffect(() => {
    const c = chart.current;
    const cs = candles.current;
    if (!c || !cs) return;
    const prev = shown.current;
    const data = merged;
    const firstLoad = prev.length === 0;
    const prepended = !firstLoad && data.length > prev.length && data[0].time < prev[0].time;
    const onlyLastChanged = !firstLoad && !prepended && data.length >= prev.length
      && data.length - prev.length <= 1 && prev.length > 0 && data[prev.length - 1]?.time === prev[prev.length - 1].time;

    if (onlyLastChanged) {
      // A live tick: touch only the newest bar of every series.
      const b = data[data.length - 1];
      cs.update({ time: t(b.time), open: b.open, high: b.high, low: b.low, close: b.close });
      volume.current?.update({ time: t(b.time), value: b.volume, color: volColor(b) });
      shown.current = data;
      paintIndicators(data, true);
      updateLegend(null);
      return;
    }

    const range = c.timeScale().getVisibleLogicalRange();
    cs.setData(data.map((b) => ({ time: t(b.time), open: b.open, high: b.high, low: b.low, close: b.close })));
    shown.current = data;
    paintVolume(data);
    paintIndicators(data, false);
    paintLevels(data);
    if (firstLoad && data.length) {
      c.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.length - 150), to: data.length + 5 });
    } else if (prepended && range) {
      const added = data.length - prev.length;
      c.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added });
    }
    loadDrawings();
    updateLegend(null);
    // A rebuilt chart (theme, symbol or timeframe) starts empty: repaint then too.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [merged, dark, intraday, symbol, tf]);

  // Indicator settings changed: repaint from the bars already on the chart.
  useEffect(() => {
    if (!shown.current.length) return;
    paintVolume(shown.current);
    paintIndicators(shown.current, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [indicators]);

  useEffect(() => { paintLevels(shown.current); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [showLevels]);

  const volColor = (b: Bar) => (b.close >= b.open ? "rgba(34,197,94,0.35)" : "rgba(239,68,68,0.35)");

  function paintVolume(data: Bar[]) {
    const c = chart.current;
    if (!c) return;
    if (!indicators.volume.on) {
      if (volume.current) { c.removeSeries(volume.current); volume.current = null; }
      c.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.06 } });
      return;
    }
    if (!volume.current) {
      volume.current = c.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", priceLineVisible: false, lastValueVisible: false });
      c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      c.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
    }
    volume.current.setData(data.map((b) => ({ time: t(b.time), value: b.volume, color: volColor(b) })));
  }

  function lineSeries(key: string, color: string, width = 1, style: LineStyle = LineStyle.Solid) {
    const c = chart.current!;
    if (!overlays.current[key]) {
      overlays.current[key] = c.addLineSeries({ color, lineWidth: width as 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    }
    return overlays.current[key];
  }
  function dropSeries(key: string) {
    const s = overlays.current[key];
    if (s && chart.current) chart.current.removeSeries(s);
    delete overlays.current[key];
  }
  function put(s: ISeriesApi<"Line"> | ISeriesApi<"Histogram"> | null | undefined, values: Series, data: Bar[], lastOnly: boolean, colorOf?: (i: number) => string) {
    if (!s) return;
    if (lastOnly) {
      const i = data.length - 1;
      const v = values[i];
      if (v !== null && Number.isFinite(v)) s.update({ time: t(data[i].time), value: v, ...(colorOf ? { color: colorOf(i) } : {}) });
      return;
    }
    s.setData(values.flatMap((v, i) => (v === null || !Number.isFinite(v) ? [] : [{ time: t(data[i].time), value: v, ...(colorOf ? { color: colorOf(i) } : {}) }])));
  }

  function paintIndicators(data: Bar[], lastOnly: boolean) {
    if (!chart.current || !data.length) return;
    const close = data.map((b) => b.close);
    const cfg = indicators;
    if (cfg.sma.on) put(lineSeries("sma", COLORS.sma), sma(close, cfg.sma.period), data, lastOnly); else dropSeries("sma");
    if (cfg.ema.on) put(lineSeries("ema", COLORS.ema), ema(close, cfg.ema.period), data, lastOnly); else dropSeries("ema");
    if (cfg.vwap.on) put(lineSeries("vwap", COLORS.vwap, 1, LineStyle.Dotted), vwap(data, intraday, cfg.vwap.period), data, lastOnly); else dropSeries("vwap");
    if (cfg.bb.on) {
      const b = bollinger(close, cfg.bb.period, cfg.bb.mult);
      put(lineSeries("bbU", COLORS.bb, 1, LineStyle.Dashed), b.upper, data, lastOnly);
      put(lineSeries("bbM", COLORS.bb), b.mid, data, lastOnly);
      put(lineSeries("bbL", COLORS.bb, 1, LineStyle.Dashed), b.lower, data, lastOnly);
    } else { dropSeries("bbU"); dropSeries("bbM"); dropSeries("bbL"); }
    if (cfg.supertrend.on) {
      const st = supertrend(data, cfg.supertrend.period, cfg.supertrend.mult);
      // One series, coloured per point: green below price in an uptrend, red above it in a downtrend.
      const s = lineSeries("st", COLORS.stUp, 2);
      if (lastOnly) {
        const i = data.length - 1;
        if (st.line[i] !== null) s.update({ time: t(data[i].time), value: st.line[i] as number, color: st.up[i] ? COLORS.stUp : COLORS.stDown });
      } else {
        s.setData(st.line.flatMap((v, i) => (v === null ? [] : [{ time: t(data[i].time), value: v, color: st.up[i] ? COLORS.stUp : COLORS.stDown }])));
      }
    } else dropSeries("st");
    if (cfg.rsi.on) put(rsiSeries.current, rsi(close, cfg.rsi.period), data, lastOnly);
    if (cfg.macd.on && macdSeries.current) {
      const m = macd(close, cfg.macd.fast, cfg.macd.slow, cfg.macd.signal);
      put(macdSeries.current.line, m.line, data, lastOnly);
      put(macdSeries.current.signal, m.signal, data, lastOnly);
      put(macdSeries.current.hist, m.hist, data, lastOnly, (i) => ((m.hist[i] ?? 0) >= 0 ? "rgba(34,197,94,0.55)" : "rgba(239,68,68,0.55)"));
    }
  }

  function paintLevels(data: Bar[]) {
    const cs = candles.current;
    if (!cs) return;
    levelLines.current.forEach((l) => cs.removePriceLine(l));
    levelLines.current = [];
    if (!showLevels || data.length < 20) return;
    for (const lvl of supportResistance(data.slice(-400))) {
      levelLines.current.push(cs.createPriceLine({
        price: lvl.price, color: lvl.kind === "support" ? COLORS.support : COLORS.resistance,
        lineWidth: 1, lineStyle: LineStyle.LargeDashed, axisLabelVisible: true,
        title: lvl.kind === "support" ? "S" : "R",
      }));
    }
  }

  // ------------------------------------------------------ legend / tooltip
  function fmtTime(sec: number) {
    const d = new Date(sec * 1000);
    const date = d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
    return intraday ? `${date} ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" })}` : date;
  }
  function updateLegend(param: MouseEventParams | null) {
    const el = legendEl.current;
    const data = shown.current;
    if (!el || !data.length) return;
    let bar: Bar | undefined;
    if (param?.time !== undefined && candles.current) {
      const time = param.time as number;
      bar = data.find((b) => b.time === time);
    }
    bar = bar ?? data[data.length - 1];
    const i = data.indexOf(bar);
    const prevClose = i > 0 ? data[i - 1].close : bar.open;
    const chg = bar.close - prevClose;
    const pct = prevClose ? (chg / prevClose) * 100 : 0;
    const dir = chg >= 0 ? "text-up" : "text-down";
    const num = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const vol = bar.volume >= 1e7 ? `${(bar.volume / 1e7).toFixed(2)} Cr` : bar.volume >= 1e5 ? `${(bar.volume / 1e5).toFixed(2)} L` : Math.round(bar.volume).toLocaleString("en-IN");
    el.innerHTML =
      `<span class="text-faint">${fmtTime(bar.time)}</span>` +
      `<span>O <b>${num(bar.open)}</b></span><span>H <b>${num(bar.high)}</b></span>` +
      `<span>L <b>${num(bar.low)}</b></span><span>C <b class="${dir}">${num(bar.close)}</b></span>` +
      `<span class="${dir}">${chg >= 0 ? "+" : ""}${num(chg)} (${chg >= 0 ? "+" : ""}${pct.toFixed(2)}%)</span>` +
      `<span>Vol <b>${vol}</b></span>`;
  }
  function onCrosshair(param: MouseEventParams) {
    updateLegend(param);
    const time = param.time;
    for (const [p, s] of [[rsiChart.current, rsiSeries.current], [macdChart.current, macdSeries.current?.line]] as const) {
      if (!p || !s) continue;
      try {
        if (time === undefined) p.clearCrosshairPosition();
        else p.setCrosshairPosition(0, time as Time, s);
      } catch { /* pane closing */ }
    }
  }

  // --------------------------------------------------------------- drawings
  function saveDrawings() {
    try { localStorage.setItem(storageKey, JSON.stringify(drawings.current)); } catch { /* storage off */ }
  }
  function loadDrawings() {
    try {
      const raw = localStorage.getItem(storageKey);
      drawings.current = raw ? (JSON.parse(raw) as Drawing[]) : [];
    } catch { drawings.current = []; }
    syncHLines();
    redrawSvg();
  }
  function syncHLines() {
    const cs = candles.current;
    if (!cs) return;
    for (const id of Object.keys(drawLines.current)) {
      if (!drawings.current.some((d) => d.id === id)) { cs.removePriceLine(drawLines.current[id]); delete drawLines.current[id]; }
    }
    for (const d of drawings.current) {
      if (d.kind === "hline" && !drawLines.current[d.id]) {
        drawLines.current[d.id] = cs.createPriceLine({ price: d.a.price, color: COLORS.draw, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "" });
      }
    }
  }
  function onClick(px: number, py: number) {
    const { tool: current, onToolDone: done } = toolRef.current;
    const cs = candles.current;
    const c = chart.current;
    if (current === "cursor" || !cs || !c) return;
    if (px > c.timeScale().width() || py > (c.paneSize().height ?? 0)) return;        // the axes, not the plot
    const price = cs.coordinateToPrice(py);
    const time = (c.timeScale().coordinateToTime(px) as number | null) ?? shown.current[shown.current.length - 1]?.time;
    if (price === null || time === undefined) return;
    const at = { time, price };
    const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    if (current === "hline") drawings.current.push({ id, kind: "hline", a: at });
    else if (current === "vline") drawings.current.push({ id, kind: "vline", a: at });
    else if (current === "trend") {
      if (!pending.current) { pending.current = at; redrawSvg(); return; }
      drawings.current.push({ id, kind: "trend", a: pending.current, b: at });
      pending.current = null;
    }
    saveDrawings();
    syncHLines();
    redrawSvg();
    done();
  }
  function redrawSvg() {
    const svg = svgEl.current;
    const c = chart.current;
    const cs = candles.current;
    if (!svg || !c || !cs) return;
    const x = (time: number) => c.timeScale().timeToCoordinate(t(time));
    const y = (price: number) => cs.priceToCoordinate(price);
    const h = svg.clientHeight;
    const parts: string[] = [];
    for (const d of drawings.current) {
      if (d.kind === "vline") {
        const xx = x(d.a.time);
        if (xx !== null) parts.push(`<line x1="${xx}" x2="${xx}" y1="0" y2="${h}" stroke="${COLORS.draw}" stroke-width="1"/>`);
      } else if (d.kind === "trend" && d.b) {
        const [x1, y1, x2, y2] = [x(d.a.time), y(d.a.price), x(d.b.time), y(d.b.price)];
        if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
          parts.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${COLORS.draw}" stroke-width="1.5"/>`);
          parts.push(`<circle cx="${x1}" cy="${y1}" r="3" fill="${COLORS.draw}"/><circle cx="${x2}" cy="${y2}" r="3" fill="${COLORS.draw}"/>`);
        }
      }
    }
    if (pending.current) {
      const [px, py] = [x(pending.current.time), y(pending.current.price)];
      if (px !== null && py !== null) parts.push(`<circle cx="${px}" cy="${py}" r="4" fill="none" stroke="${COLORS.draw}" stroke-width="1.5"/>`);
    }
    svg.innerHTML = parts.join("");
  }

  // Redraw drawings when the price scale moves too (autoscale on scroll).
  useEffect(() => {
    let raf = 0;
    const loop = () => { redrawSvg(); raf = requestAnimationFrame(loop); };
    if (drawings.current.some((d) => d.kind !== "hline") || pending.current) raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  });

  // --------------------------------------------------------------- handle
  useImperativeHandle(ref, () => ({
    zoomIn() {
      const ts = chart.current?.timeScale();
      const r = ts?.getVisibleLogicalRange();
      if (ts && r) { const span = (r.to - r.from) * 0.3; ts.setVisibleLogicalRange({ from: r.from + span, to: r.to }); }
    },
    zoomOut() {
      const ts = chart.current?.timeScale();
      const r = ts?.getVisibleLogicalRange();
      if (ts && r) { const span = (r.to - r.from) * 0.5; ts.setVisibleLogicalRange({ from: r.from - span, to: r.to }); }
    },
    reset() {
      const n = shown.current.length;
      chart.current?.priceScale("right").applyOptions({ autoScale: true });
      chart.current?.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 5 });
    },
    clearDrawings() {
      drawings.current = [];
      pending.current = null;
      saveDrawings();
      syncHLines();
      redrawSvg();
    },
  }));

  const paneLabel = "absolute left-2 top-1 z-10 text-2xs text-faint pointer-events-none";
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1" style={{ cursor: tool === "cursor" ? "default" : "crosshair" }}>
        <div ref={legendEl} data-testid="chart-legend"
          className="pointer-events-none absolute left-2 top-1 z-10 flex flex-wrap gap-x-3 gap-y-0.5 pr-20 text-2xs tabular text-muted" />
        <div ref={mainEl} className="absolute inset-0" data-testid="chart-main" />
        <svg ref={svgEl} className="pointer-events-none absolute inset-0 z-[5] h-full w-full" aria-hidden />
        {loadingOlder ? (
          <span className="absolute bottom-2 left-2 z-10 rounded bg-elevated px-2 py-0.5 text-2xs text-muted">Loading older bars…</span>
        ) : null}
      </div>
      {indicators.rsi.on ? (
        <div className="relative h-24 shrink-0 border-t border-line sm:h-28">
          <span className={paneLabel}>RSI {indicators.rsi.period}</span>
          <div ref={rsiEl} className="absolute inset-0" />
        </div>
      ) : null}
      {indicators.macd.on ? (
        <div className="relative h-24 shrink-0 border-t border-line sm:h-28">
          <span className={paneLabel}>MACD {indicators.macd.fast} {indicators.macd.slow} {indicators.macd.signal}</span>
          <div ref={macdEl} className="absolute inset-0" />
        </div>
      ) : null}
    </div>
  );
});
