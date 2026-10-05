#!/usr/bin/env python3
"""Account simulation of the finalists from scripts/search_strategies.py.

Rebuilds the trades of the chosen trend configs with search_trend_grid's
engine, takes the liquidity framework's trades from its recorded setups, and
compounds a Rs 10,000 account at a fixed % risk of current equity per trade,
with overlapping positions (risk is fixed at entry, P/L booked at exit).

Usage: python scripts/search_finalists.py DATA_DIR LIQ.csv.gz [LIQ.csv.gz ...] OUT_PREFIX
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import search_trend_grid as g  # noqa: E402

TREND = {
    "T1 trend 4h 40/30 stop1.5 (best trend)": ("4h", 40, 30, 1.5, 0, 0, 1, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD")),
    "T0 today's rules 4h 55/20 stop2 sma200": ("4h", 55, 20, 2.0, 200, 0, 1, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD")),
}
LIQ = {"L1 liquidity run-retest London+NY (best liquidity)":
       ("intraday|limit|rr1.5|buf0.1", ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"))}
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def trend_trades(data: Path, tf, n_in, n_out, stop_k, trend, em, dr, syms) -> pd.DataFrame:
    out = []
    for sym in syms:
        df, side, lim, fund_day = g.load(data, sym)
        d1, b = g.bars(df, "1D"), g.bars(df, tf)
        day = b.index.floor("1D")
        per_day = 6 if tf == "4h" else 1
        fund = (fund_day.reindex(day).fillna(fund_day.mean()).to_numpy() / per_day
                if fund_day is not None else np.zeros(len(b)))
        tr = np.maximum(b.high - b.low, np.maximum(abs(b.high - b.close.shift()), abs(b.low - b.close.shift())))
        atr = tr.rolling(20).mean().to_numpy()
        start = b.index >= pd.Timestamp("2021-08-01", tz="UTC")
        if trend:
            sma = d1.close.rolling(trend).mean()
            up = (d1.close > sma).shift(1).reindex(day).fillna(False).to_numpy().astype(bool) & start
            dn = (d1.close < sma).shift(1).reindex(day).fillna(False).to_numpy().astype(bool) & start
        else:
            up = dn = start
        o, h, l, c = (b[k].to_numpy() for k in ("open", "high", "low", "close"))
        idx, eidx, r, _ = g.run(o, h, l, c, atr, b.high.rolling(n_in).max().shift().to_numpy(),
                          b.low.rolling(n_in).min().shift().to_numpy(), b.low.rolling(n_out).min().shift().to_numpy(),
                          b.high.rolling(n_out).max().shift().to_numpy(), up, dn, fund, side, lim,
                          stop_k, em, dr, 6 if tf == "4h" else 1)
        out.append(pd.DataFrame({"symbol": sym, "entry_time": b.index[eidx], "exit_time": b.index[idx], "r": r}))
    return pd.concat(out, ignore_index=True)


def account(trades: pd.DataFrame, risk: float) -> dict:
    ev = pd.concat([pd.DataFrame({"t": trades.entry_time, "k": 0, "i": trades.index}),
                    pd.DataFrame({"t": trades.exit_time, "k": 1, "i": trades.index})]).sort_values(["t", "k"])
    eq, peak, dd, at_risk = 10_000.0, 10_000.0, 0.0, {}
    for t, k, i in ev.itertuples(index=False):
        if k == 0:
            at_risk[i] = eq * risk
        else:
            eq += at_risk.pop(i) * trades.r.at[i]
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak)
    years = (trades.exit_time.max() - trades.entry_time.min()).days / 365.25
    return {"final_rs": round(eq), "cagr_pct": round(((eq / 10_000) ** (1 / years) - 1) * 100, 1) if eq > 0 else -100,
            "max_dd_pct": round(dd * 100, 1)}


def main():
    data, liq_paths, prefix = Path(sys.argv[1]), sys.argv[2:-1], sys.argv[-1]
    systems = {name: trend_trades(data, *spec) for name, spec in TREND.items()}
    liq = pd.concat([pd.read_csv(p) for p in liq_paths], ignore_index=True)
    for name, (variant, syms) in LIQ.items():
        x = liq[(liq.variant == variant) & (liq.family == "continuation") & liq.symbol.isin(syms)].copy()
        x["entry_time"] = pd.to_datetime(x.entry_time, utc=True)
        x["exit_time"] = pd.to_datetime(x.exit_time, utc=True)
        hour = x.entry_time.dt.hour + x.entry_time.dt.minute / 60
        x = x[((hour >= 6) & (hour < 8)) | ((hour >= 12) & (hour < 16))]
        systems[name] = x[["symbol", "entry_time", "exit_time", "r"]].reset_index(drop=True)
    systems["T1 + L1 together"] = pd.concat([systems[k] for k in systems if k.startswith(("T1", "L1"))],
                                            ignore_index=True)
    rows = []
    for name, t in systems.items():
        t = t.sort_values("exit_time").reset_index(drop=True)
        yearly = t.groupby(t.exit_time.dt.year).r.agg(["size", "mean", "sum"]).round(2)
        print(f"\n{name}: {len(t)} trades, avg {t.r.mean():+.2f}R, win {100 * (t.r > 0).mean():.0f}%")
        print("  by year (trades, avg R, total R):",
              ", ".join(f"{y}: {int(s['size'])}/{s['mean']:+.2f}/{s['sum']:+.0f}" for y, s in yearly.iterrows()))
        for risk in (0.01, 0.02):
            for label, part in (("2021-24", t[t.exit_time < SPLIT]), ("2025-26", t[t.exit_time >= SPLIT]), ("all", t)):
                rows.append({"system": name, "risk_pct": risk * 100, "period": label, "trades": len(part),
                             **account(part.reset_index(drop=True), risk)})
    res = pd.DataFrame(rows)
    res.to_csv(f"{prefix}_accounts.csv", index=False)
    pd.set_option("display.width", 200)
    print("\n" + res.to_string(index=False))


if __name__ == "__main__":
    main()
