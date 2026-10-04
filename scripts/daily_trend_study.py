#!/usr/bin/env python3
"""Daily trend / breakout strategies for crypto and gold perpetuals.

Moves of several percent make a 0.14% round trip small, which the intraday
liquidity framework could not overcome (research/fx_crypto/STEP4_SWING_PERPS.md).

Symbols: BTC, ETH, SOL, BNB, XRP (Binance USD-M perps) and gold (Dukascopy spot
standing in for XAUUSDT, which tracks it at 0.99 hourly correlation).

Strategies (signal at a daily close, entry at the next day's open):
  donchian    close above the highest high of the last N days (long) or below
              the lowest low (short); exit on a close through the M-day channel
  run         the owner's "liquidity run" on the daily chart: a close through
              the prior week's high (BSL) or low (SSL) with a strong body
              (>= 60% of range) closing in the outer quarter; stop beyond the
              run candle; exit on a close through the 10-day channel
Options: trend filter (close vs 200-day average), long-only, ATR stop.
Stops are checked on daily highs and lows; a gap through the stop exits at
the open. Costs: taker 0.05% + 18% GST + 0.01% slippage per side, and the
real funding paid or received each day held (gold: 0.01% per 8 hours paid).

Usage: python scripts/daily_trend_study.py DATA_DIR OUT_PREFIX
Writes OUT_PREFIX_trades.csv and prints train (2021-24) / test (2025-26).
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "XAUUSD")
FEE_SIDE = 0.0005 * 1.18 + 0.0001
GOLD_FUNDING_DAY = 0.0001 * 3
SPLIT = pd.Timestamp("2025-01-01")


def daily(data: Path, sym: str) -> pd.DataFrame:
    df = pd.read_csv(data / f"{sym}_5m.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    if sym == "XAUUSD":                      # forex day: 17:00 New York close
        key = (df.index.tz_convert("America/New_York") + pd.Timedelta(hours=7)).floor("1D").tz_localize(None)
    else:
        key = df.index.floor("1D").tz_localize(None)
    d = df.groupby(key).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                            close=("close", "last"), n=("close", "size"))
    d = d[d.n >= 100].drop(columns="n")
    # funding paid by a long, per calendar day (positive = longs pay)
    f = data / f"{sym}_funding.csv.gz"
    if f.exists():
        fr = pd.read_csv(f)
        fr["time"] = pd.to_datetime(fr["time"], utc=True, format="mixed")
        d["funding"] = fr.groupby(fr.time.dt.floor("1D").dt.tz_localize(None)).funding_rate.sum().reindex(d.index).fillna(0.0)
    else:
        d["funding"] = GOLD_FUNDING_DAY
    tr = np.maximum(d.high - d.low, np.maximum(abs(d.high - d.close.shift()), abs(d.low - d.close.shift())))
    d["atr"] = tr.rolling(20).mean()
    d["sma200"] = d.close.rolling(200).mean()
    wk = pd.Series(d.index.to_period("W-SUN"), index=d.index)
    wk_hi = d.high.groupby(wk).max()
    wk_lo = d.low.groupby(wk).min()
    d["pwh"] = wk.map(wk_hi.shift()).to_numpy()
    d["pwl"] = wk.map(wk_lo.shift()).to_numpy()
    return d


def simulate(d: pd.DataFrame, sym: str, kind: str, n: int, m: int, trend: bool, long_only: bool, atr_stop: float):
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, sma, fund = d.atr.to_numpy(), d.sma200.to_numpy(), d.funding.to_numpy()
    hh = d.high.rolling(n).max().shift().to_numpy()
    ll = d.low.rolling(n).min().shift().to_numpy()
    xh = d.high.rolling(m).max().shift().to_numpy()      # exit channel
    xl = d.low.rolling(m).min().shift().to_numpy()
    pwh, pwl = d.pwh.to_numpy(), d.pwl.to_numpy()
    idx = d.index
    trades = []
    pos = None
    for i in range(201, len(c) - 1):
        if pos is not None:
            dd, stop = pos["d"], pos["stop"]
            # stop: gap through it exits at the open
            hit = (l[i] <= stop) if dd > 0 else (h[i] >= stop)
            px = None
            if hit:
                px = min(o[i], stop) if dd > 0 else max(o[i], stop)
            elif (dd > 0 and c[i] < xl[i]) or (dd < 0 and c[i] > xh[i]):
                px = o[i + 1]                                  # channel exit at the next open
            pos["funding"] += fund[i] * dd                      # longs pay positive funding
            if px is not None:
                risk = abs(pos["entry"] - pos["stop0"])
                gross = (px - pos["entry"]) * dd / risk
                cost = (FEE_SIDE * (pos["entry"] + px) + pos["funding"] * pos["entry"]) / risk
                trades.append({"symbol": sym, "kind": kind, "d": dd, "entry_date": pos["date"],
                               "exit_date": idx[i] if hit else idx[i + 1], "entry": pos["entry"],
                               "stop": pos["stop0"], "exit": px, "risk_pct": risk / pos["entry"] * 100,
                               "gross_r": gross, "cost_r": cost, "r": gross - cost,
                               "days": (idx[i] - pos["date"]).days + 1})
                pos = None
            continue
        if not np.isfinite(atr[i]) or not np.isfinite(sma[i]):
            continue
        sig = 0
        rng = h[i] - l[i]
        if kind == "donchian":
            if c[i] > hh[i]:
                sig = 1
            elif c[i] < ll[i]:
                sig = -1
        elif kind == "run" and rng > 0 and np.isfinite(pwh[i]):
            body = abs(c[i] - o[i]) / rng
            if c[i] > pwh[i] and body >= 0.6 and (h[i] - c[i]) <= 0.25 * rng and c[i] - pwh[i] >= 0.1 * atr[i]:
                sig = 1
            elif c[i] < pwl[i] and body >= 0.6 and (c[i] - l[i]) <= 0.25 * rng and pwl[i] - c[i] >= 0.1 * atr[i]:
                sig = -1
        if sig == 0 or (long_only and sig < 0):
            continue
        if trend and ((sig > 0 and c[i] < sma[i]) or (sig < 0 and c[i] > sma[i])):
            continue
        entry = o[i + 1]
        if kind == "run":
            stop = (l[i] - 0.1 * atr[i]) if sig > 0 else (h[i] + 0.1 * atr[i])   # beyond the run candle
        else:
            stop = entry - sig * atr_stop * atr[i]
        if (entry - stop) * sig <= 0:
            continue
        pos = {"d": sig, "entry": entry, "stop": stop, "stop0": stop, "date": idx[i + 1], "funding": 0.0}
    return trades


def metrics(r: pd.Series) -> str:
    if r.empty:
        return "n=0"
    w, lo = r[r > 0].sum(), -r[r <= 0].sum()
    eq = r.cumsum()
    return (f"n={len(r):3d} win {100 * (r > 0).mean():4.1f}% avg {r.mean():+.2f}R "
            f"PF {w / lo if lo else float('inf'):.2f} DD {(eq - eq.cummax()).min():+.1f}R")


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    days = {s: daily(data, s) for s in SYMBOLS}
    rows = []
    grid = [("donchian", n, m, a) for n, m in ((20, 10), (55, 20), (100, 50)) for a in (2.0, 3.0)] + \
           [("run", 0, 10, 0.0)]
    for (kind, n, m, a), trend, lo in itertools.product(grid, (False, True), (False, True)):
        name = f"{kind}{'' if kind == 'run' else f' {n}/{m} stop{a:g}ATR'}{' +trend' if trend else ''}{' long-only' if lo else ''}"
        for s, d in days.items():
            for t in simulate(d, s, kind, max(n, 1), m, trend, lo, a):
                t["variant"] = name
                rows.append(t)
    t = pd.DataFrame(rows)
    t["test"] = t.entry_date >= SPLIT
    t.to_csv(f"{prefix}_trades.csv", index=False)
    for v, g in t.groupby("variant", sort=False):
        print(f"{v:45s} 2021-24 {metrics(g[~g.test].r)} | 2025-26 {metrics(g[g.test].r)}")


if __name__ == "__main__":
    main()
