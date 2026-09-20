"""BASELINE vs the transcript-derived layer, over stored candles.

Answers one question: of the signals S1-S5 already produce, does the second
stage pick better ones? So every arm trades the SAME signal set and differs
only in which signals it keeps and how it exits.

  BASELINE   every S1-S5 signal, the platform's own 7% stop and 3R target
  MODEL A    only signals passing the hard gates, same stop and target
  MODEL C    passing signals, the author's pivot stop and 10-EMA exit

Scanner logic is never touched - this reads core.strategy_signal() and
core.features_fast() and decides nothing about what a signal is.

The diagnostic that matters most is not the headline. It is what the REJECTED
candidates went on to do. The author states the falsification himself: if the
trades you left all move up and the ones you pick come down, "there is a big,
big, major fault in your framework". So rejects are simulated too.

Usage:
    python research/trader_methodology/backtest.py --fixture
    python research/trader_methodology/backtest.py --limit 400
"""

from __future__ import annotations

import argparse, json, os, sys, warnings
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

BASELINE_STOP_PCT = 0.07     # the platform's current model, unchanged
BASELINE_R_TARGET = 3.0
MAX_HOLD_BARS = 120


def simulate_fixed(df, entry_i, stop, target):
    """The platform's exit: whichever of stop or target the bar touches first.

    A bar that spans both is charged as a loss. Without intrabar data there is
    no way to know the order, and assuming the good one is how backtests
    flatter themselves.
    """
    n = len(df)
    for j in range(entry_i, min(n, entry_i + MAX_HOLD_BARS)):
        lo, hi = float(df.low.iloc[j]), float(df.high.iloc[j])
        if lo <= stop:
            return stop, j - entry_i, "stop"
        if hi >= target:
            return target, j - entry_i, "target"
    j = min(n - 1, entry_i + MAX_HOLD_BARS - 1)
    return float(df.close.iloc[j]), j - entry_i, "timeout"


def simulate_author(df, ema10, entry_i, stop):
    """His exit: sit still above the 10 EMA, leave on a decisive close below.

    "I like to just be ignorant of the stock as long as it is above my 10 EMA.
    The day it comes to the 10 EMA is the day I'll come to my screen." The
    structural stop still applies underneath.
    """
    n = len(df)
    for j in range(entry_i, min(n, entry_i + MAX_HOLD_BARS)):
        if float(df.low.iloc[j]) <= stop:
            return stop, j - entry_i, "stop"
        e = float(ema10.iloc[j])
        if j > entry_i and float(df.close.iloc[j]) < e * (1 - 0.005):
            return float(df.close.iloc[j]), j - entry_i, "ema10"
    j = min(n - 1, entry_i + MAX_HOLD_BARS - 1)
    return float(df.close.iloc[j]), j - entry_i, "timeout"


def run(symbols, core, tl, params=None, progress=True):
    rows = []
    for k, sym in enumerate(symbols):
        if progress and k % 25 == 0:
            print(f"  {k}/{len(symbols)}", file=sys.stderr, flush=True)
        try:
            data = core.load_scan_dataset([sym])
        except Exception:
            continue
        df = data.get(sym)
        if df is None or len(df) < 300:
            continue
        df = df.sort_index()
        try:
            feats = core.features_fast(str(sym), df).replace([np.inf, -np.inf], np.nan)
        except Exception:
            continue
        if feats.empty:
            continue

        pre = {
            "event": tl.event_frame(df.close, params),
            "turnover": tl.turnover_frame(df.close, df.volume),
            "cb": tl.cb_flags(df.close, params),
        }
        ema10 = pre["event"]["ema10"]

        for s in core.IMPLEMENTED_STRATEGIES:
            try:
                sig = core.strategy_signal(feats, s).fillna(False).to_numpy()
            except Exception:
                continue
            for i in np.flatnonzero(sig):
                i = int(i)
                if i < 260 or i >= len(df) - 2:
                    continue
                try:
                    v = tl.evaluate(df, i, params, precomputed=pre)
                except Exception:
                    continue

                entry_i = i + 1
                entry = float(df.close.iloc[entry_i])
                if entry <= 0:
                    continue

                b_stop = entry * (1 - BASELINE_STOP_PCT)
                b_tgt = entry + BASELINE_R_TARGET * (entry - b_stop)
                bx, bbars, breason = simulate_fixed(df, entry_i, b_stop, b_tgt)

                piv = v.get("pivot")
                a_stop = piv * (1 - tl.PARAMS["STOP_BUFFER"]) if piv and piv < entry else b_stop
                ax, abars, areason = simulate_author(df, ema10, entry_i, a_stop)

                rows.append({
                    "symbol": sym,
                    "strategy": f"S{s}",
                    "date": pd.Timestamp(df.index[i]).date().isoformat(),
                    "year": pd.Timestamp(df.index[i]).year,
                    "passed": v["passed"],
                    "reject": v["reject"],
                    "rank": tl.rank_score(v),
                    "risk_pct": v.get("risk_pct"),
                    "avg_turnover_20": v.get("avg_turnover_20"),
                    "turnover_drift": v.get("turnover_drift"),
                    "cb_purity": v.get("cb_purity"),
                    "cb_count": v.get("cb_count"),
                    "cluster_fraction": v.get("cluster_fraction"),
                    "single_tower": v.get("single_tower"),
                    "ema_sep": v.get("ema_sep"),
                    "contained": v.get("contained"),
                    "upper_half": v.get("upper_half"),
                    "base_ret": (bx - entry) / entry * 100,
                    "base_bars": bbars,
                    "base_exit": breason,
                    "base_risk": (entry - b_stop) / entry * 100,
                    # R-multiples, because the two exits risk different
                    # amounts per trade. Comparing raw % would credit the
                    # wider stop for the size it could never have carried -
                    # and a tighter stop buying more size is the whole of his
                    # argument that the edge is in the entry price.
                    "base_r": (bx - entry) / (entry - b_stop) if entry > b_stop else np.nan,
                    "auth_ret": (ax - entry) / entry * 100,
                    "auth_bars": abars,
                    "auth_exit": areason,
                    "auth_risk": (entry - a_stop) / entry * 100,
                    "auth_r": (ax - entry) / (entry - a_stop) if entry > a_stop else np.nan,
                })
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame) -> str:
    out = []

    def block(title, d, ret="base_ret"):
        if d.empty:
            out.append(f"{title:34s}  (no trades)")
            return
        r = d[ret]
        out.append(
            f"{title:34s} n={len(d):6d}  win={100*(r>0).mean():5.1f}%  "
            f"mean={r.mean():+6.2f}%  med={r.median():+6.2f}%  "
            f"sum={r.sum():+9.0f}%"
        )

    out.append("=" * 96)
    out.append("BASELINE exit (7% stop, 3R target) - every arm trades the same S1-S5 signals")
    out.append("=" * 96)
    block("BASELINE  all signals", df)
    block("MODEL A   gates passed", df[df.passed])
    block("          gates rejected", df[~df.passed])

    out.append("")
    out.append("The falsification check: rejects must NOT beat accepts.")
    p, rj = df[df.passed]["base_ret"], df[~df.passed]["base_ret"]
    if len(p) and len(rj):
        d = p.mean() - rj.mean()
        out.append(f"  accepted - rejected = {d:+.2f}%/trade   "
                   f"{'OK' if d > 0 else 'INVERTED - the funnel is picking the wrong ones'}")

    out.append("")
    out.append("=" * 96)
    out.append("AUTHOR exit (pivot stop, decisive close below 10 EMA)")
    out.append("=" * 96)
    block("MODEL C   gates passed", df[df.passed], "auth_ret")
    block("          all signals", df, "auth_ret")

    out.append("")
    out.append("=" * 96)
    out.append("Risk-normalised (R per trade). This is the fair comparison: the two")
    out.append("exits risk different amounts, and a tighter stop buys more size.")
    out.append("=" * 96)
    for lbl, d, col in (
        ("BASELINE  all signals", df, "base_r"),
        ("MODEL A   gates passed", df[df.passed], "base_r"),
        ("MODEL C   gates passed", df[df.passed], "auth_r"),
        ("          all signals", df, "auth_r"),
    ):
        if d.empty or d[col].isna().all():
            out.append(f"{lbl:34s}  (no trades)")
            continue
        r = d[col].dropna()
        out.append(f"{lbl:34s} n={len(r):6d}  mean={r.mean():+6.3f}R  "
                   f"med={r.median():+6.3f}R  sum={r.sum():+8.0f}R")

    out.append("")
    out.append("Stop width - his claim is that better entries mean tighter stops")
    for lbl, d in (("all signals", df), ("gates passed", df[df.passed])):
        if not d.empty and d.auth_risk.notna().any():
            out.append(f"  {lbl:16s} median pivot stop {d.auth_risk.median():.2f}%   "
                       f"(baseline is a flat {100*BASELINE_STOP_PCT:.0f}%)")

    out.append("")
    out.append("=" * 96)
    out.append("Per strategy (baseline exit)")
    out.append("=" * 96)
    for s in sorted(df.strategy.unique()):
        d = df[df.strategy == s]
        dp = d[d.passed]
        out.append(
            f"  {s}  all n={len(d):6d} mean={d.base_ret.mean():+6.2f}%   "
            f"passed n={len(dp):5d} mean={dp.base_ret.mean():+6.2f}%"
            if len(dp) else
            f"  {s}  all n={len(d):6d} mean={d.base_ret.mean():+6.2f}%   passed n=0"
        )

    out.append("")
    out.append("=" * 96)
    out.append("Per year (baseline exit)")
    out.append("=" * 96)
    for y in sorted(df.year.unique()):
        d = df[df.year == y]
        dp = d[d.passed]
        out.append(
            f"  {y}  all n={len(d):6d} mean={d.base_ret.mean():+6.2f}%   "
            f"passed n={len(dp):5d} mean={dp.base_ret.mean():+6.2f}%"
            if len(dp) else
            f"  {y}  all n={len(d):6d} mean={d.base_ret.mean():+6.2f}%   passed n=0"
        )

    out.append("")
    out.append("=" * 96)
    out.append("Which gate does the rejecting")
    out.append("=" * 96)
    vc = df[~df.passed]["reject"].value_counts()
    for k, n in vc.items():
        out.append(f"  {str(k):14s} {n:6d}  ({100*n/len(df):4.1f}% of all signals)")
    out.append(f"  {'PASSED':14s} {int(df.passed.sum()):6d}  "
               f"({100*df.passed.mean():4.1f}% of all signals)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true", help="use the golden fixture DB")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "backtest_results.csv"))
    a = ap.parse_args()

    if a.fixture:
        sys.path.insert(0, os.path.join(ROOT, "backend", "tests", "golden"))
        import conftest_helpers as H
        H.install_fixture_db()
        from app.engine import core
        symbols = H.fixture_symbols(core)
    else:
        from app.engine import core
        con = core._db()
        try:
            symbols = [r[0] for r in con.execute(
                "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' "
                "GROUP BY symbol HAVING COUNT(*)>=300 ORDER BY symbol")]
        finally:
            con.close()

    import importlib.util as u
    spec = u.spec_from_file_location(
        "trader_layer", os.path.join(ROOT, "backend", "app", "engine", "trader_layer.py"))
    tl = u.module_from_spec(spec)
    spec.loader.exec_module(tl)

    if a.limit:
        symbols = symbols[: a.limit]
    print(f"symbols: {len(symbols)}", file=sys.stderr)

    df = run(symbols, core, tl)
    if df.empty:
        print("no signals produced - nothing to summarise")
        return
    df.to_csv(a.out, index=False)
    print(summarise(df))
    print(f"\nrows written to {a.out}")


if __name__ == "__main__":
    main()
