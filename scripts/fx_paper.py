#!/usr/bin/env python3
"""Paper-trade the liquidity strategy (version B, research/fx_crypto/STEP2_FINDINGS.md)
live on forex and gold, without real money.

Each run fetches the last ~17 days of 5-minute candles from Twelve Data,
replays the frozen rules over them, and keeps a book in STATE_DIR:

  pending  liquidity runs waiting for their first retest: the limit order the
           strategy would have resting now (entry, stop, TP1/TP2, expiry)
  trades   every paper trade since PAPER_START, with its outcome once closed

Rules (frozen; changing them restarts the paper test):
  forex + gold, run -> first retest of the broken level, limit entry that
  must trade 0.05 ATR through the price, entry hours 11:30-13:30 and
  17:30-21:30 IST, framework score >= 65, stop beyond the level, half off at
  TP1 then break-even, rest at TP2, 12-hour limit; the stop must be at least
  three spreads away.

Twelve Data has no BID/ASK, so the cost of each trade is the median
Dukascopy spread for that symbol and hour (research/fx_crypto/spread_by_hour.json).

New pending orders and closed trades are written to ALERTS_FILE as markdown
for the workflow to post. Usage: python scripts/fx_paper.py STATE_DIR
Environment: TWELVEDATA_API_KEY, optional PAPER_START (default 2026-10-05).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.engine import liquidity_pa as lp  # noqa: E402

SYMBOLS = {"EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD", "XAUUSD": "XAU/USD"}
SESSION_UTC = {6, 7, 12, 13, 14, 15}
MIN_SCORE = 65
MAX_COST_R = 1 / 3        # the stop must be at least 3 spreads away, or nobody can trade it
PARAMS = dict(entry="limit", fill_through=0.05)
SPREADS = json.loads((ROOT / "research/fx_crypto/spread_by_hour.json").read_text())["spread"]


def ist(ts) -> str:
    return pd.Timestamp(ts).tz_convert("Asia/Kolkata").strftime("%d %b %H:%M IST")


def fetch(sym: str, key: str) -> pd.DataFrame:
    r = requests.get("https://api.twelvedata.com/time_series", timeout=60, params={
        "symbol": SYMBOLS[sym], "interval": "5min", "outputsize": 5000,
        "timezone": "UTC", "order": "ASC", "apikey": key})
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise RuntimeError(f"{sym}: Twelve Data {j.get('code')} {j.get('message')}")
    df = pd.DataFrame(j["values"])
    df["time"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]].astype(float)
    now = pd.Timestamp.now(tz="UTC")
    df = df[df.index + pd.Timedelta(minutes=5) <= now]        # drop the bar still forming
    df["volume"] = 0.0
    table = SPREADS[sym]
    df["spread"] = [table.get(str(h), table.get(h)) for h in df.index.hour]
    return df


def trade_id(row) -> str:
    return f"{row['symbol']}|{row['event_time']}|{int(row['direction'])}"


def main():
    state_dir = Path(sys.argv[1])
    state_dir.mkdir(parents=True, exist_ok=True)
    # Tolerate a pasted "NAME=value", quotes or a trailing newline: keys are plain alphanumerics.
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip().strip("='\" ").rpartition("=")[2].strip("='\" \n")
    if not key:
        # Skip quietly rather than fail: a failing schedule would email the owner every 15 minutes.
        print("::warning title=FX paper trading paused::add the repository secret TWELVEDATA_API_KEY")
        return
    start = pd.Timestamp(os.environ.get("PAPER_START", "2026-10-05"), tz="UTC")
    state_file = state_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {"alerted": [], "trades": {}}
    alerts, pending_all, errors = [], [], []
    prices = {}
    now = pd.Timestamp.now(tz="UTC")

    for sym in SYMBOLS:
        try:
            df = fetch(sym, key)
        except Exception as exc:                     # one bad symbol never stops the rest
            errors.append(str(exc)[:200])
            continue
        eng = lp.Engine(df, sym, lp.Params(**PARAMS))
        setups = pd.DataFrame([lp.asdict(s) for s in eng.run()])
        if len(setups):
            setups = setups[(setups.decision == "TRADE") & (setups.family == "continuation")]
            setups["ts"] = pd.to_datetime(setups.entry_time, utc=True)
            setups = setups[setups.ts.dt.hour.isin(SESSION_UTC) & (setups.score >= MIN_SCORE)
                            & (setups.cost_r <= MAX_COST_R) & (setups.ts >= start)]
        last_bar = df.index[-1]
        prices[sym] = {"price": float(df.close.iloc[-1]), "bar": last_bar.isoformat()}
        for _, row in setups.iterrows() if len(setups) else []:
            tid = trade_id(row)
            still_open = (pd.Timestamp(row.exit_time) >= last_bar and row.outcome in ("time", "tp1+time")
                          and row.hold_minutes < lp.Params().max_hold * 5)
            rec = {k: row[k] for k in ("symbol", "direction", "event_time", "entry_time", "entry", "stop",
                                       "tp1", "tp2", "rr1", "score", "exit_time", "outcome", "r", "cost_r")}
            rec = {k: (v.item() if hasattr(v, "item") else v) for k, v in rec.items()}
            rec["status"] = "open" if still_open else "closed"
            old = state["trades"].get(tid)
            if old is None or old.get("status") == "open":
                if rec["status"] == "closed" and (old is None or old["status"] == "open"):
                    alerts.append(f"**{sym} paper trade closed** ({'long' if rec['direction'] > 0 else 'short'}, "
                                  f"entered {ist(rec['entry_time'])}): {rec['outcome']}, **{rec['r']:+.2f}R**")
                elif old is None:
                    alerts.append(f"**{sym} paper trade opened** {'long' if rec['direction'] > 0 else 'short'} "
                                  f"at {rec['entry']:.5g}, stop {rec['stop']:.5g}, TP1 {rec['tp1']:.5g} ({ist(rec['entry_time'])})")
                state["trades"][tid] = rec
        for o in eng.pending_orders():
            spread = SPREADS[sym].get(str(now.hour), 0.0)
            if (o["score"] < MIN_SCORE or o["rr1"] < eng.p.min_rr or pd.Timestamp(o["expires"]) <= now
                    or spread > MAX_COST_R * abs(o["entry"] - o["stop"])):
                continue
            o["id"] = trade_id(o)
            pending_all.append(o)
            if o["id"] not in state["alerted"]:
                state["alerted"].append(o["id"])
                side = "BUY" if o["direction"] > 0 else "SELL"
                alerts.append(
                    f"**{sym} pending {side} LIMIT {o['entry']:.5g}**: stop {o['stop']:.5g}, "
                    f"TP1 {o['tp1']:.5g} ({o['rr1']:.1f}R), TP2 {o['tp2']:.5g}; score {o['score']}; "
                    f"fills only 11:30-13:30 or 17:30-21:30 IST; cancel at {ist(o['expires'])}")
    state["alerted"] = state["alerted"][-500:]
    state["updated"] = now.isoformat(timespec="minutes")
    state["errors"] = errors
    state["pending"] = pending_all
    state["prices"] = prices             # the latest 5-minute close per market, for the dashboard
    state_file.write_text(json.dumps(state, indent=1, default=str))

    closed = [t for t in state["trades"].values() if t["status"] == "closed"]
    rs = pd.Series([t["r"] for t in closed], dtype=float)
    lines = [f"# Liquidity strategy B: paper trading", "",
             f"Updated {ist(now)}. Paper start {start.date()}. Rules: scripts/fx_paper.py (frozen).", "",
             f"Closed trades: **{len(closed)}**, total **{rs.sum():+.2f}R**, "
             f"average {rs.mean() if len(rs) else 0:+.2f}R, wins {int((rs > 0).sum())}. "
             f"Backtest expectation: about +0.3R a trade, 36% wins, ~80 trades a year.", ""]
    if pending_all:
        lines += ["## Pending limit orders", "", "| symbol | side | entry | stop | TP1 | TP2 | score | cancel at |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {o['symbol']} | {'BUY' if o['direction'] > 0 else 'SELL'} | {o['entry']:.5g} | {o['stop']:.5g} | "
                  f"{o['tp1']:.5g} | {o['tp2']:.5g} | {o['score']} | {ist(o['expires'])} |" for o in pending_all]
        lines.append("")
    if state["trades"]:
        lines += ["## Trades", "", "| entered | symbol | side | entry | stop | TP1 | status | outcome | R |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for t in sorted(state["trades"].values(), key=lambda t: t["entry_time"], reverse=True):
            lines.append(f"| {ist(t['entry_time'])} | {t['symbol']} | {'long' if t['direction'] > 0 else 'short'} | "
                         f"{t['entry']:.5g} | {t['stop']:.5g} | {t['tp1']:.5g} | {t['status']} | "
                         f"{t['outcome'] if t['status'] == 'closed' else ''} | "
                         f"{t['r']:+.2f} |" if t["status"] == "closed" else
                         f"| {ist(t['entry_time'])} | {t['symbol']} | {'long' if t['direction'] > 0 else 'short'} | "
                         f"{t['entry']:.5g} | {t['stop']:.5g} | {t['tp1']:.5g} | open | | |")
    if errors:
        lines += ["", "Data errors this run: " + "; ".join(errors)]
    (state_dir / "README.md").write_text("\n".join(lines) + "\n")
    alerts_file = os.environ.get("ALERTS_FILE")
    if alerts_file and alerts:
        Path(alerts_file).write_text("\n\n".join(alerts) + "\n")
    print(f"{len(pending_all)} pending, {len(state['trades'])} trades, {len(alerts)} alerts, errors: {errors}")


if __name__ == "__main__":
    main()
