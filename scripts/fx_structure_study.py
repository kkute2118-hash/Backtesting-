#!/usr/bin/env python3
"""Intraday market-structure study for forex, gold and crypto perpetuals.

Reads the 5-minute files published by scripts/fetch_fx_crypto.py and measures,
per symbol and separately for 2021-24 (where rules may be chosen) and 2025-26
(where they must hold, the repository's evidence rule):

  1. hours      when each market moves: median 1-hour range, spread, volume by
                UTC hour, and the cost of one round trip as a share of that range
  2. memory     trend or mean reversion: variance ratios from 15 minutes to 4
                hours, and whether the last hour predicts the next
  3. days       the prior day's high and low: how often a break holds by the
                close or fails back inside (a "sweep"), and both-sides days
  4. orb        opening-range breakouts (London 08:00, New York 08:00 local for
                forex; 00:00 UTC and the 13:30 UTC US open for crypto): win rate
                and expectancy after costs at 1R, 1.5R, 2R and 3R targets
  5. bos        break of structure on 15-minute swings: follow the break, or
                fade a wick through the swing that closes back inside
  6. vol        does a wide day follow a wide day; range by weekday

Every simulated trade pays the symbol's real cost: the recorded Dukascopy
BID/ASK spread for forex and gold, and 0.05% taker fee plus 0.01% slippage per
side for crypto. When a stop and a target fall inside the same 5-minute bar the
stop is assumed to come first.

Usage: python scripts/fx_structure_study.py DATA_DIR OUT.json [--symbols A,B]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CRYPTO_COST_PER_SIDE = 0.0005 + 0.0001
TRAIN = ("2021-01-01", "2025-01-01")
TEST = ("2025-01-01", "2100-01-01")
TARGETS = (1.0, 1.5, 2.0, 3.0)


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated()]
    return df


def is_crypto(sym: str) -> bool:
    return sym.endswith("USDT")


def round_trip_cost(df: pd.DataFrame, sym: str) -> pd.Series:
    """Price cost of entering and leaving at each bar."""
    if is_crypto(sym):
        return df["close"] * 2 * CRYPTO_COST_PER_SIDE
    return df["spread"].fillna(df["spread"].median())


def periods(df):
    return {"2021-24": df.loc[TRAIN[0]:TRAIN[1]].iloc[:-1] if len(df.loc[TRAIN[0]:TRAIN[1]]) else df.iloc[:0],
            "2025-26": df.loc[TEST[0]:]}


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)


# ---------------------------------------------------------------- 1. hours
def hours(df, sym):
    h1 = df.resample("1h").agg({"high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    rng_bp = (h1.high - h1.low) / h1.close * 1e4
    cost_bp = (round_trip_cost(df, sym) / df.close * 1e4).resample("1h").mean().reindex(h1.index)
    vol_share = h1.volume / h1.volume.groupby(h1.index.date).transform("sum")
    by = pd.DataFrame({"range_bp": rng_bp, "cost_bp": cost_bp, "vol_share": vol_share})
    g = by.groupby(by.index.hour)
    out = []
    for hr, x in g:
        rb, cb = x.range_bp.median(), x.cost_bp.median()
        out.append({"utc_hour": int(hr), "ist": f"{(hr * 60 + 330) // 60 % 24:02d}:{(hr * 60 + 330) % 60:02d}",
                    "range_bp": _r(rb, 1), "cost_bp": _r(cb, 2),
                    "cost_pct_of_range": _r(cb / rb * 100 if rb else None, 1),
                    "volume_pct": _r(x.vol_share.mean() * 100, 1)})
    return out


# --------------------------------------------------------------- 2. memory
def memory(df):
    r = np.log(df.close).diff().dropna()
    # Ignore returns across the forex weekend gap and any data hole.
    gap = df.index.to_series().diff().dt.total_seconds().reindex(r.index) > 600
    r = r[~gap]
    v1 = r.var()
    vr = {}
    for q, label in ((3, "15m"), (6, "30m"), (12, "1h"), (24, "2h"), (48, "4h")):
        s = r.rolling(q).sum().iloc[q - 1::q]
        vr[label] = _r(s.var() / (q * v1))
    h = df.close.resample("1h").last().dropna()
    hr = np.log(h).diff()
    nxt = hr.shift(-1)
    ok = hr.notna() & nxt.notna()
    by_session = {}
    for name, hrs in (("asia 00-07 UTC", range(0, 7)), ("london 07-12", range(7, 12)),
                      ("overlap 12-16", range(12, 16)), ("ny late 16-21", range(16, 21)), ("rollover 21-24", range(21, 24))):
        m = ok & hr.index.hour.isin(list(hrs))
        by_session[name] = _r(np.corrcoef(hr[m], nxt[m])[0, 1]) if m.sum() > 50 else None
    return {"variance_ratio": vr, "next_hour_autocorr": _r(np.corrcoef(hr[ok], nxt[ok])[0, 1]),
            "next_hour_autocorr_by_session": by_session,
            "read": "variance ratio above 1 = moves extend (trend), below 1 = moves fade (mean reversion)"}


# ----------------------------------------------------------------- 3. days
def daily(df, sym):
    # Forex days run from the 17:00 New York close; crypto days are UTC days.
    if is_crypto(sym):
        key = df.index.floor("1D")
    else:
        ny = df.index.tz_convert("America/New_York")
        key = (ny + pd.Timedelta(hours=7)).floor("1D").tz_localize(None)
    d = df.groupby(key).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                            close=("close", "last"), bars=("close", "size"))
    return d[d.bars >= (200 if is_crypto(sym) else 150)]


def days(df, sym):
    d = daily(df, sym)
    pdh, pdl = d.high.shift(), d.low.shift()
    atr = (d.high - d.low).rolling(14).mean().shift()
    up = d.high > pdh
    dn = d.low < pdl
    valid = pdh.notna() & atr.notna()
    up, dn = up & valid, dn & valid
    held_up = up & (d.close > pdh)
    held_dn = dn & (d.close < pdl)
    beyond_up = ((d.high - pdh) / atr)[up]
    beyond_dn = ((pdl - d.low) / atr)[dn]
    n = int(valid.sum())
    return {
        "days": n,
        "broke_prior_high_pct": _r(up.sum() / n * 100, 1),
        "broke_prior_low_pct": _r(dn.sum() / n * 100, 1),
        "both_sides_pct": _r((up & dn).sum() / n * 100, 1),
        "inside_day_pct": _r((~up & ~dn & valid).sum() / n * 100, 1),
        "high_break_held_at_close_pct": _r(held_up.sum() / max(up.sum(), 1) * 100, 1),
        "low_break_held_at_close_pct": _r(held_dn.sum() / max(dn.sum(), 1) * 100, 1),
        "median_push_beyond_high_atr": _r(beyond_up.median(), 2),
        "median_push_beyond_low_atr": _r(beyond_dn.median(), 2),
    }


# ---------------------------------------------------------- trade engine
def simulate(high, low, close, entries, max_bars):
    """entries: list of (i, direction, entry, stop, target, cost). Walk forward
    from bar i+1 (bar i too for the stop, when entry happened inside bar i).
    Returns R multiple after cost for each trade."""
    out = []
    n = len(close)
    for i, d, e, s, t, cost, check_entry_bar in entries:
        risk = abs(e - s)
        if risk <= 0:
            continue
        if check_entry_bar and ((d > 0 and low[i] <= s) or (d < 0 and high[i] >= s)):
            out.append(-1 - cost / risk)
            continue
        j1 = min(i + 1 + max_bars, n)
        hs, ls = high[i + 1:j1], low[i + 1:j1]
        if not len(hs):
            continue
        if d > 0:
            stop_hit, tgt_hit = ls <= s, hs >= t
        else:
            stop_hit, tgt_hit = hs >= s, ls <= t
        si = np.argmax(stop_hit) if stop_hit.any() else 10 ** 9
        ti = np.argmax(tgt_hit) if tgt_hit.any() else 10 ** 9
        if si == ti == 10 ** 9:
            exit_px = close[j1 - 1]
            r = (exit_px - e) * d / risk
        elif si <= ti:
            r = -1.0
        else:
            r = abs(t - e) / risk
        out.append(r - cost / risk)
    return np.array(out)


def summarize(r):
    if not len(r):
        return {"trades": 0}
    wins = r > 0
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(eq)).min()
    losing = max((len(list(g)) for k, g in __import__("itertools").groupby(wins) if not k), default=0)
    return {"trades": int(len(r)), "win_pct": _r(wins.mean() * 100, 1), "avg_R": _r(r.mean()),
            "total_R": _r(r.sum(), 1), "max_drawdown_R": _r(dd, 1), "longest_losing_streak": int(losing)}


# ------------------------------------------------------------------ 4. ORB
def orb_entries(df, sym, open_local, tz, or_minutes=30, window_hours=4, k=2.0):
    loc = df.index.tz_convert(tz)
    hh, mm = map(int, open_local.split(":"))
    cost = round_trip_cost(df, sym).to_numpy()
    high, low, close = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    start_mask = (loc.hour == hh) & (loc.minute == mm)
    entries = []
    or_bars = or_minutes // 5
    win = window_hours * 12
    for i in np.flatnonzero(start_mask):
        if loc[i].weekday() >= 5 and not is_crypto(sym):
            continue
        j = i + or_bars
        if j + win >= len(close):
            break
        if (df.index[j] - df.index[i]) > pd.Timedelta(minutes=or_minutes + 10):
            continue                                        # data hole
        hi, lo = high[i:j].max(), low[i:j].min()
        width = hi - lo
        if width <= 0:
            continue
        for b in range(j, j + win):
            if high[b] > hi or low[b] < lo:
                if high[b] > hi and low[b] < lo:
                    break                                   # both sides in one bar: no clean signal
                d = 1 if high[b] > hi else -1
                e = hi if d > 0 else lo
                s = lo if d > 0 else hi
                entries.append((b, d, e, s, e + d * k * width, cost[b], True))
                break
    return entries


def orb(df, sym):
    sessions = ({"crypto 00:00 UTC": ("00:00", "UTC"), "US open 09:30 NY": ("09:30", "America/New_York")}
                if is_crypto(sym) else
                {"London 08:00": ("08:00", "Europe/London"), "New York 08:00": ("08:00", "America/New_York")})
    out = {}
    for name, (t, tz) in sessions.items():
        res = {}
        for per, part in periods(df).items():
            if len(part) < 1000:
                continue
            h, l, c = part.high.to_numpy(), part.low.to_numpy(), part.close.to_numpy()
            res[per] = {f"{k}R": summarize(simulate(h, l, c, orb_entries(part, sym, t, tz, k=k), 48))
                        for k in TARGETS}
        out[name] = res
    return out


# ------------------------------------------------------------------ 5. BOS
def bos(df, sym, k_list=TARGETS, side=2):
    out = {}
    for per, part5 in periods(df).items():
        if len(part5) < 3000:
            continue
        p = part5.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        cost15 = round_trip_cost(part5, sym).resample("15min").mean().reindex(p.index).ffill().to_numpy()
        h, l, c = p.high.to_numpy(), p.low.to_numpy(), p.close.to_numpy()
        n = len(c)
        win = 2 * side + 1
        hmax = pd.Series(h).rolling(win, center=True).max().to_numpy()
        lmin = pd.Series(l).rolling(win, center=True).min().to_numpy()
        is_sh, is_sl = h == hmax, l == lmin
        follow = {k: [] for k in k_list}
        fade = {k: [] for k in k_list}
        last_sh = last_sl = None
        used_sh = used_sl = None
        for i in range(n):
            # a swing at bar i-side is confirmed now
            jc = i - side
            if jc >= 0:
                if is_sh[jc]:
                    last_sh, used_sh = jc, False
                if is_sl[jc]:
                    last_sl, used_sl = jc, False
            if last_sh is None or last_sl is None:
                continue
            sh, sl = h[last_sh], l[last_sl]
            if not used_sh and h[i] > sh:
                used_sh = True
                if c[i] > sh:                                # break and close above: follow long
                    e, s = c[i], sl
                    for k in k_list:
                        follow[k].append((i, 1, e, s, e + k * (e - s), cost15[i], False))
                else:                                        # wick through, close back below: fade short
                    e, s = c[i], h[i]
                    for k in k_list:
                        fade[k].append((i, -1, e, s, e - k * (s - e), cost15[i], False))
            if not used_sl and l[i] < sl:
                used_sl = True
                if c[i] < sl:
                    e, s = c[i], sh
                    for k in k_list:
                        follow[k].append((i, -1, e, s, e - k * (s - e), cost15[i], False))
                else:
                    e, s = c[i], l[i]
                    for k in k_list:
                        fade[k].append((i, 1, e, s, e + k * (e - s), cost15[i], False))
        # Skip setups whose risk is under 3x the cost: no edge survives that.
        def keep(es):
            return [x for x in es if abs(x[2] - x[3]) >= 3 * x[5]]
        out[per] = {"follow_break": {f"{k}R": summarize(simulate(h, l, c, keep(follow[k]), 32)) for k in k_list},
                    "fade_wick": {f"{k}R": summarize(simulate(h, l, c, keep(fade[k]), 32)) for k in k_list}}
    return out


# ------------------------------------------------------------------ 6. vol
def vol(df, sym):
    d = daily(df, sym)
    rng = (d.high - d.low) / d.close * 100
    wd = rng.groupby(pd.to_datetime(d.index).weekday).median()
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {"range_pct_median": _r(rng.median(), 2),
            "range_today_vs_yesterday_corr": _r(rng.corr(rng.shift()), 2),
            "range_pct_by_weekday": {names[i]: _r(v, 2) for i, v in wd.items()}}


def study(path: Path):
    sym = path.name.split("_5m")[0]
    df = load(path)
    print(f"{sym}: {len(df):,} bars {df.index[0]} to {df.index[-1]}", file=sys.stderr, flush=True)
    res = {"symbol": sym, "bars": len(df), "from": str(df.index[0]), "to": str(df.index[-1])}
    res["hours"] = hours(df, sym)
    res["memory"] = {per: memory(p) for per, p in periods(df).items() if len(p) > 2000}
    res["days"] = {per: days(p, sym) for per, p in periods(df).items() if len(p) > 2000}
    res["orb"] = orb(df, sym)
    res["bos"] = bos(df, sym)
    res["vol"] = vol(df, sym)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    want = {s for s in a.symbols.split(",") if s}
    files = sorted(Path(a.data).glob("*_5m.csv.gz"))
    results = [study(f) for f in files if not want or f.name.split("_5m")[0] in want]
    Path(a.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
