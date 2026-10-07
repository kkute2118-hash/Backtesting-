"""Live paper trading of the 4-hour trend breakout on the Oracle server
(research/fx_crypto/STEP14_STRATEGY_SEARCH.md, chosen on 2021-24 real prices,
held on 2025-26).

Rules (frozen; changing them restarts the paper book, see RULES):
  markets   BTCUSDT, ETHUSDT, SOLUSDT, XAUUSDT perpetuals
  signal    a 4h close above the highest high of the previous 40 4h bars
  entry     market buy at the next 15-minute open (the next 4h open)
  stop      1.5 ATR(4h, 20) below the entry
  exit      a 4h close below the lowest low of the previous 30 4h bars, at the
            next 15-minute open; or the stop
  size      1% of equity at risk: position = 1% / stop distance (crypto is
            usually under 1x equity, gold about 1.4x), never above 5x
  charges   taker 0.05% + 18% GST + 0.01% slippage on the entry and the exit,
            funding 0.01% per 8 hours held
  account   Rs 10,000 paper, compounding

Runs every 5 minutes (deploy/oracle/update.sh, ati-lab-trend.timer). Each
run reads only completed candles and moves each market's state forward bar by
bar from where the last run stopped, so a missed run catches up. Writes
REPORT_DIR/trend-state.json (the book), trend-latest.json and trend.html
(served behind the site login at /reports/trend.html).

Alerts: the owner's phone through the free ntfy app: the order to place on a
breakout (size in rupees, stop), the fill, the exit signal and the close.

Data: Binance futures public candles (the exact instruments, no key). If
Binance refuses the server's region, crypto falls back to Binance's spot
market-data host and gold to Yahoo Finance (GC=F).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

REPORT_DIR = Path(os.environ.get("REPORT_DIR", "/data/reports"))
RULES = "4h breakout 40/30, 1.5 ATR stop, 1% risk (step 14)"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSDT")
YAHOO = {"XAUUSDT": "GC=F", "BTCUSDT": "BTC-USD", "ETHUSDT": "ETH-USD", "SOLUSDT": "SOL-USD"}
N_IN, N_OUT, ATR_N, STOP_ATR = 40, 30, 20, 1.5
TAKER = 0.0005 * 1.18 + 0.0001
FUNDING_PER_15M = 0.0001 / 32
START_EQUITY, RISK, MAX_POSITION_X = 10_000.0, 0.01, 5.0
UA = {"User-Agent": "Mozilla/5.0 (ATI Lab paper trading)"}
NTFY = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
FX_BOOK_URL = os.environ.get(
    "FX_BOOK_URL", "https://raw.githubusercontent.com/kkute2118-hash/Backtesting-/fx-paper/state.json")


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
    """Channels and ATR on 4h bars. d1 is accepted for the fetch signature;
    the step 14 rules use no daily trend filter."""
    hh = h4.high.rolling(N_IN).max().shift()
    ll = h4.low.rolling(N_OUT).min().shift()
    tr = np.maximum(h4.high - h4.low, np.maximum(abs(h4.high - h4.close.shift()), abs(h4.low - h4.close.shift())))
    atr = tr.rolling(ATR_N).mean()
    return pd.DataFrame({"hh": hh, "ll": ll, "atr": atr, "close": h4.close}, index=h4.index)


def position_x(entry: float, stop: float) -> float:
    """Position as a multiple of equity so that the stop loses RISK of it."""
    return round(min(RISK / ((entry - stop) / entry), MAX_POSITION_X), 3)


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
        elif status in ("pending", "awaiting_retest"):      # orders from earlier rule sets
            events.append(f"{sym}: order at {st.get('level', 0):.6g} cancelled (rules changed)")
            st.update(status="flat")
        elif status == "enter_next":
            entry = float(b.open)
            stop = entry - STOP_ATR * st["atr"]
            st.update(status="long", entry=entry, stop=stop, entry_time=str(ts), held15=0,
                      size_x=position_x(entry, stop))
            events.append(f"{sym}: BOUGHT at {entry:.6g}, stop {stop:.6g}, position {st['size_x']:.2f}x equity")
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
                    events.append(f"{sym}: 4h close {r.close:.6g} below the 30-bar low {r.ll:.6g}: sell at the next open")
                elif (st.get("status") == "flat" and np.isfinite(r.hh) and np.isfinite(r.atr)
                      and r.close > r.hh):
                    st.update(status="enter_next", level=float(r.hh), atr=float(r.atr), signal_time=str(j),
                              signal_close=float(r.close))
                    events.append(f"{sym}: BREAKOUT, 4h close {r.close:.6g} above the 40-bar high {r.hh:.6g}. "
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
                                        "size_x": st.get("size_x", position_x(entry, stop))})
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
    if "BREAKOUT" in event and "signal_close" in st:
        px = st["signal_close"]
        stop = px - STOP_ATR * st["atr"]
        size_x = position_x(px, stop)
        return (f"{name}: BUY NOW at market (~{px:.6g})",
                f"4h breakout on {name} perp: close {px:.6g} above the 40-bar high {st['level']:.6g}.\n\n"
                f"BUY at market now\nSTOP-LOSS order at {stop:.6g} ({(px - stop) / px:.1%} below)\n"
                f"Position: Rs {equity * size_x:,.0f} ({size_x:.2f}x your Rs {equity:,.0f}; "
                f"set the exchange leverage to 5x)\nRisk: Rs {equity * RISK:,.0f} (1%)\n\n"
                f"Exit: a 4h close below the 30-bar low (you will get an alert).", True)
    if "BOUGHT at" in event and st.get("status") == "long":
        return (f"{name}: paper entry at {st['entry']:.6g}",
                f"Paper book bought {name} at {st['entry']:.6g}.\nStop {st['stop']:.6g}\n"
                f"Position {st['size_x']:.2f}x equity = Rs {equity * st['size_x']:,.0f}", False)
    if "below the 30-bar low" in event:
        return f"{name}: SELL now", event + "\nClose the position at market now.", True
    if "SOLD" in event:
        return f"{name}: position closed", event, False
    return f"{name}", event, False


# ---------------------------------------------------------------- report
def _equity(trades):
    eq = START_EQUITY
    for t in sorted(trades, key=lambda t: t["exit_time"]):
        if "ret" in t:                      # position of size_x times equity, return after charges
            eq += eq * t["size_x"] * t["ret"]
        else:
            eq += eq * 0.01 * t["r"]
    return eq


def write_report(book, now, events, sources):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades = [t for s in book["markets"].values() for t in s.get("closed", [])]
    eq = _equity(trades)
    rs = [t["r"] for t in trades]
    summary = {"updated": now.isoformat(timespec="minutes"), "paper_start": book["start"], "rules": RULES,
               "equity": round(eq, 2), "trades": len(trades), "total_r": round(sum(rs), 2),
               "markets": {k: {kk: v for kk, v in s.items() if kk != "closed"} for k, s in book["markets"].items()},
               "recent_events": book.get("events", [])[-40:], "sources": sources,
               "closed": sorted(trades, key=lambda t: t["exit_time"], reverse=True)[:50]}
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
<h2>4H trend breakout: paper book</h2>
<p>Updated {ist(now)} IST. Paper start {book['start'][:10]}. Rs 10,000 paper account, compounding, 1% risk a trade, after charges.</p>
<p class=k>Rs {eq:,.0f} &middot; {len(trades)} trades &middot; {sum(rs):+.2f}R</p>
<p><b>Phone alerts:</b> install the free <b>ntfy</b> app, tap +, and subscribe to the topic
<code style="font-size:16px">{book.get('ntfy_topic', '(set by NTFY_TOPIC)')}</code> (server ntfy.sh).</p>
<h3>Markets now</h3><table><tr><th>market</th><th>state</th><th>data</th></tr>{''.join(rows)}</table>
<h3>Latest events</h3><ul>{ev or '<li>none yet</li>'}</ul>
<h3>Closed trades</h3><table><tr><th>entered</th><th>market</th><th>entry</th><th>exit</th><th>why</th><th>R</th></tr>{trows}</table>
<p><b>Rules (research/fx_crypto/STEP14_STRATEGY_SEARCH.md):</b> BTC, ETH, SOL and gold perpetuals. Buy at the next
open after a 4h close above the 40-bar high. Stop 1.5 ATR(4h) below the entry. Sell at the next open after a 4h close
below the 30-bar low. Position sized so the stop loses 1% of the account. Real prices 2021-24: +1.30R a trade;
held-out 2025-26: +0.72R; about 1 trade in 4 wins.</p>"""
    (REPORT_DIR / "trend.html").write_text(html)


def fx_alerts(state: dict, seen: set) -> list[tuple[str, str, str, bool]]:
    """(key, title, body, urgent) for forex book events not yet relayed: new
    pending limit orders, fills and closes (scripts/fx_paper.py's state)."""
    ist = lambda x: pd.Timestamp(x).tz_convert("Asia/Kolkata").strftime("%d %b %H:%M IST")  # noqa: E731
    out = []
    for o in state.get("pending", []):
        key = f"p:{o['id']}"
        if key in seen:
            continue
        side = "BUY" if o["direction"] > 0 else "SELL"
        out.append((key, f"{o['symbol']}: {side} LIMIT {o['entry']:.5g}",
                    f"Forex (liquidity B) order to place:\n{side} LIMIT {o['entry']:.5g}\nSTOP {o['stop']:.5g}\n"
                    f"TP1 {o['tp1']:.5g} ({o['rr1']:.1f}R), TP2 {o['tp2']:.5g}\nScore {o['score']}\n"
                    f"Fills only 11:30-13:30 or 17:30-21:30 IST. Cancel at {ist(o['expires'])}.", True))
    for tid, t in state.get("trades", {}).items():
        key = f"t:{tid}:{t['status']}"
        if key in seen:
            continue
        side = "long" if t["direction"] > 0 else "short"
        if t["status"] == "open":
            out.append((key, f"{t['symbol']}: forex {side} filled at {t['entry']:.5g}",
                        f"Paper {side} {t['symbol']} at {t['entry']:.5g} ({ist(t['entry_time'])}).\n"
                        f"Stop {t['stop']:.5g}, TP1 {t['tp1']:.5g}, TP2 {t['tp2']:.5g}.", False))
        else:
            out.append((key, f"{t['symbol']}: forex trade closed {t['r']:+.2f}R",
                        f"{side} {t['symbol']} from {t['entry']:.5g} ({ist(t['entry_time'])}): "
                        f"{t['outcome']}, {t['r']:+.2f}R after costs.", False))
    return out


def relay_fx(book: dict, topic: str) -> None:
    """Forward the forex paper book's events (GitHub branch fx-paper) to the
    same phone topic, so both strategies alert in one place. Never raises."""
    try:
        state = requests.get(FX_BOOK_URL, headers=UA, timeout=20).json()
    except Exception:
        return
    first = "fx_seen" not in book
    seen_list = book.setdefault("fx_seen", [])
    if first:
        notify(topic, "Forex alerts connected",
               "Liquidity strategy B (forex and gold): limit orders to place, fills and closes will arrive here.")
    for key, title, body, urgent in fx_alerts(state, set(seen_list)):
        notify(topic, title, body, urgent)
        seen_list.append(key)
    book["fx_seen"] = seen_list[-1000:]


def _start_book(old: dict | None, now: pd.Timestamp) -> dict:
    """A fresh book under RULES; an older book is kept beside it, and so is the
    phone topic, so the owner's subscription carries on."""
    book = {"start": now.isoformat(timespec="minutes"), "rules": RULES, "markets": {}, "events": []}
    if old:
        stamp = str(old.get("start", "old"))[:10]
        (REPORT_DIR / f"trend-state-before-{now:%Y%m%d}-from-{stamp}.json").write_text(
            json.dumps(old, indent=1, default=str))
        if old.get("ntfy_topic"):
            book["ntfy_topic"] = old["ntfy_topic"]
    return book


def run():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "trend-state.json"
    now = pd.Timestamp.now(tz="UTC")
    old = json.loads(path.read_text()) if path.exists() else None
    book = old if old and old.get("rules") == RULES else _start_book(old, now)
    topic = os.environ.get("NTFY_TOPIC") or book.get("ntfy_topic")
    if not topic:
        # A private channel name, kept on the server (behind the site login), never in the repository.
        topic = book["ntfy_topic"] = f"ati-trend-{secrets.token_hex(8)}"
        notify(topic, "ATI trend alerts connected", "You will get breakouts, fills and exits here.")
    elif book is not old:
        notify(topic, "Trend book: new rules",
               "Paper book restarted: BTC, ETH, SOL, gold. 4h 40-bar breakout, 1.5 ATR stop, "
               "30-bar exit, 1% risk. Forex and leverage tiers removed.")
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
    relay_fx(book, topic)
    book["events"] = (book.get("events", []) + new_events)[-500:]
    path.write_text(json.dumps(book, indent=1, default=str))
    write_report(book, now, new_events, sources)
    return path


if __name__ == "__main__":
    print(f"trend: wrote {run()}", flush=True)
