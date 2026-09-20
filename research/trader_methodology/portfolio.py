"""Rs 1,00,000 portfolio: raw scan against the filtered scan.

Per-trade averages hide the two things that decide what a real account makes:
you cannot take every signal (capital is finite), and a trade you do take
blocks a slot while it runs. A strategy firing 29 signals a day and one firing
one a day look very different per trade and can look identical per year.

So this walks the calendar day by day. Free slot, take the best available
signal; no free slot, the signal is simply missed, exactly as it would be.

Costs are charged on every fill. Position size is equity/slots, so wins
compound and losses shrink the next position.
"""

from __future__ import annotations
import argparse, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
COST_PCT = 0.593          # realistic round trip, see costs.py


def load():
    r = pd.read_csv(os.path.join(HERE, "rank_results.csv"))
    e = pd.read_csv(os.path.join(HERE, "entry_results.csv"))
    bars = e[["symbol", "strategy", "date", "imm_bars"]].drop_duplicates(
        ["symbol", "strategy", "date"])
    d = r.merge(bars, on=["symbol", "strategy", "date"], how="left")
    d["imm_bars"] = d.imm_bars.fillna(d.imm_bars.median()).astype(int)
    d["date"] = pd.to_datetime(d.date)
    d["kept"] = (~d.single_tower.astype(bool)) & d.cb_purity.between(0.30, 0.70) \
        & d.avg_turnover_20.between(100, 400)
    return d.sort_values("date")


def simulate(sig: pd.DataFrame, capital=100_000.0, slots=3, cost=COST_PCT,
             rank_col="score"):
    """Day-by-day with a fixed number of slots.

    Ties inside a day are broken by `rank_col` so the arms differ only in
    which signals they are allowed to see, not in how they queue.
    """
    if sig.empty:
        return {"final": capital, "trades": 0, "ret_pct": 0.0, "missed": 0,
                "win": np.nan, "maxdd": 0.0, "exposure": 0.0}

    equity = capital
    free_on = np.zeros(slots)          # calendar day index each slot frees up
    days = sorted(sig.date.unique())
    day_ix = {d: i for i, d in enumerate(days)}
    curve, trades, missed, wins, busy_days = [], 0, 0, 0, 0

    for d in days:
        i = day_ix[d]
        todays = sig[sig.date == d].sort_values(rank_col, ascending=False)
        busy_days += int((free_on > i).sum())
        for _, row in todays.iterrows():
            openable = np.where(free_on <= i)[0]
            if not len(openable):
                missed += len(todays) - trades if False else 1
                continue
            s = openable[0]
            size = equity / slots
            pnl = size * (row.ret - cost) / 100.0
            equity += pnl
            wins += int(row.ret - cost > 0)
            trades += 1
            free_on[s] = i + max(int(row.imm_bars), 1)
        curve.append(equity)

    curve = np.array(curve)
    peak = np.maximum.accumulate(curve)
    maxdd = float(((peak - curve) / peak).max() * 100) if len(curve) else 0.0
    return {"final": equity, "trades": trades, "ret_pct": (equity / capital - 1) * 100,
            "missed": missed, "win": 100 * wins / trades if trades else np.nan,
            "maxdd": maxdd, "exposure": 100 * busy_days / (len(days) * slots)}


def row(lbl, r, years):
    cagr = ((r["final"] / 100_000.0) ** (1 / years) - 1) * 100 if r["final"] > 0 else -100
    return (f"  {lbl:26s} Rs {r['final']:>10,.0f}   {r['ret_pct']:+7.1f}%   "
            f"{cagr:+6.1f}%   {r['trades']:5d}   {r['win']:5.1f}%   "
            f"{r['maxdd']:5.1f}%   {r['missed']:6d}")


def header(title):
    print()
    print("=" * 104)
    print(title)
    print("=" * 104)
    print(f"  {'arm':26s} {'final':>13s}   {'total':>7s}   {'CAGR':>6s}   "
          f"{'trades':>5s}   {'win':>5s}   {'maxDD':>5s}   {'missed':>6s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slots", type=int, default=3)
    ap.add_argument("--capital", type=float, default=100_000.0)
    a = ap.parse_args()

    d = load()
    span_days = (d.date.max() - d.date.min()).days
    years = max(span_days / 365.25, 0.5)
    print(f"Rs {a.capital:,.0f} capital, {a.slots} concurrent slots, "
          f"Rs {a.capital/a.slots:,.0f} per position (compounding)")
    print(f"Costs {COST_PCT}% round trip. Period {d.date.min():%Y-%m-%d} to "
          f"{d.date.max():%Y-%m-%d} ({years:.2f} years). Fixture: 161 symbols.")

    header("ALL FIVE STRATEGIES")
    print(row("raw scan", simulate(d, a.capital, a.slots), years))
    print(row("filtered", simulate(d[d.kept], a.capital, a.slots), years))

    header("PER STRATEGY - raw scan vs filtered")
    for s in sorted(d.strategy.unique()):
        x = d[d.strategy == s]
        print(row(f"{s} raw", simulate(x, a.capital, a.slots), years))
        print(row(f"{s} filtered", simulate(x[x.kept], a.capital, a.slots), years))
        print()

    header("COMBINATIONS, FILTERED")
    for lbl, ss in (("S4+S5", ["S4", "S5"]),
                    ("S1+S4+S5", ["S1", "S4", "S5"]),
                    ("all but S3", ["S1", "S2", "S4", "S5"]),
                    ("all five", ["S1", "S2", "S3", "S4", "S5"])):
        print(row(lbl, simulate(d[d.kept & d.strategy.isin(ss)], a.capital, a.slots), years))

    header("HELD-OUT YEAR ONLY (2026) - the bands never saw it")
    te = d[d.year == 2026]
    yrs26 = max((te.date.max() - te.date.min()).days / 365.25, 0.5)
    print(row("raw scan", simulate(te, a.capital, a.slots), yrs26))
    print(row("filtered", simulate(te[te.kept], a.capital, a.slots), yrs26))
    print(row("filtered, all but S3",
              simulate(te[te.kept & (te.strategy != "S3")], a.capital, a.slots), yrs26))
    print(row("filtered, S4+S5",
              simulate(te[te.kept & te.strategy.isin(["S4", "S5"])], a.capital, a.slots), yrs26))

    header("SLOT COUNT SENSITIVITY (filtered, all five, whole period)")
    for n in (1, 2, 3, 4, 5, 8):
        print(row(f"{n} slot(s)", simulate(d[d.kept], a.capital, n), years))


if __name__ == "__main__":
    main()
