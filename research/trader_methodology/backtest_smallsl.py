"""The small stop: does his structural SL beat our flat 7%?

The forward book opens every non-S5 trade on a flat 7% stop with a 3R target.
That number is ours. His is a pivot: the stop goes under the demand candle's
low, and on the fixture that comes out at 2-5% instead of 7. He is explicit
that the tight stop is where the edge lives - "I also like his SL he enter
perfect points so SL can be minimized extremely".

So test it as the stop, not as a ranking key. Ranking candidates BY stop width
already failed three ways (FINDINGS_RANKER.md); that is a different question
from whether a tighter stop is a better stop on the same trade.

Four arms, identical signals, identical entry bar:

  FLAT7      entry x 0.93, target entry + 3R          the current book
  PIVOT      under the demand candle, target + 3R     his stop
  PIVOT_CAP  the same, but never wider than 7%        the two combined
  PIVOT_MK   PIVOT plus the marking gates below       stop AND selection

The marking gates are the ones the user asked to try, stated up front so they
cannot be fitted afterwards:

  not inside the demand zone   his one outright refusal on stop placement
  stop <= 0.6 x the stock's own typical move   one normal move has to be able
                                               to pay for the risk several times
  turnover >= 1.2x its own 20-day average      money arriving, not a dead tape

Everything is reported per year and per strategy, gross AND after Indian
round-trip costs, because a 2% stop and a 0.59% round trip are the same order
of magnitude and a gross number would be meaningless.

Scanner logic untouched: signals come from strategy_signal(), unchanged.
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
LOOKBACK_DAYS = 2200          # ~6 years, so the sample spans several regimes
WARMUP = 300                  # bars before the first tradable signal

# The marking gates, fixed before the run.
MK_MAX_SL_OVER_DNA = 0.6
MK_MIN_TURNOVER_SPIKE = 1.2


def exit_at(df, e, stop, tgt):
    """Walk forward bar by bar. The stop is checked first on every bar.

    A bar whose low breaks the stop AND whose high reaches the target is
    counted as a stop. With a 2% stop and a 3R target that combination is
    common, and resolving it the other way would hand the tight-stop arm free
    wins that nobody could have taken.
    """
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

        # Once per symbol, not once per signal. dna() drops any swing above
        # i - span itself, so this costs nothing in lookahead.
        swings = tl.swing_low_positions(d.close)
        t = tl.turnover_cr(d.close, d.volume)
        avg_prior = t.shift(1).rolling(tl.AUTHOR_AVERAGE_TURNOVER_LOOKBACK,
                                       min_periods=tl.AUTHOR_AVERAGE_TURNOVER_LOOKBACK).mean()

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

                # --- the marking, read at the SIGNAL bar, never later -------
                dn = tl.dna(d.close, at=i, swings=swings)
                piv = None
                try:
                    start = tl.expansion_end(d.close, i)
                    piv = tl.pivot_low(d.low, d.close, d.open, i, search_from=start)
                except Exception:
                    piv = None

                spike = None
                if np.isfinite(avg_prior.iloc[i]) and float(avg_prior.iloc[i]) > 0:
                    spike = float(t.iloc[i]) / float(avg_prior.iloc[i])

                flat = entry * (1 - FLAT_STOP)
                pivot_stop = None
                if piv is not None and np.isfinite(piv) and piv < entry:
                    pivot_stop = float(piv) * (1.0 - tl.PARAMS["STOP_BUFFER"])

                rows.append({
                    "symbol": sym, "strategy": f"S{s}",
                    "date": pd.Timestamp(d.index[i]).date().isoformat(),
                    "year": pd.Timestamp(d.index[i]).year,
                    "entry": entry,
                    "flat_stop": flat,
                    "pivot_stop": pivot_stop,
                    "pivot_raw": None if piv is None else float(piv),
                    "dna_candle": dn["dna_candle"], "dna_move": dn["dna_move"],
                    "turnover_spike": spike,
                    "avg_turnover_20": (float(avg_prior.iloc[i])
                                        if np.isfinite(avg_prior.iloc[i]) else None),
                    "_i": i, "_e": e,
                })
                r = rows[-1]

                for name, stop in (("flat", flat), ("pivot", pivot_stop)):
                    if stop is None or stop >= entry:
                        r[f"{name}_ret"] = None
                        r[f"{name}_r"] = None
                        r[f"{name}_exit"] = None
                        r[f"{name}_bars"] = None
                        continue
                    tgt = entry + R_TARGET * (entry - stop)
                    x, why, bars = exit_at(d, e, stop, tgt)
                    r[f"{name}_ret"] = (x - entry) / entry * 100
                    r[f"{name}_r"] = (x - entry) / (entry - stop)
                    r[f"{name}_exit"] = why
                    r[f"{name}_bars"] = bars
                    r[f"{name}_sl_pct"] = (entry - stop) / entry * 100

                # PIVOT_CAP: his stop, but never wider than ours. A capped stop
                # is a different trade, so it is resolved separately rather
                # than inferred from the other two.
                cap = pivot_stop
                if cap is None or cap < flat:
                    cap = flat
                tgt = entry + R_TARGET * (entry - cap)
                x, why, bars = exit_at(d, e, cap, tgt)
                r["cap_ret"] = (x - entry) / entry * 100
                r["cap_r"] = (x - entry) / (entry - cap)
                r["cap_exit"] = why
                r["cap_sl_pct"] = (entry - cap) / entry * 100

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["sl_vs_dna"] = df.pivot_sl_pct / df.dna_move
    df["inside_zone"] = df.pivot_raw.notna() & (df.flat_stop > df.pivot_raw)
    return df


def net(ret_pct, slip):
    """Gross % per trade minus the round trip. Notional is the slot size, and
    at Rs 1 lakh brokerage is already at its Rs20 cap, so the answer barely
    moves with position size."""
    return ret_pct - C.round_trip_pct(100000.0, C.SLIPPAGE[slip])


def line(label, r, sl=None, extra=""):
    if r is None or len(r) == 0:
        return f"{label:26s} (none)"
    g = r["ret"].mean()
    return (f"{label:26s} n={len(r):6d}  win={100*(r['ret']>0).mean():5.1f}%  "
            f"SL={sl if sl is not None else float('nan'):5.2f}%  "
            f"gross={g:+6.3f}%  net={net(g, 'realistic'):+6.3f}%  "
            f"R={r['r'].mean():+6.3f}{extra}")


def arms(df):
    """Each arm as a (ret, r, sl%) frame over the rows where it can be taken."""
    out = {}
    a = df[df.flat_ret.notna()]
    out["FLAT7  (current book)"] = (
        pd.DataFrame({"ret": a.flat_ret, "r": a.flat_r}), a.flat_sl_pct.mean())

    b = df[df.pivot_ret.notna()]
    out["PIVOT  (his stop)"] = (
        pd.DataFrame({"ret": b.pivot_ret, "r": b.pivot_r}), b.pivot_sl_pct.mean())

    c = df[df.cap_ret.notna()]
    out["PIVOT_CAP (<= 7%)"] = (
        pd.DataFrame({"ret": c.cap_ret, "r": c.cap_r}), c.cap_sl_pct.mean())

    m = df[df.pivot_ret.notna() & ~df.inside_zone
           & (df.sl_vs_dna <= MK_MAX_SL_OVER_DNA)
           & (df.turnover_spike >= MK_MIN_TURNOVER_SPIKE)]
    out["PIVOT_MK (+ marking)"] = (
        pd.DataFrame({"ret": m.pivot_ret, "r": m.pivot_r}), m.pivot_sl_pct.mean())

    # The control the marking arm has to beat: the same number of PIVOT trades
    # drawn at random. Without it, "fewer trades did better" is unreadable.
    if len(m) > 20:
        means = []
        for seed in range(30):
            d = b.sample(n=min(len(m), len(b)), random_state=seed)
            means.append(d.pivot_ret.mean())
        out["_random_same_n"] = (float(np.mean(means)), float(np.std(means)), len(m))
    return out


def report(df, title):
    o = [""]
    o.append("=" * 104)
    o.append(title)
    o.append("=" * 104)
    o.append(f"signals {len(df):,} | symbols {df.symbol.nunique():,} | "
             f"{df.year.min()}-{df.year.max()} | a demand pivot was found on "
             f"{100*df.pivot_stop.notna().mean():.1f}% of them")
    rt = C.round_trip_pct(100000.0, C.SLIPPAGE['realistic'])
    o.append(f"costs: round trip {rt:.3f}% of notional at realistic slippage, "
             f"subtracted from every net figure")
    o.append("")
    a = arms(df)
    rnd = a.pop("_random_same_n", None)
    for k, (frame, sl) in a.items():
        o.append(line(k, frame, sl))
    if rnd:
        o.append(f"{'  random same-n control':26s} n={rnd[2]:6d}  "
                 f"gross={rnd[0]:+6.3f}%  sd={rnd[1]:5.3f}")

    o.append("")
    o.append("-" * 104)
    o.append("Per year (gross % per trade)")
    o.append("-" * 104)
    o.append(f"{'year':6s} {'n':>7s} {'FLAT7':>9s} {'PIVOT':>9s} {'CAP':>9s} "
             f"{'MK':>9s} {'MK n':>7s} {'PIVOT SL%':>10s}")
    for y in sorted(df.year.unique()):
        d = df[df.year == y]
        m = d[d.pivot_ret.notna() & ~d.inside_zone
              & (d.sl_vs_dna <= MK_MAX_SL_OVER_DNA)
              & (d.turnover_spike >= MK_MIN_TURNOVER_SPIKE)]
        o.append(f"{y:<6d} {len(d):7d} {d.flat_ret.mean():+9.2f} "
                 f"{d.pivot_ret.mean():+9.2f} {d.cap_ret.mean():+9.2f} "
                 + (f"{m.pivot_ret.mean():+9.2f}" if len(m) else f"{'--':>9s}")
                 + f" {len(m):7d} {d.pivot_sl_pct.mean():10.2f}")

    o.append("")
    o.append("-" * 104)
    o.append("Per strategy (gross % per trade)")
    o.append("-" * 104)
    o.append(f"{'strat':6s} {'n':>7s} {'FLAT7':>9s} {'PIVOT':>9s} {'CAP':>9s} "
             f"{'MK':>9s} {'MK n':>7s} {'PIVOT SL%':>10s}")
    for s in sorted(df.strategy.unique()):
        d = df[df.strategy == s]
        m = d[d.pivot_ret.notna() & ~d.inside_zone
              & (d.sl_vs_dna <= MK_MAX_SL_OVER_DNA)
              & (d.turnover_spike >= MK_MIN_TURNOVER_SPIKE)]
        o.append(f"{s:6s} {len(d):7d} {d.flat_ret.mean():+9.2f} "
                 f"{d.pivot_ret.mean():+9.2f} {d.cap_ret.mean():+9.2f} "
                 + (f"{m.pivot_ret.mean():+9.2f}" if len(m) else f"{'--':>9s}")
                 + f" {len(m):7d} {d.pivot_sl_pct.mean():10.2f}")

    o.append("")
    o.append("-" * 104)
    o.append("How each arm ends")
    o.append("-" * 104)
    for name, col in (("FLAT7", "flat_exit"), ("PIVOT", "pivot_exit"), ("CAP", "cap_exit")):
        v = df[col].value_counts(normalize=True)
        o.append(f"{name:8s} stop {100*v.get('stop',0):5.1f}%   "
                 f"target {100*v.get('target',0):5.1f}%   "
                 f"timeout {100*v.get('timeout',0):5.1f}%")
    o.append("")
    o.append(f"stop placed INSIDE the demand zone by the flat rule: "
             f"{100*df.inside_zone.mean():.1f}% of signals")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-bars", type=int, default=1100)
    ap.add_argument("--out", default=os.path.join(HERE, "smallsl_results.csv"))
    ap.add_argument("--title", default="Small structural stop vs the flat 7%")
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
