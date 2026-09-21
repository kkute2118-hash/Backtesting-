"""Select on DNA and turnover. Buy at the pivot. Keep OUR stop and target.

Everything his that has been tested so far was tested as a package, and the
package kept failing. This separates the two halves that were always moving
together:

    SELECTION  does "DNA first, then turnover" pick better stocks?
    RISK       does his demand-candle stop beat our flat 7%?

The last run said no to the second on S1/S2/S3 and yes on S4/S5. This run
drops his stop entirely - our 7% and our 3R on every arm - so the selection
is measured on its own, on the trade we already know how to price.

The pivot appears here as an ENTRY, which is its other role in his method and
one nothing here has tested. "Three entry types: value buy in the demand
zone..." (N-04). So instead of paying the close after a scan hit, rest a
limit at the demand candle's low and let price come back to it:

  E_CLOSE   the close after the signal bar, as in every earlier arm
  E_PIVOT   a limit at the demand candle low, live for WAIT bars. Filled at
            the limit, or at the open when a bar gaps through it. Never
            filled means NO TRADE, which is his rule and not an omission -
            "if you do not get the price at the best price, you're better off
            leaving it."

E_PIVOT buys lower, so on the same 7% stop the stop sits lower too and the 3R
target is nearer in rupees. That is the whole question: does waiting for the
price pay for the trades that never come back?

The gates, fixed before the run:

  DNA        typical move >= 8% over >= 5 clean legs
  TURNOVER   20-day average >= Rs 40 cr AND rising over the last 20 sessions

Both are read at the signal bar. Four arms times two gate settings, plus a
random same-n control, so "fewer trades did better" stays readable.

Scanner logic untouched.
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

FLAT_STOP = 0.07
R_TARGET = 3.0
MAX_HOLD = 120
LOOKBACK_DAYS = 2200
WARMUP = 300

DNA_MIN_MOVE = 8.0
DNA_MIN_LEGS = 5
TURNOVER_MIN_CR = 40.0
TURNOVER_DRIFT_MIN = 0.0
WAIT_BARS = (5, 10)


def exit_at(df, e, stop, tgt):
    for j in range(e, min(len(df), e + MAX_HOLD)):
        if float(df.low.iloc[j]) <= stop:
            return stop, "stop", j - e
        if tgt is not None and float(df.high.iloc[j]) >= tgt:
            return tgt, "target", j - e
    k = min(len(df) - 1, e + MAX_HOLD - 1)
    return float(df.close.iloc[k]), "timeout", k - e


def limit_fill(df, start, limit, wait):
    """First bar within `wait` that trades at or below `limit`.

    A bar that GAPS below the limit fills at its open, not at the limit: the
    order rests in the book overnight and the market opens where it opens.
    Filling at the limit there would invent a better price than the trade
    could have had, and it would flatter exactly the arm being tested.
    """
    for j in range(start, min(len(df), start + wait)):
        o = float(df.open.iloc[j])
        if o <= limit:
            return j, o
        if float(df.low.iloc[j]) <= limit:
            return j, limit
    return None, None


def build(symbols, core, tl, min_bars):
    rows = []
    for k, sym in enumerate(symbols):
        if k % 25 == 0:
            print(f"  {k}/{len(symbols)}", file=sys.stderr, flush=True)
        d = core.load_scan_dataset([sym], lookback_days=LOOKBACK_DAYS).get(sym)
        if d is None or len(d) < min_bars:
            continue
        d = d.sort_index()
        try:
            f = core.features_fast(str(sym), d).replace([np.inf, -np.inf], np.nan)
        except Exception:
            continue
        if f.empty:
            continue

        swings = tl.swing_low_positions(d.close)
        t = tl.turnover_cr(d.close, d.volume)
        L = tl.AUTHOR_AVERAGE_TURNOVER_LOOKBACK
        avg_prior = t.shift(1).rolling(L, min_periods=L).mean()
        drift = (avg_prior / avg_prior.shift(L) - 1.0) * 100.0

        for s in core.IMPLEMENTED_STRATEGIES:
            try:
                sig = core.strategy_signal(f, s).fillna(False).to_numpy()
            except Exception:
                continue
            for i in np.flatnonzero(sig):
                i = int(i)
                if i < WARMUP or i >= len(d) - 2:
                    continue
                e = i + 1
                close_entry = float(d.close.iloc[e])
                if close_entry <= 0:
                    continue

                dn = tl.dna(d.close, at=i, swings=swings)
                try:
                    piv = tl.pivot_low(d.low, d.close, d.open, i,
                                       search_from=tl.expansion_end(d.close, i))
                except Exception:
                    piv = None

                r = {
                    "symbol": sym, "strategy": f"S{s}",
                    "date": pd.Timestamp(d.index[i]).date().isoformat(),
                    "year": pd.Timestamp(d.index[i]).year,
                    "close_entry": close_entry,
                    "dna_move": dn["dna_move"], "dna_legs": dn["legs"],
                    "avg_turnover_20": (float(avg_prior.iloc[i])
                                        if np.isfinite(avg_prior.iloc[i]) else None),
                    "turnover_drift_pct": (float(drift.iloc[i])
                                           if np.isfinite(drift.iloc[i]) else None),
                    "pivot_raw": None if piv is None else float(piv),
                }

                # E_CLOSE: our stop, our target, paid at the close.
                stop = close_entry * (1 - FLAT_STOP)
                x, why, bars = exit_at(d, e, stop, close_entry + R_TARGET * (close_entry - stop))
                r["close_ret"] = (x - close_entry) / close_entry * 100
                r["close_exit"] = why
                r["close_bars"] = bars

                # E_PIVOT: rest a limit at the demand candle low.
                for w in WAIT_BARS:
                    r[f"piv{w}_ret"] = None
                    r[f"piv{w}_exit"] = None
                    r[f"piv{w}_bars"] = None
                    r[f"piv{w}_wait"] = None
                    if piv is None or not np.isfinite(piv) or piv >= close_entry:
                        continue
                    j, fill = limit_fill(d, e, float(piv), w)
                    if j is None:
                        r[f"piv{w}_exit"] = "never filled"
                        continue
                    st = fill * (1 - FLAT_STOP)
                    x, why, bars = exit_at(d, j + 1, st, fill + R_TARGET * (fill - st))
                    r[f"piv{w}_ret"] = (x - fill) / fill * 100
                    r[f"piv{w}_exit"] = why
                    # Bars from the SIGNAL, not from the fill: the slot is
                    # occupied from the day the order goes in.
                    r[f"piv{w}_bars"] = (j - i) + bars + 1
                    r[f"piv{w}_wait"] = j - e
                rows.append(r)
    return pd.DataFrame(rows)


def gates(df):
    dna = df.dna_move.notna() & (df.dna_move >= DNA_MIN_MOVE) & (df.dna_legs >= DNA_MIN_LEGS)
    to = (df.avg_turnover_20.notna() & (df.avg_turnover_20 >= TURNOVER_MIN_CR)
          & df.turnover_drift_pct.notna() & (df.turnover_drift_pct > TURNOVER_DRIFT_MIN))
    return dna, dna & to


def net(g):
    return g - C.round_trip_pct(100000.0 / 3, C.SLIPPAGE["realistic"])


def line(label, ret):
    if ret is None or len(ret) == 0:
        return f"{label:38s} (none)"
    g = float(ret.mean())
    return (f"{label:38s} n={len(ret):6d}  win={100*(ret>0).mean():5.1f}%  "
            f"gross={g:+6.3f}%  net={net(g):+6.3f}%")


def control(pool, n, col, draws=30):
    if len(pool) <= n or n < 20:
        return None
    m = [pool.sample(n=n, random_state=s)[col].mean() for s in range(draws)]
    return float(np.mean(m)), float(np.std(m))


def report(df, title):
    o = ["", "=" * 100, title, "=" * 100]
    o.append(f"signals {len(df):,} | symbols {df.symbol.nunique():,} | "
             f"{df.year.min()}-{df.year.max()}")
    o.append(f"OUR stop (7%) and OUR target (3R) on every arm. Costs at a "
             f"Rs 33,333 slot = {C.round_trip_pct(100000/3, C.SLIPPAGE['realistic']):.3f}% "
             f"round trip.")
    dna, both = gates(df)
    o.append("")
    o.append(f"gate 1  DNA >= {DNA_MIN_MOVE:.0f}% on >= {DNA_MIN_LEGS} legs      "
             f"{int(dna.sum()):7,d}  ({100*dna.mean():4.1f}%)")
    o.append(f"gate 2  + turnover >= {TURNOVER_MIN_CR:.0f} cr and rising  "
             f"{int(both.sum()):7,d}  ({100*both.mean():4.1f}%)")

    for gname, mask in (("NO GATES (every signal)", None),
                        ("DNA only", dna), ("DNA + TURNOVER", both)):
        d = df if mask is None else df[mask]
        o.append("")
        o.append("-" * 100)
        o.append(f"{gname}   n={len(d):,}")
        o.append("-" * 100)
        a = d[d.close_ret.notna()]
        o.append(line("  E_CLOSE  buy the close after the signal", a.close_ret))
        for w in WAIT_BARS:
            col = f"piv{w}_ret"
            b = d[d[col].notna()]
            filled = 100.0 * len(b) / max(len(d), 1)
            o.append(line(f"  E_PIVOT  limit at the pivot, {w:2d} bars", b[col])
                     + f"   filled {filled:4.1f}%")

    o.append("")
    o.append("=" * 100)
    o.append("Does the gate beat a random draw of the same size?")
    o.append("=" * 100)
    for w_label, col in [("E_CLOSE", "close_ret")] + [(f"E_PIVOT {w}", f"piv{w}_ret")
                                                      for w in WAIT_BARS]:
        pool = df[df[col].notna()]
        sel = df[both & df[col].notna()]
        c = control(pool, len(sel), col)
        if c is None:
            o.append(f"{w_label:14s} (too few)")
            continue
        o.append(f"{w_label:14s} gated={sel[col].mean():+6.3f}%  "
                 f"random same-n={c[0]:+6.3f}%  sd={c[1]:5.3f}  "
                 f"edge={sel[col].mean()-c[0]:+6.3f}%  "
                 f"({(sel[col].mean()-c[0])/c[1]:+5.1f} sd)")

    o.append("")
    o.append("=" * 100)
    o.append("Per strategy and per year: gated, E_PIVOT 10 bars vs E_CLOSE (gross %)")
    o.append("=" * 100)
    o.append(f"{'bucket':8s} {'all n':>8s} {'ALL close':>10s} | {'gated n':>8s} "
             f"{'gated close':>12s} {'gated pivot':>12s} {'pivot n':>8s}")
    for key, col in (("year", df.year), ("strategy", df.strategy)):
        o.append("-" * 100)
        for v in sorted(col.unique()):
            d = df[col == v]
            g = df[both & (col == v)]
            gp = g[g.piv10_ret.notna()]
            o.append(f"{str(v):8s} {len(d):8d} {d.close_ret.mean():+10.2f} | "
                     f"{len(g):8d} "
                     + (f"{g.close_ret.mean():+12.2f} " if len(g) else f"{'--':>12s} ")
                     + (f"{gp.piv10_ret.mean():+12.2f} {len(gp):8d}"
                        if len(gp) else f"{'--':>12s} {0:8d}"))

    o.append("")
    d = df[both]
    for w in WAIT_BARS:
        never = (d[f"piv{w}_exit"] == "never filled").sum()
        got = d[f"piv{w}_ret"].notna().sum()
        o.append(f"E_PIVOT {w:2d} bars: {got:,} filled, {never:,} never came back to the "
                 f"pivot, {len(d)-got-never:,} had no pivot at all")
    gp = d[d.piv10_ret.notna()]
    if len(gp):
        o.append(f"median wait to fill: {gp.piv10_wait.median():.0f} bars; "
                 f"median discount to the close: "
                 f"{100*(1 - (gp.pivot_raw/gp.close_entry)).median():.2f}%")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-bars", type=int, default=1100)
    ap.add_argument("--out", default=os.path.join(HERE, "dnaturnover_results.csv"))
    ap.add_argument("--title", default="DNA + turnover selection, pivot entry, OUR stop")
    a = ap.parse_args()

    from app.engine import core
    con = core._db()
    try:
        symbols = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' "
            "GROUP BY symbol HAVING COUNT(*)>=? ORDER BY symbol", (a.min_bars,))]
    finally:
        con.close()
    if a.sample and a.sample < len(symbols):
        rng = np.random.default_rng(a.seed)
        symbols = sorted(rng.choice(symbols, size=a.sample, replace=False).tolist())

    import importlib.util as u
    spec = u.spec_from_file_location(
        "trader_layer", os.path.join(ROOT, "backend", "app", "engine", "trader_layer.py"))
    tl = u.module_from_spec(spec); spec.loader.exec_module(tl)

    print(f"symbols: {len(symbols)}", file=sys.stderr)
    df = build(symbols, core, tl, a.min_bars)
    if df.empty:
        print("no signals"); return
    df.to_csv(a.out, index=False)
    print(report(df, a.title))
    print(f"\nrows -> {a.out}")


if __name__ == "__main__":
    main()
