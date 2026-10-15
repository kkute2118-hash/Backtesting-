#!/usr/bin/env python3
"""Opening-range breakout (the owner's idea, 12 Oct 2026) on real 2021-2026 prices.

At a market open, the first 15-minute candle sets a range. A break above it is
a buy, a break below a sell; one trade per session (the first break). Variants:

  entry   touch  - stop order: filled at the range edge (or the open on a gap)
          close  - a 15-minute candle closes beyond the edge; filled at the next open
  stop    edge   - the opposite end of the opening candle
          half   - the middle (50%) of the opening candle
  exit    1R, 1.5R, 2R, 3R target, or none; anything still open is closed
          8 hours after the open
  costcap all trades, or only those whose costs are under 1/3 of the risk

5-minute bars; when a bar spans both the stop and the target the stop is
assumed first, a target is never counted on the entry bar, and a stop gap
fills at the bar's open. Costs per side: forex and gold half the recorded
spread of that bar plus 0.002% slippage; crypto perpetuals 0.05% taker +
18% GST + 0.01% slippage (funding ignored: trades last at most 8 hours).

Writes one row per (symbol, session, entry, stop, exit, costcap, year).
Usage: python scripts/research/search_orb.py DATA_DIR OUT.csv.gz
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

FX = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD")
CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
# session name -> (time zone, local open)
SESSIONS = {
    "London 08:00": ("Europe/London", "08:00"),
    "New York 08:00": ("America/New_York", "08:00"),
    "New York 09:30": ("America/New_York", "09:30"),
    "Tokyo 09:00": ("Asia/Tokyo", "09:00"),
    "India 09:15": ("Asia/Kolkata", "09:15"),
    "UTC 00:00": ("UTC", "00:00"),
}
TARGETS = (1.0, 1.5, 2.0, 3.0, np.inf)
HOLD = pd.Timedelta(hours=8)
TAKER = 0.0005 * 1.18 + 0.0001
SLIP_FX = 0.00002


def load(data: Path, sym: str) -> pd.DataFrame:
    df = pd.read_csv(data / f"{sym}_5m.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    if "spread" not in df:
        df["spread"] = 0.0
    return df[["open", "high", "low", "close", "spread"]]


def session_opens(index: pd.DatetimeIndex, tz: str, hhmm: str) -> pd.DatetimeIndex:
    days = pd.date_range(index[0].tz_convert(tz).normalize(), index[-1].tz_convert(tz).normalize(), freq="D")
    h, m = map(int, hhmm.split(":"))
    return (days + pd.Timedelta(hours=h, minutes=m)).tz_convert("UTC")


def side_cost(sym: str, price: float, spread: float) -> float:
    """Cost of one side in price units."""
    if sym in CRYPTO:
        return TAKER * price
    return spread / 2 + SLIP_FX * price


def trades_for(sym: str, df: pd.DataFrame, tz: str, hhmm: str):
    t = df.index.values
    o, h, l, c, sp = (df[k].to_numpy() for k in ("open", "high", "low", "close", "spread"))
    out = []
    for start in session_opens(df.index, tz, hhmm):
        s0 = np.searchsorted(t, start.to_datetime64())
        s1 = np.searchsorted(t, (start + pd.Timedelta(minutes=15)).to_datetime64())
        s2 = np.searchsorted(t, (start + HOLD).to_datetime64())
        # a complete opening candle: three 5-minute bars starting at the open
        if s1 - s0 != 3 or t[s0] != start.to_datetime64() or s2 - s1 < 6:
            continue
        hi, lo = h[s0:s1].max(), l[s0:s1].min()
        if hi <= lo:
            continue
        for entry_mode in ("touch", "close"):
            e_i, d, entry = None, 0, None
            if entry_mode == "touch":
                for i in range(s1, s2):
                    up, dn = h[i] > hi, l[i] < lo
                    if up and dn:
                        break                      # both sides in one bar: order unknown, skip
                    if up or dn:
                        d = 1 if up else -1
                        edge = hi if up else lo
                        entry = max(o[i], edge) if up else min(o[i], edge)
                        e_i = i
                        break
            else:
                for j in range(s1, s2 - 3, 3):     # 15-minute candles after the opening one
                    cl = c[j + 2]
                    if cl > hi or cl < lo:
                        if j + 3 < s2:
                            d = 1 if cl > hi else -1
                            e_i = j + 3
                            entry = o[e_i]
                        break
            if e_i is None:
                continue
            for stop_mode in ("edge", "half"):
                stop = (lo if d > 0 else hi) if stop_mode == "edge" else (hi + lo) / 2
                risk = (entry - stop) * d
                if risk <= 0:
                    continue
                cin = side_cost(sym, entry, sp[e_i])
                # stop: first bar (entry bar included) whose low/high reaches it
                seg_l, seg_h, seg_o = l[e_i:s2], h[e_i:s2], o[e_i:s2]
                hit_stop = (seg_l <= stop) if d > 0 else (seg_h >= stop)
                k_stop = int(np.argmax(hit_stop)) if hit_stop.any() else None
                for tgt in TARGETS:
                    k_tgt = None
                    if np.isfinite(tgt):
                        level = entry + d * tgt * risk
                        hit_t = (seg_h >= level) if d > 0 else (seg_l <= level)
                        hit_t[0] = False           # never on the entry bar
                        k_tgt = int(np.argmax(hit_t)) if hit_t.any() else None
                    if k_stop is not None and (k_tgt is None or k_stop <= k_tgt):
                        k = k_stop
                        px = min(seg_o[k], stop) if d > 0 else max(seg_o[k], stop)
                        if k == 0:
                            px = stop
                        why = "stop"
                    elif k_tgt is not None:
                        k, px, why = k_tgt, level, "target"
                    else:
                        k, px, why = s2 - 1 - e_i, c[s2 - 1], "time"
                    cout = side_cost(sym, px, sp[e_i + k])
                    r = ((px - entry) * d - cin - cout) / risk
                    out.append((sym, entry_mode, stop_mode, tgt, pd.Timestamp(start).year,
                                r, (cin + cout) / risk, why))
    return out


def main() -> None:
    data, out_path = Path(sys.argv[1]), sys.argv[2]
    rows = []
    for sym in FX + CRYPTO:
        df = load(data, sym)
        for name, (tz, hhmm) in SESSIONS.items():
            if name == "UTC 00:00" and sym not in CRYPTO:
                continue                            # forex has no trading at the daily roll
            for rec in trades_for(sym, df, tz, hhmm):
                rows.append((name,) + rec)
        print(sym, len(rows), flush=True)
    t = pd.DataFrame(rows, columns=["session", "symbol", "entry", "stop", "target", "year", "r", "cost_r", "why"])
    t["capped"] = t.cost_r <= 1 / 3
    t.to_csv(out_path, index=False)
    print("wrote", out_path, len(t))


if __name__ == "__main__":
    main()
