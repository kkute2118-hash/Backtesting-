#!/usr/bin/env python3
"""Trend breakout on the 4-hour chart with 15-minute entries, for crypto and
gold perpetuals (follows research/fx_crypto/STEP5_DAILY_TREND.md).

Signal (4h close): close above the highest high of the previous N 4h bars,
the last completed daily close above its 200-day average, long only.
Entries, all executed on 15-minute bars:
  next     market buy at the next 4h open
  retest   limit buy at the broken 4h high (the S/R flip), valid 24 hours
  confirm  after price comes back within 0.25 ATR of the broken high, buy on
           the first 15m close above the last 15m swing high (micro MSB), 24 hours
Stop: 2 ATR(4h) below the entry, checked on 15m bars (a gap exits at the open).
Exit: a 4h close below the lowest low of the previous M 4h bars, at the next
15m open. Costs: taker 0.05% + 18% GST + 0.01% slippage a side (a limit
entry pays maker 0.02% + GST), real Binance funding while held (gold 0.01%
per 8 hours). Also runs the daily 55/20 for comparison.

Usage: python scripts/trend_4h_study.py DATA_DIR OUT_PREFIX
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "XAUUSD")
TAKER = 0.0005 * 1.18 + 0.0001
MAKER = 0.0002 * 1.18
GOLD_FUNDING_DAY = 0.0003
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def load(data: Path, sym: str):
    df = pd.read_csv(data / f"{sym}_5m.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    m15 = df.resample("15min").agg(agg).dropna()
    h4 = df.resample("4h").agg(agg).dropna()
    d1 = df.resample("1D").agg(agg).dropna()
    f = data / f"{sym}_funding.csv.gz"
    if f.exists():
        fr = pd.read_csv(f)
        fr["time"] = pd.to_datetime(fr["time"], utc=True, format="mixed")
        day_f = fr.groupby(fr.time.dt.floor("1D")).funding_rate.sum()
    else:
        day_f = pd.Series(GOLD_FUNDING_DAY, index=d1.index)
    # funding per 15m bar held (positive = longs pay)
    m15["funding"] = day_f.reindex(m15.index.floor("1D")).fillna(day_f.mean()).to_numpy() / 96
    trend_ok = (d1.close > d1.close.rolling(200).mean()).shift(1)        # last *completed* day
    h4["trend"] = trend_ok.reindex(h4.index.floor("1D")).fillna(False).astype(bool).to_numpy()
    tr = np.maximum(h4.high - h4.low, np.maximum(abs(h4.high - h4.close.shift()), abs(h4.low - h4.close.shift())))
    h4["atr"] = tr.rolling(20).mean()
    return m15, h4


def swings_high(h, n=2):
    w = 2 * n + 1
    return h == pd.Series(h).rolling(w, center=True).max().to_numpy()


def run(sym, m15, h4, n_in, n_out, entry_mode):
    H4h, H4l, H4c = h4.high.to_numpy(), h4.low.to_numpy(), h4.close.to_numpy()
    hh = h4.high.rolling(n_in).max().shift().to_numpy()
    ll = h4.low.rolling(n_out).min().shift().to_numpy()
    atr, trend = h4.atr.to_numpy(), h4.trend.to_numpy()
    t4 = h4.index
    o, h, l, c, fund = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "funding"))
    t15 = m15.index
    sh = swings_high(h)
    pos15 = t15.searchsorted
    nxt = t15 + pd.Timedelta(minutes=15)
    last4 = np.asarray((nxt.hour % 4 == 0) & (nxt.minute == 0))
    idx4 = t4.searchsorted(t15, side="right") - 1
    trades = []
    j = 220
    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
            j += 1
            continue
        lvl, a = hh[j], atr[j]
        k0 = pos15(t4[j] + pd.Timedelta(hours=4))        # first 15m bar after the signal bar
        k_end = min(k0 + 96, len(c) - 1)                  # 24 hours to get in
        k_in, px, fee_in = None, None, TAKER
        if entry_mode == "next":
            k_in, px = k0, o[k0]
        elif entry_mode == "retest":
            for k in range(k0, k_end):
                if l[k] <= lvl:
                    k_in, px, fee_in = k, min(o[k], lvl), MAKER
                    break
        else:   # confirm
            touched, last_sw = False, None
            for k in range(k0 - 8, k_end):
                if k - 2 >= 0 and sh[k - 2]:
                    last_sw = h[k - 2]
                if k < k0:
                    continue
                touched = touched or l[k] <= lvl + 0.25 * a
                if touched and last_sw is not None and c[k] > last_sw:
                    k_in, px = min(k + 1, len(c) - 1), o[min(k + 1, len(c) - 1)]
                    break
        if k_in is None:
            j += 1
            continue
        stop = px - 2 * a
        risk = px - stop
        funding = 0.0
        k = k_in
        exit_px = None
        while k < len(c) - 1:
            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break
            funding += fund[k]
            if last4[k]:                                  # this 15m bar closes a 4h bar
                j4 = idx4[k]
                if np.isfinite(ll[j4]) and H4c[j4] < ll[j4]:
                    k += 1
                    exit_px = o[k]
                    break
            k += 1
        if exit_px is None:
            break
        cost = fee_in * px + TAKER * exit_px + funding * px
        trades.append({"symbol": sym, "mode": entry_mode, "n_in": n_in, "entry_time": t15[k_in],
                       "exit_time": t15[min(k, len(t15) - 1)], "entry": px, "stop": stop, "exit": exit_px,
                       "risk_pct": risk / px * 100, "r": (exit_px - px - cost) / risk, "cost_r": cost / risk})
        j = t4.searchsorted(t15[min(k, len(t15) - 1)])     # one position at a time
    return trades


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    rows = []
    for sym in SYMBOLS:
        m15, h4 = load(data, sym)
        for n_in, n_out in ((55, 20), (20, 10)):
            for mode in ("next", "retest", "confirm"):
                rows += run(sym, m15, h4, n_in, n_out, mode)
        print(sym, len(rows), file=sys.stderr, flush=True)
    t = pd.DataFrame(rows)
    t["test"] = t.entry_time >= SPLIT
    t.to_csv(f"{prefix}_trades.csv", index=False)
    for (n_in, mode), g in t.groupby(["n_in", "mode"]):
        a, b = g[~g.test].r, g[g.test].r
        print(f"4h {n_in}/{20 if n_in == 55 else 10} entry={mode:8s} 2021-24 n={len(a):4d} avg {a.mean():+.2f}R win {(a > 0).mean():.0%} | "
              f"2025-26 n={len(b):4d} avg {b.mean():+.2f}R win {(b > 0).mean():.0%} | cost {g.cost_r.median():.2f}R stop {g.risk_pct.median():.1f}%")


if __name__ == "__main__":
    main()
