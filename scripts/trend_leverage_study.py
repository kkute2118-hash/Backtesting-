#!/usr/bin/env python3
"""Leverage caps of the live 4h trend paper book, tested on real prices.

Runs the live book's own code (app.tasks.trend_paper.advance and indicators)
bar by bar over 2021-2026 5-minute history from the fx-crypto-data release, so
signals, retest entries, stops, exits and charges are exactly what the server
does. Position size is risk / stop distance, capped at a multiple of equity;
the cap does not change any trade's R, only its weight, so every cap is
compared on the same trades. Equity compounds trade by trade in exit order,
as trend_paper._equity does.

Selection period 2021-08 to 2024-12, hold-out 2025-01 to 2026-10.

Written for the book's rules before 5 Oct 2026 (commit 628d155: 55/20, retest
entry, 2 ATR, leverage tiers); the tiers and assumed win rates are copied here
so it still reproduces research/fx_crypto/STEP13_LEVERAGE_REAL_DATA.md, but
trend_paper now runs the step 14 rules, so its signals differ.

Usage: python scripts/trend_leverage_study.py DATA_DIR OUT_PREFIX
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.tasks import trend_paper as tp  # noqa: E402

# XAUUSD (spot gold) stands in for the XAUUSDT perpetual, whose history starts Dec 2025.
MARKETS = {"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT", "SOLUSDT": "SOLUSDT", "XAUUSDT": "XAUUSD",
           "EURUSD": "EURUSD", "GBPUSD": "GBPUSD", "USDJPY": "USDJPY", "AUDUSD": "AUDUSD"}
START = pd.Timestamp("2021-08-01", tz="UTC")
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
WIN_RATES = {"BTCUSDT": 0.42, "ETHUSDT": 0.40, "SOLUSDT": 0.38, "XAUUSDT": 0.39, "EURUSD": 0.41,
             "GBPUSD": 0.39, "USDCAD": 0.38, "USDJPY": 0.38, "AUDUSD": 0.37}
RISK = 0.02


def tier(sym: str, win_rate: float | None = None) -> float:
    w = WIN_RATES.get(sym, 0.39) if win_rate is None else win_rate
    return 8.0 if w > 0.45 else 6.0 if w > 0.40 else 5.0 if w > 0.37 else 3.0


LIVE_CAPS = {s: tier(s) for s in WIN_RATES}


def load(data: Path, file_sym: str):
    df = pd.read_csv(data / f"{file_sym}_5m.csv.gz", usecols=["time", "open", "high", "low", "close"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    return (tp._resample(df, "1D"), tp._resample(df, "4h"), tp._resample(df, "15min"))


def trades_for(sym: str, data: Path) -> list[dict]:
    d1, h4, m15 = load(data, MARKETS[sym])
    ind = tp.indicators(d1, h4)
    st = {"last15": str(m15.index[m15.index < START][-1]), "status": "flat"}
    tp.advance(st, ind, m15, sym)
    out = st.get("closed", [])
    for t in out:
        t["stop_pct"] = (t["entry"] - t["stop"]) / t["entry"]
    return out


def size_x(t: dict, cap: float) -> float:
    return min(RISK / t["stop_pct"], cap)


def simulate(trades: list[dict], caps: dict[str, float]) -> dict:
    trades = sorted(trades, key=lambda t: t["exit_time"])
    eq, peak, max_dd, worst = 1.0, 1.0, 0.0, 0.0
    for t in trades:
        change = size_x(t, caps[t["symbol"]]) * t["ret"]
        eq *= 1 + change
        worst = min(worst, change)
        peak = max(peak, eq)
        max_dd = max(max_dd, 1 - eq / peak)
    years = (pd.Timestamp(trades[-1]["exit_time"]) - pd.Timestamp(trades[0]["entry_time"])).days / 365.25
    # account exposure while several positions are open at once
    edges = sorted([(pd.Timestamp(t["entry_time"]), size_x(t, caps[t["symbol"]])) for t in trades]
                   + [(pd.Timestamp(t["exit_time"]), -size_x(t, caps[t["symbol"]])) for t in trades],
                   key=lambda e: (e[0], e[1]))
    open_x = peak_x = 0.0
    for _, dx in edges:
        open_x += dx
        peak_x = max(peak_x, open_x)
    return {"trades": len(trades), "multiple": round(eq, 2),
            "cagr_pct": round((eq ** (1 / years) - 1) * 100, 1) if eq > 0 and years > 0 else None,
            "max_dd_pct": round(max_dd * 100, 1), "worst_trade_pct": round(worst * 100, 1),
            "peak_exposure_x": round(peak_x, 1)}


def per_symbol(trades: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df["win"] = df.r > 0
    df["period"] = np.where(pd.to_datetime(df.exit_time, utc=True) < SPLIT, "2021-24", "2025-26")
    g = df.groupby(["symbol", "period"])
    out = pd.DataFrame({"trades": g.size(), "win_pct": (g.win.mean() * 100).round(1),
                        "avg_r": g.r.mean().round(2), "sum_r": g.r.sum().round(1),
                        "median_stop_pct": (g.stop_pct.median() * 100).round(2)}).reset_index()
    out["assumed_win_pct"] = out.symbol.map(lambda s: round(WIN_RATES[s] * 100, 1))
    out["live_cap_x"] = out.symbol.map(LIVE_CAPS)
    out["cap_binds_pct"] = [
        round(100 * float((RISK / df[(df.symbol == s) & (df.period == p)].stop_pct > LIVE_CAPS[s]).mean()), 1)
        for s, p in zip(out.symbol, out.period)]
    return out


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    trades = []
    for sym in MARKETS:
        ts = trades_for(sym, data)
        print(f"{sym}: {len(ts)} trades", flush=True)
        trades += ts
    pd.DataFrame(trades).to_csv(f"{prefix}_trades.csv", index=False)
    table = per_symbol(trades)
    table.to_csv(f"{prefix}_by_symbol.csv", index=False)
    print(table.to_string(index=False))

    sel = [t for t in trades if pd.Timestamp(t["exit_time"]) < SPLIT]
    hold = [t for t in trades if pd.Timestamp(t["exit_time"]) >= SPLIT]
    # the live tiering rule, fed real 2021-24 win rates instead of the assumed ones
    real_wr = {s: float(np.mean([t["r"] > 0 for t in sel if t["symbol"] == s])) for s in MARKETS}
    tiers_real = {s: tier(s, real_wr[s]) for s in MARKETS}
    policies = {"live tiers (assumed win rates)": LIVE_CAPS,
                "tiers from real 2021-24 win rates": tiers_real,
                **{f"flat cap {c}x": {s: float(c) for s in MARKETS} for c in (1, 2, 3, 5)},
                "no cap (2% risk only)": {s: 1e9 for s in MARKETS}}
    rows = []
    for name, caps in policies.items():
        for period, ts in (("2021-24", sel), ("2025-26", hold), ("all", trades)):
            rows.append({"policy": name, "period": period, **simulate(ts, caps)})
    res = pd.DataFrame(rows)
    res.to_csv(f"{prefix}_policies.csv", index=False)
    print(res.to_string(index=False))
    Path(f"{prefix}_meta.json").write_text(json.dumps(
        {"live_caps": LIVE_CAPS, "real_win_rates_2021_24": real_wr, "tiers_from_real": tiers_real}, indent=1))


if __name__ == "__main__":
    main()
