"""Live paper trading of the 4-hour trend strategy on the Oracle server
(research/fx_crypto/STEP5_DAILY_TREND.md, scripts/trend_4h_study.py).

Rules (frozen; changing them restarts the paper book):
  markets   BTC, ETH, SOL, BNB, XRP and gold, as Binance USD-M perpetuals
  signal    a 4h close above the highest high of the previous 55 4h bars,
            with the last completed daily close above its 200-day average
  entry     market buy at the next 15-minute open after the 4h close (switched
            from a limit at the broken high on 5 Oct 2026, at the owner's
            request: +0.83R / +0.57R a trade against +0.96R / +0.38R)
  stop      2 ATR(4h, 20) below the entry
  exit      a 4h close below the lowest low of the previous 20 4h bars, at the
            next 15-minute open; or the stop
  charges   taker 0.05% + 18% GST + 0.01% slippage on the entry and the exit,
            funding 0.01% per 8 hours held
  account   Rs 10,000 paper, compounding: 2% of equity risked a trade,
            position at most 5x equity (research/fx_crypto/STEP9_SIZING.md)

Runs every 5 minutes (deploy/oracle/update.sh, ati-lab-trend.timer). Each
run reads only completed candles and moves each market's state forward bar by
bar from where the last run stopped, so a missed run catches up. Writes
REPORT_DIR/trend-state.json (the book), trend-latest.json and trend.html
(served behind the site login at /reports/trend.html).

Data: Binance futures public candles (the exact instruments, no key). If
Binance refuses the server's region, crypto falls back to Binance's spot
market-data host and gold to Yahoo Finance (GC=F, the source yfinance uses).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from datetime import timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

REPORT_DIR = Path(os.environ.get("REPORT_DIR", "/data/reports"))
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "XAUUSDT")
YAHOO = {"XAUUSDT": "GC=F", "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD",
         "BNBUSDT": "BNB-USD", "XRPUSDT": "XRP-USD"}
N_IN, N_OUT, ATR_N, STOP_ATR = 55, 20, 20, 2.0
TAKER = 0.0005 * 1.18 + 0.0001
FUNDING_PER_15M = 0.0001 / 32
START_EQUITY, RISK, MAX_POSITION_X = 10_000.0, 0.02, 5.0
UA = {"User-Agent": "Mozilla/5.0 (ATI Lab paper trading)"}
NTFY = os.environ.get("NTFY_SERVER", "https://ntfy.sh")


# ------------------------------------------------------------------ data
def _binance(host, path, sym, interval, limit):
    r = requests.get(f"{host}{path}", params={"symbol": sym, "interval": interval, "limit": limit},
                     headers=UA, timeout=30)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame(rows, columns=range(len(rows[0])))[[0, 1, 2, 3, 4]]
    df.columns = ["time", "open", "high", "low", "close"]
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.set_index("time").astype(float)


def _yahoo(sym, interval, rng):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO[sym]}",
                     params={"interval": interval, "range": rng}, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")},
                      index=pd.to_datetime(res["timestamp"], unit="s", utc=True)).dropna()
    return df


def _resample(df, rule):
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def fetch(sym):
    """(daily, 4h, 15m, source) of completed candles only."""
    errors = []
    sources = [("binance futures", "https://fapi.binance.com", "/fapi/v1/klines")]
    if sym != "XAUUSDT":
        sources.append(("binance spot", "https://data-api.binance.vision", "/api/v3/klines"))
    for name, host, path in sources:
        try:
            d1 = _binance(host, path, sym, "1d", 260)
            h4 = _binance(host, path, sym, "4h", 300)
            m15 = _binance(host, path, sym, "15m", 1000)     # ~10 days to catch up after downtime
            return _complete(d1, "1D"), _complete(h4, "4h"), _complete(m15, "15min"), name
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__} {exc}"[:150])
    try:                                                   # Yahoo: 1h -> 4h, 15m, daily
        d1 = _yahoo(sym, "1d", "2y")
        h4 = _resample(_yahoo(sym, "1h", "60d"), "4h")
        m15 = _yahoo(sym, "15m", "5d")
        return _complete(d1, "1D"), _complete(h4, "4h"), _complete(m15, "15min"), "yahoo finance"
    except Exception as exc:
        errors.append(f"yahoo: {type(exc).__name__} {exc}"[:150])
    raise RuntimeError("; ".join(errors))


def _complete(df, rule):
    now = pd.Timestamp.now(tz="UTC")
    return df[df.index + pd.Timedelta(rule) <= now]


# ------------------------------------------------------------- strategy
def indicators(d1, h4):
    hh = h4.high.rolling(N_IN).max().shift()
    ll = h4.low.rolling(N_OUT).min().shift()
    tr = np.maximum(h4.high - h4.low, np.maximum(abs(h4.high - h4.close.shift()), abs(h4.low - h4.close.shift())))
    atr = tr.rolling(ATR_N).mean()
    trend_day = (d1.close > d1.close.rolling(200).mean())            # by day, known at that day's close
    trend = trend_day.shift(1).astype(float).reindex(h4.index.floor("1D")).fillna(0.0).to_numpy() > 0
    return pd.DataFrame({"hh": hh, "ll": ll, "atr": atr, "close": h4.close, "trend": trend}, index=h4.index)


def advance(st: dict, ind: pd.DataFrame, m15: pd.DataFrame, sym: str) -> list[str]:
    """Move one market's state over the 15m bars after st['last15']. Returns
    event lines. Pure apart from mutating st."""
    events = []
    last = pd.Timestamp(st["last15"]) if st.get("last15") else m15.index[-1]
    bars = m15[m15.index > last]
    if not st.get("last15"):
        # first run: start flat, but take a signal from the latest 4h close
        st.update(status="flat")
        bars = m15.iloc[-1:]
    for ts, b in bars.iterrows():
        status = st.get("status", "flat")
        if status == "exit_next":
            _close(st, b.open, ts, "trend exit", events, sym)
            status = st["status"]
        if status == "pending":                      # a resting limit from before the switch
            events.append(f"{sym}: buy limit {st['level']:.6g} cancelled (strategy now enters at market)")
            st.update(status="flat")
        if status == "enter_next":
            entry = float(b.open)
            stop = entry - STOP_ATR * st["atr"]
            st.update(status="long", entry=entry, stop=stop, entry_time=str(ts), held15=0,
                      size_x=round(min(RISK / ((entry - stop) / entry), MAX_POSITION_X), 3))
            events.append(f"{sym}: BOUGHT at {entry:.6g} (market), stop {stop:.6g}")
        if st.get("status") == "long":
            st["held15"] = st.get("held15", 0) + 1
            if b.low <= st["stop"]:
                _close(st, min(b.open, st["stop"]), ts, "stop", events, sym)
        # does this 15m bar close a 4h bar?
        end = ts + pd.Timedelta(minutes=15)
        if end.hour % 4 == 0 and end.minute == 0:
            j = end - pd.Timedelta(hours=4)
            if j in ind.index:
                r = ind.loc[j]
                if st.get("status") == "long" and np.isfinite(r.ll) and r.close < r.ll:
                    st["status"] = "exit_next"
                    events.append(f"{sym}: 4h close {r.close:.6g} below the 20-bar low {r.ll:.6g}: sell at the next open")
                elif (st.get("status") == "flat" and r.trend and np.isfinite(r.hh)
                      and np.isfinite(r.atr) and r.close > r.hh):
                    st.update(status="enter_next", level=float(r.hh), atr=float(r.atr), signal_time=str(j),
                              signal_close=float(r.close))
                    events.append(f"{sym}: BREAKOUT, 4h close {r.close:.6g} above the 55-bar high {r.hh:.6g}. "
                                  f"Buy at market now, stop about {r.close - STOP_ATR * r.atr:.6g}")
        st["last15"] = str(ts)
    return events


def _close(st, px, ts, why, events, sym):
    entry, stop = st["entry"], st["stop"]
    risk = entry - stop
    cost = TAKER * entry + TAKER * px + FUNDING_PER_15M * st.get("held15", 0) * entry
    r = (px - entry - cost) / risk
    st.setdefault("closed", []).append({"symbol": sym, "entry_time": st["entry_time"], "exit_time": str(ts),
                                        "entry": entry, "stop": stop, "exit": float(px), "why": why, "r": round(r, 3),
                                        "ret": round((px - entry - cost) / entry, 6),
                                        "size_x": st.get("size_x", min(RISK / (risk / entry), MAX_POSITION_X))})
    events.append(f"{sym}: SOLD at {px:.6g} ({why}), {r:+.2f}R after charges")
    st.update(status="flat")
    for k in ("entry", "stop", "entry_time", "held15", "level", "atr", "expires", "signal_time",
              "signal_close", "size_x"):
        st.pop(k, None)


# ---------------------------------------------------------- phone alerts
def notify(topic: str, title: str, body: str, high: bool = False) -> bool:
    """Push to the ntfy app on the owner's phone (subscribed to `topic`).
    Never raises: a failed alert must not stop the book."""
    try:
        r = requests.post(f"{NTFY}/{topic}", data=body.encode("utf-8"), timeout=15, headers={
            "Title": title.encode("ascii", "ignore").decode(), "Priority": "high" if high else "default",
            "Tags": "chart_with_upwards_trend" if high else "information_source"})
        return r.ok
    except Exception:
        return False


def alert_text(sym: str, event: str, st: dict, equity: float) -> tuple[str, str, bool]:
    """(title, body, urgent) for one event, with the order to place."""
    name = sym.replace("USDT", "")
    if "BREAKOUT" in event and st.get("status") in ("enter_next", "long"):
        px = st.get("entry", st.get("signal_close"))
        stop_dist = STOP_ATR * st["atr"]
        stop = px - stop_dist
        size_x = min(RISK / (stop_dist / px), MAX_POSITION_X)
        qty_note = (f"Size for Rs {equity:,.0f} (2% risk = Rs {equity * RISK:,.0f}): position value "
                    f"Rs {equity * size_x:,.0f}, leverage {size_x:.1f}x.")
        return (f"{name}: BUY NOW at market ~{px:.6g}",
                f"4h breakout on {name}USDT perp.\nBUY AT MARKET now (about {px:.6g})\nSTOP {stop:.6g} "
                f"({stop_dist / px:.1%} below)\n{qty_note}\n"
                f"Exit rule: sell after a 4h close below the 20-bar low (you will get an alert).", True)
    if "BOUGHT" in event:
        return f"{name}: entry recorded", event + "\nPut the stop order on the exchange now.", False
    if "below the 20-bar low" in event:
        return f"{name}: SELL now", event + "\nClose the position at market now.", True
    if "SOLD" in event:
        return f"{name}: position closed", event, False
    if "expired" in event:
        return f"{name}: cancel the buy limit", event, False
    return f"{name}", event, False


# --------------------------------------------------------------- report
def _equity(trades):
    eq = START_EQUITY
    for t in sorted(trades, key=lambda t: t["exit_time"]):
        if "ret" in t:                      # position of size_x times equity, return after charges
            eq += eq * t["size_x"] * t["ret"]
        else:                               # trades from before the switch: 1% risk
            eq += eq * 0.01 * t["r"]
    return eq


def write_report(book, now, events, sources):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades = [t for s in book["markets"].values() for t in s.get("closed", [])]
    eq = _equity(trades)
    rs = [t["r"] for t in trades]
    summary = {"updated": now.isoformat(timespec="minutes"), "paper_start": book["start"],
               "equity": round(eq, 2), "trades": len(trades), "total_r": round(sum(rs), 2),
               "markets": {k: {kk: v for kk, v in s.items() if kk != "closed"} for k, s in book["markets"].items()},
               "recent_events": book.get("events", [])[-40:], "sources": sources}
    (REPORT_DIR / "trend-latest.json").write_text(json.dumps(summary, indent=1, default=str))
    ist = lambda x: pd.Timestamp(x).tz_convert("Asia/Kolkata").strftime("%d %b %H:%M")  # noqa: E731
    rows = []
    for sym, s in book["markets"].items():
        st = s.get("status", "flat")
        if st == "long":
            info = f"LONG from {s['entry']:.6g}, stop {s['stop']:.6g}, since {ist(s['entry_time'])}"
        elif st == "enter_next":
            info = f"BUY at the next open (breakout above {s['level']:.6g})"
        elif st == "exit_next":
            info = "selling at the next open"
        else:
            info = "waiting for a 4h breakout"
        rows.append(f"<tr><td>{sym}</td><td>{info}</td><td>{sources.get(sym, '')}</td></tr>")
    trows = "".join(f"<tr><td>{ist(t['entry_time'])}</td><td>{t['symbol']}</td><td>{t['entry']:.6g}</td>"
                    f"<td>{t['exit']:.6g}</td><td>{t['why']}</td><td>{t['r']:+.2f}R</td></tr>"
                    for t in sorted(trades, key=lambda t: t["exit_time"], reverse=True)[:50])
    ev = "".join(f"<li>{e}</li>" for e in reversed(book.get("events", [])[-20:]))
    html = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>4H trend paper book</title><style>body{{font:15px system-ui;margin:16px;max-width:900px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}
.k{{font-size:28px;font-weight:600}}</style>
<h2>4H trend strategy: paper book</h2>
<p>Updated {ist(now)} IST. Paper start {book['start'][:10]}. Rs 10,000 paper account, compounding, 2% risk a trade (position at most 5x), after charges.</p>
<p class=k>Rs {eq:,.0f} &middot; {len(trades)} trades &middot; {sum(rs):+.2f}R</p>
<p><b>Phone alerts:</b> install the free <b>ntfy</b> app, tap +, and subscribe to the topic
<code style="font-size:16px">{book.get('ntfy_topic', '(set by NTFY_TOPIC)')}</code> (server ntfy.sh). Breakouts arrive about a
minute after the 4h close: buy at market, with the stop and size.</p>
<h3>Markets now</h3><table><tr><th>market</th><th>state</th><th>data</th></tr>{''.join(rows)}</table>
<h3>Latest events</h3><ul>{ev or '<li>none yet</li>'}</ul>
<h3>Closed trades</h3><table><tr><th>entered</th><th>market</th><th>entry</th><th>exit</th><th>why</th><th>R</th></tr>{trows}</table>
<p>Rules: 4h close above the 55-bar high with the daily close above its 200-day average; buy at market at the
next open; stop 2 ATR; exit on a 4h close below the 20-bar low. Backtest after charges: +0.83R a trade in
2021-24, +0.57R in 2025-26.</p>"""
    (REPORT_DIR / "trend.html").write_text(html)


def run():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "trend-state.json"
    book = json.loads(path.read_text()) if path.exists() else {
        "start": pd.Timestamp.now(tz="UTC").isoformat(timespec="minutes"), "markets": {}, "events": []}
    now = pd.Timestamp.now(tz="UTC")
    topic = os.environ.get("NTFY_TOPIC") or book.get("ntfy_topic")
    if not topic:
        # A private channel name, kept on the server (behind the site login), never in the repository.
        topic = book["ntfy_topic"] = f"ati-trend-{secrets.token_hex(8)}"
        notify(topic, "ATI trend alerts connected", "You will get breakouts, fills and exits here.")
    trades_so_far = [t for st_ in book["markets"].values() for t in st_.get("closed", [])]
    equity = _equity(trades_so_far)
    sources, new_events = {}, []
    for sym in SYMBOLS:
        try:
            d1, h4, m15, src = fetch(sym)
        except Exception as exc:
            sources[sym] = f"error: {exc}"[:200]
            continue
        sources[sym] = src
        st = book["markets"].setdefault(sym, {})
        for e in advance(st, indicators(d1, h4), m15, sym):
            new_events.append(f"{now.tz_convert('Asia/Kolkata').strftime('%d %b %H:%M')} IST {e}")
            title, body, urgent = alert_text(sym, e, st, equity)
            notify(topic, title, body, urgent)
        time.sleep(0.2)
    book["events"] = (book.get("events", []) + new_events)[-500:]
    path.write_text(json.dumps(book, indent=1, default=str))
    write_report(book, now, new_events, sources)
    return path


if __name__ == "__main__":
    print(f"trend: wrote {run()}", flush=True)
