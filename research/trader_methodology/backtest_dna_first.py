"""His order, his rules: DNA first, then turnover, then the entry and its stop.

Everything before this ran his measures as a flat bundle of filters bolted
onto OUR trade: our flat 7% stop, our 3R target. That is not what he does, and
one difference matters more than all the filtering:

    "Profit target is set from DNA, not from a fixed R multiple."   (D-07)

A 3R target on a 5% stop asks for 15%. If the stock's typical up move is 9%,
that target is not reached by a normal move at all - it needs an exceptional
one. Every tight-stop test so far has been asking his stop to pay for our
target. This run lets the DNA set the target, which is the thing he actually
says, and the reason it is worth running again after a negative result.

THE FUNNEL, in his order, each step gating the next:

  1  DNA        the stock must HAVE a measurable character - legs, not a range
                ("never measure DNA inside a range", D-05) - and that character
                has to be worth trading. His stated daily band starts at 8%.
  2  TURNOVER   only then liquidity. Rs 1-2.5 cr is "extremely less" and
                Rs 80-90 cr is "pretty healthy"; our own floor is Rs 40 cr. The
                average must also be RISING through the move (L-07), which is
                the part he actually reads: "175, 200, 255".
  3  ENTRY+SL   the stop goes under the demand candle's low, never inside the
                demand zone, and must be proportionate to the DNA (S-02). No
                quality pivot means no trade at all (P-06).

  EXIT          target = one DNA move. Stop = the pivot. Not 3R.

Reward-to-risk is REPORTED at several minimums rather than cut at one, because
he gives the shape of that rule ("a 17-20% stop against a 25-30% DNA is
wrong") and no number, and picking one after seeing the answer is how the last
three constructions fooled themselves.

Entry is the close after the signal bar, as in every other arm here. Waiting
for his M10/inside-bar trigger was tested separately and cost 2.39 points
(FINDINGS_ENTRY.md); this run is about the stop and the target, so the entry
is held constant rather than changed at the same time.

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

MAX_HOLD = 120
LOOKBACK_DAYS = 2200
WARMUP = 300

# ---- step 1: DNA ---------------------------------------------------------
# 8% is the bottom of the daily band the lectures describe (8-20%). DERIVED
# from his examples, not a number he states as a rule.
DNA_MIN_MOVE = 8.0
# Enough legs for a median to mean anything. OURS.
DNA_MIN_LEGS = 5

# ---- step 2: turnover ----------------------------------------------------
# 40 is our existing entry floor; 80 is the level he calls "pretty healthy".
# Both are reported so the choice is visible rather than assumed.
TURNOVER_FLOORS = (40.0, 80.0)
# "the 20-day average RISING through the move" - his confirmation, cut at
# zero because rising is rising.
TURNOVER_DRIFT_MIN = 0.0

# ---- step 3: stop --------------------------------------------------------
RR_MINIMUMS = (0.0, 1.0, 2.0, 3.0)

FLAT_STOP = 0.07
R_TARGET = 3.0


def exit_at(df, e, stop, tgt):
    """Stop checked before target on every bar - a bar that does both is a
    stop, because nobody could have known it would come back."""
    for j in range(e, min(len(df), e + MAX_HOLD)):
        if float(df.low.iloc[j]) <= stop:
            return stop, "stop", j - e
        if tgt is not None and float(df.high.iloc[j]) >= tgt:
            return tgt, "target", j - e
    k = min(len(df) - 1, e + MAX_HOLD - 1)
    return float(df.close.iloc[k]), "timeout", k - e


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
                entry = float(d.close.iloc[e])
                if entry <= 0:
                    continue

                dn = tl.dna(d.close, at=i, swings=swings)
                piv = None
                try:
                    piv = tl.pivot_low(d.low, d.close, d.open, i,
                                       search_from=tl.expansion_end(d.close, i))
                except Exception:
                    piv = None

                av = float(avg_prior.iloc[i]) if np.isfinite(avg_prior.iloc[i]) else None
                dr = float(drift.iloc[i]) if np.isfinite(drift.iloc[i]) else None
                sp = (float(t.iloc[i]) / av) if av else None

                r = {
                    "symbol": sym, "strategy": f"S{s}",
                    "date": pd.Timestamp(d.index[i]).date().isoformat(),
                    "year": pd.Timestamp(d.index[i]).year,
                    "entry": entry,
                    "dna_move": dn["dna_move"], "dna_candle": dn["dna_candle"],
                    "dna_legs": dn["legs"],
                    "avg_turnover_20": av, "turnover_drift_pct": dr,
                    "turnover_spike": sp,
                    "pivot_raw": None if piv is None else float(piv),
                }

                # BASELINE, on every signal: our stop, our target.
                flat = entry * (1 - FLAT_STOP)
                x, why, _ = exit_at(d, e, flat, entry + R_TARGET * (entry - flat))
                r["base_ret"] = (x - entry) / entry * 100
                r["base_r"] = (x - entry) / (entry - flat)

                stop = None
                if piv is not None and np.isfinite(piv) and piv < entry:
                    stop = float(piv) * (1.0 - tl.PARAMS["STOP_BUFFER"])
                r["pivot_stop"] = stop
                r["sl_pct"] = None if stop is None else (entry - stop) / entry * 100
                r["inside_zone"] = bool(piv is not None and flat > piv)
                r["rr"] = (dn["dna_move"] / r["sl_pct"]
                           if (stop is not None and dn["dna_move"] and r["sl_pct"]) else None)

                # HIS trade: pivot stop, DNA target.
                if stop is not None and dn["dna_move"]:
                    tgt = entry * (1 + dn["dna_move"] / 100.0)
                    x, why, bars = exit_at(d, e, stop, tgt)
                    r["his_ret"] = (x - entry) / entry * 100
                    r["his_r"] = (x - entry) / (entry - stop)
                    r["his_exit"] = why
                    r["his_bars"] = bars
                # The same stop with OUR target, so the target and the stop can
                # be told apart instead of moving together.
                if stop is not None:
                    x, why, _ = exit_at(d, e, stop, entry + R_TARGET * (entry - stop))
                    r["stop3r_ret"] = (x - entry) / entry * 100
                    r["stop3r_r"] = (x - entry) / (entry - stop)
                    r["stop3r_exit"] = why
                # And our stop with HIS target, the other half of the pair.
                if dn["dna_move"]:
                    x, why, _ = exit_at(d, e, flat, entry * (1 + dn["dna_move"] / 100.0))
                    r["flatdna_ret"] = (x - entry) / entry * 100
                    r["flatdna_r"] = (x - entry) / (entry - flat)
                    r["flatdna_exit"] = why
                rows.append(r)
    return pd.DataFrame(rows)


def net(g):
    return g - C.round_trip_pct(100000.0, C.SLIPPAGE["realistic"])


def steps(df, turnover_floor):
    """The funnel, in his order. Returns the mask after each step."""
    m1 = df.dna_move.notna() & (df.dna_move >= DNA_MIN_MOVE) & (df.dna_legs >= DNA_MIN_LEGS)
    m2 = m1 & df.avg_turnover_20.notna() & (df.avg_turnover_20 >= turnover_floor) \
        & df.turnover_drift_pct.notna() & (df.turnover_drift_pct > TURNOVER_DRIFT_MIN)
    m3 = m2 & df.pivot_stop.notna() & ~df.inside_zone
    return m1, m2, m3


def stat(label, ret, r, sl=None, extra=""):
    if ret is None or len(ret) == 0:
        return f"{label:34s} (none)"
    g = float(ret.mean())
    return (f"{label:34s} n={len(ret):6d}  win={100*(ret>0).mean():5.1f}%  "
            + (f"SL={sl:5.2f}%  " if sl is not None else " " * 11)
            + f"gross={g:+6.3f}%  net={net(g):+6.3f}%  R={float(r.mean()):+6.3f}{extra}")


def report(df, title):
    o = ["", "=" * 108, title, "=" * 108]
    o.append(f"signals {len(df):,} | symbols {df.symbol.nunique():,} | "
             f"{df.year.min()}-{df.year.max()}")
    o.append(f"costs: round trip {C.round_trip_pct(100000.0, C.SLIPPAGE['realistic']):.3f}% "
             f"of notional, subtracted from every net figure")
    o.append("")
    o.append("Is the TARGET the thing? Same signals, the four stop/target pairs:")
    o.append("-" * 108)
    a = df[df.base_ret.notna()]
    o.append(stat("our stop 7% + our target 3R", a.base_ret, a.base_r, 7.0))
    b = df[df.flatdna_ret.notna()]
    o.append(stat("our stop 7% + HIS target DNA", b.flatdna_ret, b.flatdna_r, 7.0))
    c = df[df.stop3r_ret.notna()]
    o.append(stat("HIS stop pivot + our target 3R", c.stop3r_ret, c.stop3r_r, c.sl_pct.mean()))
    e = df[df.his_ret.notna()]
    o.append(stat("HIS stop pivot + HIS target DNA", e.his_ret, e.his_r, e.sl_pct.mean()))

    for floor in TURNOVER_FLOORS:
        m1, m2, m3 = steps(df, floor)
        o.append("")
        o.append("=" * 108)
        o.append(f"HIS FUNNEL, turnover floor Rs {floor:.0f} cr")
        o.append("=" * 108)
        o.append(f"  all signals                      {len(df):7,d}")
        o.append(f"  1. DNA >= {DNA_MIN_MOVE:.0f}% on >= {DNA_MIN_LEGS} legs        "
                 f"{int(m1.sum()):7,d}   ({100*m1.mean():4.1f}%)")
        o.append(f"  2. + turnover >= {floor:.0f} cr and rising  {int(m2.sum()):7,d}   "
                 f"({100*m2.mean():4.1f}%)")
        o.append(f"  3. + a pivot, stop outside the zone {int(m3.sum()):7,d}   "
                 f"({100*m3.mean():4.1f}%)")
        o.append("")
        for name, m in (("after DNA", m1), ("after turnover", m2), ("after the stop rule", m3)):
            d = df[m & df.his_ret.notna()]
            o.append(stat(f"  {name}", d.his_ret, d.his_r,
                          d.sl_pct.mean() if len(d) else None))
        o.append("")
        o.append("  reward-to-risk minimum (DNA target / pivot stop):")
        for rr in RR_MINIMUMS:
            d = df[m3 & df.his_ret.notna() & df.rr.notna() & (df.rr >= rr)]
            o.append(stat(f"    R:R >= {rr:.0f}", d.his_ret, d.his_r,
                          d.sl_pct.mean() if len(d) else None))

        # The control: the same number of trades drawn from the pool the funnel
        # narrowed. Without it "fewer trades did better" says nothing.
        pool = df[df.his_ret.notna()]
        sel = df[m3 & df.his_ret.notna()]
        if len(sel) > 20 and len(pool) > len(sel):
            means = [pool.sample(n=len(sel), random_state=s).his_ret.mean()
                     for s in range(30)]
            o.append("")
            o.append(f"  random same-n from the same pool   n={len(sel):6d}  "
                     f"gross={np.mean(means):+6.3f}%  sd={np.std(means):5.3f}  "
                     f"funnel edge={sel.his_ret.mean()-np.mean(means):+6.3f}%")

    m1, m2, m3 = steps(df, TURNOVER_FLOORS[0])
    o.append("")
    o.append("=" * 108)
    o.append(f"Per year and per strategy, full funnel at Rs {TURNOVER_FLOORS[0]:.0f} cr")
    o.append("=" * 108)
    o.append(f"{'bucket':8s} {'all n':>8s} {'BASE':>8s} {'funnel n':>9s} {'FUNNEL':>8s} "
             f"{'net':>8s} {'SL%':>7s} {'RR':>6s}")
    sel = df[m3 & df.his_ret.notna()]
    for key, col in (("year", df.year), ("strategy", df.strategy)):
        o.append("-" * 108)
        for v in sorted(col.unique()):
            d = df[col == v]
            k = sel[getattr(sel, key) == v]
            g = k.his_ret.mean() if len(k) else float("nan")
            o.append(f"{str(v):8s} {len(d):8d} {d.base_ret.mean():+8.2f} {len(k):9d} "
                     + (f"{g:+8.2f} {net(g):+8.2f} {k.sl_pct.mean():7.2f} "
                        f"{k.rr.mean():6.2f}" if len(k) else f"{'--':>8s} {'--':>8s} "
                        f"{'--':>7s} {'--':>6s}"))

    o.append("")
    o.append("How the funnel's trades end, against the baseline's:")
    for name, col, mask in (("BASELINE  ", "his_exit", df.his_ret.notna()),
                            ("FUNNEL    ", "his_exit", m3 & df.his_ret.notna())):
        v = df[mask][col].value_counts(normalize=True)
        o.append(f"  {name} stop {100*v.get('stop',0):5.1f}%   target {100*v.get('target',0):5.1f}%"
                 f"   timeout {100*v.get('timeout',0):5.1f}%")
    d = df[m3 & df.his_ret.notna()]
    if len(d):
        o.append(f"  funnel median hold {d.his_bars.median():.0f} bars, "
                 f"median DNA target {d.dna_move.median():.1f}%, "
                 f"median stop {d.sl_pct.median():.2f}%")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-bars", type=int, default=1100)
    ap.add_argument("--out", default=os.path.join(HERE, "dnafirst_results.csv"))
    ap.add_argument("--title", default="DNA first, then turnover, then his stop and DNA target")
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
