#!/usr/bin/env python3
"""Grid search of Donchian trend breakouts on real 2021-2026 prices.

Signal: a bar closes beyond the highest high (long) / lowest low (short) of the
previous N_IN bars, optionally only when the last completed daily close is on
the right side of its L-day average. Entry: next bar's open (market), or a
limit at the broken level for 24 hours that fills only 0.05 ATR through.
Stop: K x ATR(20). Exit: a close beyond the N_OUT-bar opposite channel, at the
next bar's open; a stop is hit at the stop, or at the open on a gap.
Costs per side: crypto taker 0.05% + 18% GST + 0.01% slippage (maker 0.02% +
GST on limit fills) and real Binance funding while held; forex and gold the
median recorded spread. Writes per (config, symbol, year): trades, wins, R.

Usage: python scripts/search_trend_grid.py DATA_DIR OUT.csv.gz
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
TAKER = 0.0005 * 1.18 + 0.0001
MAKER = 0.0002 * 1.18 + 0.0001
PAIRS = [(20, 10), (30, 10), (30, 20), (40, 10), (40, 20), (40, 30), (55, 10), (55, 20), (55, 30),
         (55, 50), (80, 20), (80, 30), (80, 40), (80, 50), (100, 20), (100, 30), (100, 50), (100, 60)]
STOPS = (1.5, 2.0, 3.0)
TRENDS = (0, 100, 200)
ENTRIES = (0, 1)          # 0 market at next open, 1 limit at the level for 24h
DIRS = (1, 2)             # 1 long only, 2 long and short


@njit(cache=True)
def run(o, h, l, c, atr, hh_in, ll_in, ll_out, hh_out, up, dn, fund, side_cost, lim_cost,
        stop_k, entry_mode, dirs, lim_bars):
    n = len(c)
    out_i = np.empty(n, np.int64)
    out_r = np.empty(n, np.float64)
    out_g = np.empty(n, np.float64)
    k = 0
    pos = 0          # +1 long, -1 short
    pend = 0         # pending limit direction
    pend_lvl = 0.0
    pend_atr = 0.0
    pend_left = 0
    entry = stop = risk = fee_in = 0.0
    fund_acc = 0.0
    exit_next = False
    for i in range(1, n):
        # 1) a pending exit fills at this bar's open
        if pos != 0 and exit_next:
            px = o[i]
            g = (px - entry) * pos / risk
            cost = (fee_in * entry + side_cost * px + fund_acc * entry) / risk
            out_i[k] = i; out_r[k] = g - cost; out_g[k] = g; k += 1
            pos = 0; exit_next = False
        # 2) a pending limit may fill
        if pos == 0 and pend != 0:
            if pend == 1 and l[i] <= pend_lvl - 0.05 * pend_atr:
                entry = min(o[i], pend_lvl); pos = 1
            elif pend == -1 and h[i] >= pend_lvl + 0.05 * pend_atr:
                entry = max(o[i], pend_lvl); pos = -1
            if pos != 0:
                stop = entry - pos * stop_k * pend_atr; risk = stop_k * pend_atr
                fee_in = lim_cost; fund_acc = 0.0; pend = 0
            else:
                pend_left -= 1
                if pend_left <= 0:
                    pend = 0
        # 3) the stop, inside this bar
        if pos != 0:
            fund_acc += fund[i] * pos
            hit = (pos == 1 and l[i] <= stop) or (pos == -1 and h[i] >= stop)
            if hit:
                px = min(o[i], stop) if pos == 1 else max(o[i], stop)
                g = (px - entry) * pos / risk
                cost = (fee_in * entry + side_cost * px + fund_acc * entry) / risk
                out_i[k] = i; out_r[k] = g - cost; out_g[k] = g; k += 1
                pos = 0
                continue
        # 4) at this bar's close: exit rule, then new signals
        if pos == 1 and not np.isnan(ll_out[i]) and c[i] < ll_out[i]:
            exit_next = True
        elif pos == -1 and not np.isnan(hh_out[i]) and c[i] > hh_out[i]:
            exit_next = True
        if pos == 0 and pend == 0 and i + 1 < n and not np.isnan(atr[i]) and atr[i] > 0:
            sig = 0
            if up[i] and not np.isnan(hh_in[i]) and c[i] > hh_in[i]:
                sig = 1
            elif dirs == 2 and dn[i] and not np.isnan(ll_in[i]) and c[i] < ll_in[i]:
                sig = -1
            if sig != 0:
                if entry_mode == 0:
                    entry = o[i + 1]; pos = 0
                    # enter at the next open: handled by marking a pending market order
                    pend = 2 * sig; pend_lvl = entry; pend_atr = atr[i]
                else:
                    pend = sig; pend_lvl = hh_in[i] if sig == 1 else ll_in[i]
                    pend_atr = atr[i]; pend_left = lim_bars
        # a market order placed at this close fills at the next open
        if pend == 2 or pend == -2:
            if i + 1 < n:
                d = 1 if pend == 2 else -1
                pos = d; entry = o[i + 1]
                stop = entry - d * stop_k * pend_atr; risk = stop_k * pend_atr
                fee_in = side_cost; fund_acc = 0.0
                # the entry bar's stop/exit is processed on the next iteration
            pend = 0
    return out_i[:k], out_r[:k], out_g[:k]


def load(data: Path, sym: str):
    df = pd.read_csv(data / f"{sym}_5m.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    if sym.endswith("USDT"):
        side, lim = TAKER, MAKER
    else:
        frac = float((df["spread"] / df["close"]).median())
        side = lim = frac / 2 + 0.00002
    fund_day = None
    f = data / f"{sym}_funding.csv.gz"
    if f.exists():
        fr = pd.read_csv(f)
        fr["time"] = pd.to_datetime(fr["time"], utc=True, format="mixed")
        fund_day = fr.groupby(fr.time.dt.floor("1D")).funding_rate.sum()
    return df[["open", "high", "low", "close"]], side, lim, fund_day


def bars(df, rule):
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def main():
    data, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for sym in SYMBOLS:
        df, side, lim, fund_day = load(data, sym)
        d1 = bars(df, "1D")
        for tf in ("4h", "1D"):
            b = bars(df, tf)
            day = b.index.floor("1D")
            per_day = 6 if tf == "4h" else 1
            fund = (fund_day.reindex(day).fillna(fund_day.mean()).to_numpy() / per_day
                    if fund_day is not None else np.zeros(len(b)))
            tr = np.maximum(b.high - b.low, np.maximum(abs(b.high - b.close.shift()), abs(b.low - b.close.shift())))
            atr = tr.rolling(20).mean().to_numpy()
            o, h, l, c = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
            years = b.index.year.to_numpy()
            lim_bars = 6 if tf == "4h" else 1
            trend_cache = {}
            for t in TRENDS:
                if t == 0:
                    trend_cache[t] = (np.ones(len(b), bool), np.ones(len(b), bool))
                else:
                    sma = d1.close.rolling(t).mean()
                    upd = (d1.close > sma).shift(1).reindex(day).fillna(False).to_numpy().astype(bool)
                    dnd = (d1.close < sma).shift(1).reindex(day).fillna(False).to_numpy().astype(bool)
                    warm = (d1.close.rolling(t).count() >= t).shift(1).reindex(day).fillna(False).to_numpy().astype(bool)
                    trend_cache[t] = (upd & warm, dnd & warm)
            for (n_in, n_out), stop_k, t, em, dr in itertools.product(PAIRS, STOPS, TRENDS, ENTRIES, DIRS):
                hh_in = b.high.rolling(n_in).max().shift().to_numpy()
                ll_in = b.low.rolling(n_in).min().shift().to_numpy()
                ll_out = b.low.rolling(n_out).min().shift().to_numpy()
                hh_out = b.high.rolling(n_out).max().shift().to_numpy()
                up, dn = trend_cache[t]
                # no trades before the 200-day warm-up, so every config starts together
                up = up & (b.index >= pd.Timestamp("2021-08-01", tz="UTC"))
                dn = dn & (b.index >= pd.Timestamp("2021-08-01", tz="UTC"))
                idx, r, g = run(o, h, l, c, atr, hh_in, ll_in, ll_out, hh_out, up, dn, fund, side, lim,
                                stop_k, em, dr, lim_bars)
                cfg = f"{tf}|{n_in}/{n_out}|stop{stop_k}|sma{t}|{'limit' if em else 'market'}|{'ls' if dr == 2 else 'long'}"
                if len(r) == 0:
                    continue
                yr = years[idx]
                for y in np.unique(yr):
                    m = yr == y
                    rows.append((cfg, sym, int(y), int(m.sum()), int((r[m] > 0).sum()),
                                 float(r[m].sum()), float(g[m].sum())))
            print(f"{sym} {tf} done", file=sys.stderr, flush=True)
    pd.DataFrame(rows, columns=["config", "symbol", "year", "trades", "wins", "sum_r", "sum_gross_r"]).to_csv(out, index=False)


if __name__ == "__main__":
    main()
