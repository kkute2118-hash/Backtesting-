"""What each strategy does to a Rs 1 lakh account, strategy by strategy.

Per-trade percentages are not a result. A book with three slots cannot take
486,551 trades, and which trades it DOES take is decided by whichever signal
happened to arrive while a slot was free. That is the difference between a
backtest and an account, and on a small account it is most of the answer:
the earlier portfolio work found the binding constraint was trade count, not
selection.

So this runs an actual account. Chronological, one position per stock, slots
that block, compounding on the realised equity, and Indian costs charged on
the REAL position size rather than on a notional Rs 1 lakh - at a Rs 33,000
slot the Rs 20 brokerage cap does not bind and the cost is not the same
number.

Arms come from the backtests already run:

  FLAT7      our 7% stop, 3R target          the current book
  PIVOT      his demand-candle stop, 3R      backtest_smallsl.py
  PIVOT_MK   the same plus the marking gates
  FUNNEL     DNA -> turnover -> his stop, DNA target   backtest_dna_first.py

Reported per strategy and for all strategies together, at one, three and five
slots, because the slot count is the parameter a person actually chooses and
its effect here is larger than any filter tested.
"""

from __future__ import annotations

import argparse, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, HERE)

import costs as C

CAPITAL = 100_000.0
SLOT_COUNTS = (1, 3, 5)
SLIPPAGE = "realistic"

# The marking gates, same as in backtest_smallsl.py.
MK_MAX_SL_OVER_DNA = 0.6
MK_MIN_TURNOVER_SPIKE = 1.2


def calendar():
    """The NSE trading days the store knows about, as a position lookup.

    Exit dates are recorded as a number of bars held, and bars are trading
    days. Adding them as calendar days would push every exit over weekends and
    holidays and let positions occupy slots they had already left.
    """
    from app.engine import core
    con = core._db()
    try:
        days = [r[0] for r in con.execute(
            "SELECT DISTINCT dt FROM candles ORDER BY dt")]
    finally:
        con.close()
    return {d: i for i, d in enumerate(days)}, days


def simulate(trades, slots, capital=CAPITAL, seed=None):
    """One account. `trades` needs date_i, exit_i, symbol, ret_pct.

    Slots block: a signal arriving with every slot full is not taken, and it
    is not queued either. That is what actually happens to a person watching a
    scan with three positions already open.

    `seed` reshuffles the order signals are considered in WITHIN a day. On a
    three-slot book only a handful of the day's signals can be taken, so which
    one gets the slot is close to arbitrary - and the result swings on it. One
    path is an anecdote; see spread().
    """
    if trades.empty:
        return None
    if seed is None:
        t = trades.sort_values(["date_i", "symbol"], kind="stable")
    else:
        rng = np.random.default_rng(seed)
        t = (trades.assign(_k=rng.random(len(trades)))
                   .sort_values(["date_i", "_k"], kind="stable"))
    equity = capital
    open_pos = []                      # (exit_i, symbol, size, ret_pct)
    held = set()
    taken = skipped_slot = skipped_dup = 0
    curve = []                         # (date_i, equity) at each realisation
    wins = 0
    peak = equity
    max_dd = 0.0

    for row in t.itertuples():
        # Close everything that finished before this signal.
        still = []
        for exit_i, sym, size, ret in open_pos:
            if exit_i <= row.date_i:
                gross = size * ret / 100.0
                cost = size * C.round_trip_pct(size, C.SLIPPAGE[SLIPPAGE]) / 100.0
                equity += gross - cost
                if gross - cost > 0:
                    wins += 1
                held.discard(sym)
                curve.append((exit_i, equity))
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
            else:
                still.append((exit_i, sym, size, ret))
        open_pos = still

        if row.symbol in held:
            skipped_dup += 1
            continue
        if len(open_pos) >= slots:
            skipped_slot += 1
            continue
        size = equity / slots
        if size <= 0:
            skipped_slot += 1
            continue
        open_pos.append((row.exit_i, row.symbol, size, row.ret_pct))
        held.add(row.symbol)
        taken += 1

    for exit_i, sym, size, ret in open_pos:       # close the book
        gross = size * ret / 100.0
        cost = size * C.round_trip_pct(size, C.SLIPPAGE[SLIPPAGE]) / 100.0
        equity += gross - cost
        if gross - cost > 0:
            wins += 1
        curve.append((exit_i, equity))
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)

    if not taken:
        return None
    span_days = (t.date_i.max() - t.date_i.min()) or 1
    years = span_days / 250.0
    total = equity / capital - 1.0
    cagr = ((equity / capital) ** (1 / years) - 1.0) if years > 0 and equity > 0 else float("nan")
    return {
        "offered": len(t), "taken": taken, "skipped_slot": skipped_slot,
        "skipped_dup": skipped_dup, "win_pct": 100.0 * wins / taken,
        "final": equity, "total_pct": 100.0 * total, "cagr_pct": 100.0 * cagr,
        "max_dd_pct": 100.0 * max_dd, "years": years,
        "per_year": taken / years if years > 0 else float("nan"),
    }


def prepare(df, ret_col, bars_col, cal, mask=None):
    d = df if mask is None else df[mask]
    d = d[d[ret_col].notna() & d[bars_col].notna()].copy()
    d["date_i"] = d.date.map(cal)
    d = d[d.date_i.notna()]
    d["date_i"] = d.date_i.astype(int)
    d["exit_i"] = d.date_i + d[bars_col].astype(int)
    d["ret_pct"] = d[ret_col].astype(float)
    return d[["date_i", "exit_i", "symbol", "ret_pct", "strategy"]]


def spread(trades, slots, n=25):
    """The same account run n times with the within-day order reshuffled.

    Reported instead of a single path because the single path is not a
    measurement: with 40 trades a year and a payoff carried by a few winners,
    whether the book happened to hold the one that ran is decided by the
    arrival order, not by the strategy.
    """
    finals = []
    for seed in range(n):
        r = simulate(trades, slots, seed=seed)
        if r:
            finals.append(r["final"])
    if not finals:
        return None
    f = np.array(finals)
    return {"median": float(np.median(f)), "p10": float(np.percentile(f, 10)),
            "p90": float(np.percentile(f, 90)),
            "win_share": float((f > CAPITAL).mean()), "n": len(f)}


def table(name, prepped, out):
    out.append("")
    out.append("=" * 112)
    out.append(f"{name}   -   Rs {CAPITAL:,.0f} account")
    out.append("=" * 112)
    out.append(f"{'strategy':10s} {'slots':>5s} {'offered':>9s} {'taken':>7s} "
               f"{'/yr':>6s} {'win%':>6s} {'final Rs':>12s} {'CAGR%':>7s} "
               f"{'maxDD%':>7s} | {'median Rs':>11s} {'p10':>9s} {'p90':>9s} {'>1L':>5s}")
    strategies = ["ALL"] + sorted(prepped.strategy.unique())
    for strat in strategies:
        d = prepped if strat == "ALL" else prepped[prepped.strategy == strat]
        out.append("-" * 112)
        for slots in SLOT_COUNTS:
            r = simulate(d, slots)
            if r is None:
                out.append(f"{strat:10s} {slots:5d}        no trades")
                continue
            sp = spread(d, slots)
            tail = (f" | {sp['median']:11,.0f} {sp['p10']:9,.0f} {sp['p90']:9,.0f} "
                    f"{100*sp['win_share']:4.0f}%") if sp else ""
            out.append(
                f"{strat:10s} {slots:5d} {r['offered']:9,d} {r['taken']:7,d} "
                f"{r['per_year']:6.0f} {r['win_pct']:6.1f} {r['final']:12,.0f} "
                f"{r['cagr_pct']:+7.1f} {r['max_dd_pct']:7.1f}{tail}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smallsl", default=os.path.join(HERE, "smallsl_all.csv"))
    ap.add_argument("--dnafirst", default=os.path.join(HERE, "dnafirst_500.csv"))
    a = ap.parse_args()

    cal, days = calendar()
    print(f"calendar: {len(days)} trading days, {days[0]} to {days[-1]}", file=sys.stderr)
    out = []
    out.append(f"Costs charged per trade on the REAL position size at "
               f"{SLIPPAGE} slippage.")
    out.append("'final Rs' is one path, taking the day's signals in symbol order. "
               "The four columns after the bar are 25 runs of the same account with "
               "the within-day order reshuffled: median, 10th and 90th percentile, "
               "and the share of runs that finished above Rs 1 lakh. Trust those, "
               "not the single path.")
    out.append(f"At 3 slots a position is about Rs {CAPITAL/3:,.0f}, where the round trip "
               f"is {C.round_trip_pct(CAPITAL/3, C.SLIPPAGE[SLIPPAGE]):.3f}% "
               f"(against {C.round_trip_pct(CAPITAL, C.SLIPPAGE[SLIPPAGE]):.3f}% at Rs 1 lakh - "
               f"the Rs 20 brokerage cap stops binding on a small slot).")

    if os.path.exists(a.smallsl):
        cols = ["symbol", "strategy", "date", "flat_ret", "flat_bars",
                "pivot_ret", "pivot_bars", "pivot_sl_pct", "sl_vs_dna",
                "turnover_spike", "inside_zone"]
        df = pd.read_csv(a.smallsl, usecols=cols)
        print(f"smallsl: {len(df):,} signals", file=sys.stderr)
        table("FLAT7 - our 7% stop, 3R target (the current book)",
              prepare(df, "flat_ret", "flat_bars", cal), out)
        table("PIVOT - his demand-candle stop, 3R target",
              prepare(df, "pivot_ret", "pivot_bars", cal), out)
        mk = (df.pivot_ret.notna() & ~df.inside_zone.astype(bool)
              & (df.sl_vs_dna <= MK_MAX_SL_OVER_DNA)
              & (df.turnover_spike >= MK_MIN_TURNOVER_SPIKE))
        table("PIVOT_MK - his stop plus the marking gates",
              prepare(df, "pivot_ret", "pivot_bars", cal, mk), out)

    if os.path.exists(a.dnafirst):
        cols = ["symbol", "strategy", "date", "his_ret", "his_bars", "dna_move",
                "dna_legs", "avg_turnover_20", "turnover_drift_pct",
                "pivot_stop", "inside_zone"]
        d2 = pd.read_csv(a.dnafirst, usecols=cols)
        print(f"dnafirst: {len(d2):,} signals", file=sys.stderr)
        m = (d2.dna_move.notna() & (d2.dna_move >= 8.0) & (d2.dna_legs >= 5)
             & d2.avg_turnover_20.notna() & (d2.avg_turnover_20 >= 40.0)
             & d2.turnover_drift_pct.notna() & (d2.turnover_drift_pct > 0)
             & d2.pivot_stop.notna() & ~d2.inside_zone.astype(bool))
        table("FUNNEL - DNA, then turnover, then his stop and DNA target "
              "(500-stock sample)", prepare(d2, "his_ret", "his_bars", cal, m), out)

    print("\n".join(out))


if __name__ == "__main__":
    main()
