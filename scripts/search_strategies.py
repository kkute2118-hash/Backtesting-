#!/usr/bin/env python3
"""Rank every searched strategy on 2021-24 only, then show its 2025-26 result.

Inputs: the trend grid (scripts/search_trend_grid.py) and the liquidity
framework's recorded setups (scripts/search_liquidity_runs.py). For the
liquidity framework, every combination of filters on the recorded features is
a candidate: event family, score floor, session, HTF alignment, strong MSB on
reversals, FVG, premium/discount location. Each candidate is evaluated on
market groups. A candidate qualifies on 2021-24 alone (enough trades, at
least 3 of 4 years positive, positive average); qualifiers are ranked by R
a year in 2021-24. The 2025-26 hold-out is reported, never used to choose.

Usage: python scripts/search_strategies.py TREND.csv.gz LIQ1.csv.gz [LIQ2.csv.gz ...] OUT_PREFIX
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

SEL_YEARS = (2021, 2022, 2023, 2024)
HOLD_YEARS = (2025, 2026)
SEL_SPAN = 3 + 5 / 12        # Aug 2021 - Dec 2024
HOLD_SPAN = 1 + 9 / 12       # Jan 2025 - Sep 2026
GROUPS = {
    "crypto3": ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    "crypto3+gold": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD"),
    "gold": ("XAUUSD",),
    "fx4": ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"),
    "fx4+gold": ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"),
    "all8": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"),
}


def summarize(yearly: pd.DataFrame, keys: list[str], min_sel: int) -> pd.DataFrame:
    """yearly: keys + year, trades, sum_r -> one row per key with sel/hold stats."""
    sel = yearly[yearly.year.isin(SEL_YEARS)]
    hold = yearly[yearly.year.isin(HOLD_YEARS)]
    s = sel.groupby(keys).agg(n_sel=("trades", "sum"), r_sel=("sum_r", "sum"))
    pos = sel.groupby(keys + ["year"]).sum_r.sum().gt(0).groupby(level=keys).sum().rename("pos_years")
    h = hold.groupby(keys).agg(n_hold=("trades", "sum"), r_hold=("sum_r", "sum"))
    out = s.join(pos).join(h).fillna({"n_hold": 0, "r_hold": 0.0}).reset_index()
    out["avg_sel"] = out.r_sel / out.n_sel
    out["avg_hold"] = out.r_hold / out.n_hold.replace(0, np.nan)
    out["r_year_sel"] = out.r_sel / SEL_SPAN
    out["r_year_hold"] = out.r_hold / HOLD_SPAN
    out["qualifies"] = (out.n_sel >= min_sel) & (out.pos_years >= 3) & (out.avg_sel > 0)
    return out


def grouped(yearly: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    parts = []
    for g, syms in GROUPS.items():
        x = yearly[yearly.symbol.isin(syms)].groupby(keys + ["year"])[["trades", "sum_r"]].sum().reset_index()
        x["group"] = g
        parts.append(x)
    return pd.concat(parts, ignore_index=True)


def trend(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    out = summarize(grouped(d, ["config"]), ["config", "group"], min_sel=40)
    out["family"] = "trend"
    return out


def liquidity(paths: list[str]) -> pd.DataFrame:
    d = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    d["entry_time"] = pd.to_datetime(d.entry_time, utc=True)
    d["year"] = d.entry_time.dt.year
    hour = d.entry_time.dt.hour + d.entry_time.dt.minute / 60
    london_ny = ((hour >= 6) & (hour < 8)) | ((hour >= 12) & (hour < 16))   # 11:30-13:30, 17:30-21:30 IST
    filters = {
        "event": {"any": True, "run": d.family == "continuation", "sweep": d.family == "reversal"},
        "score": {f">={s}": d.score >= s for s in (0, 55, 65, 75)},
        "session": {"any": True, "london+ny": london_ny, "ny": (hour >= 12) & (hour < 16)},
        "htf": {"any": True, "aligned": d.htf_aligned.astype(bool)},
        "msb": {"any": True, "strong": (d.msb == "strong") | (d.family == "continuation")},
        "fvg": {"any": True, "fvg": d.fvg.astype(bool)},
        "location": {"any": True, "pd_ok": d.discount_ok.astype(bool)},
    }
    variants = d.variant.astype("category")
    v_codes = variants.cat.codes.to_numpy()
    symbols = d.symbol.astype("category")
    s_codes = symbols.cat.codes.to_numpy()
    years = d.year.to_numpy()
    y0 = years.min()
    nv, ns, ny = len(variants.cat.categories), len(symbols.cat.categories), years.max() - y0 + 1
    cell = (v_codes * ns + s_codes) * ny + (years - y0)
    r = d.r.to_numpy()
    rows = []
    names = list(filters)
    for combo in itertools.product(*(filters[k].items() for k in names)):
        m = np.ones(len(d), bool)
        for _, cond in combo:
            if cond is not True:
                m &= np.asarray(cond)
        cnt = np.bincount(cell[m], minlength=nv * ns * ny)
        sr = np.bincount(cell[m], weights=r[m], minlength=nv * ns * ny)
        label = "|".join(f"{k}={lab}" for k, (lab, _) in zip(names, combo))
        nz = np.nonzero(cnt)[0]
        for c_ in nz:
            v, rest = divmod(c_, ns * ny)
            s_, y = divmod(rest, ny)
            rows.append((f"{variants.cat.categories[v]}|{label}", symbols.cat.categories[s_], int(y0 + y),
                         int(cnt[c_]), float(sr[c_])))
    yearly = pd.DataFrame(rows, columns=["config", "symbol", "year", "trades", "sum_r"])
    out = summarize(grouped(yearly, ["config"]), ["config", "group"], min_sel=150)
    out["family"] = "liquidity"
    return out


def main():
    trend_path, liq_paths, prefix = sys.argv[1], sys.argv[2:-1], sys.argv[-1]
    res = pd.concat([trend(trend_path), liquidity(liq_paths)], ignore_index=True)
    res.to_csv(f"{prefix}_all.csv.gz", index=False)
    q = res[res.qualifies].sort_values("r_year_sel", ascending=False)
    cols = ["family", "group", "config", "n_sel", "avg_sel", "r_year_sel", "pos_years",
            "n_hold", "avg_hold", "r_year_hold"]
    pd.set_option("display.width", 250, "display.max_colwidth", 120)
    print(f"candidates: {len(res):,}  qualifying on 2021-24: {len(q):,}")
    print("held-out 2025-26 positive among qualifiers:", f"{(q.r_hold > 0).mean():.0%}")
    for fam in ("trend", "liquidity"):
        print(f"\n=== top 15 {fam} by 2021-24 R a year (2025-26 shown, not used)")
        print(q[q.family == fam][cols].head(15).round(2).to_string(index=False))
    q[cols].head(500).to_csv(f"{prefix}_top.csv", index=False)


if __name__ == "__main__":
    main()
