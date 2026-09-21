"""MODEL B: rank the scanner's signals, don't gate them.

Runs 1 and 2 killed the hard-gate stack - it inverted the funnel and damaged
the strategies that already worked. But three measures carried real signal
across all 22,000+ signals, and all three come straight from the source:

  CB purity        how many of the expansion's up days were Committed Buyer
                   days, relative to that stock's own good days. Scored as a
                   BAND, not more-is-better: the 50-75% band ran +0.67% and
                   above 75% ran -1.61%, which is his own extension warning.
  volume cluster   several adjacent elevated bars, not one isolated tower
  turnover         a BAND again. The top quartile was the worst performer,
                   so a floor plus a ceiling, not a ranking on size.

A ranker can use the whole distribution instead of collapsing it to a
pass/fail, which is what the gates did wrong: they reduced 22,530 signals to
796 and lost S4 and S5 in the process.

Take the top N per day and measure against taking all of them, and against
taking N at random - the random arm is the one that says whether the ranking
is doing anything or whether N-per-day is just diversification.

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

FLAT_STOP = 0.07
R_TARGET = 3.0
MAX_HOLD = 120


def band(x, lo, hi, soft=0.25):
    """1.0 inside [lo, hi], tapering to 0 outside.

    A band rather than a threshold because both CB purity and turnover turned
    out non-monotonic: too much of either is a warning, not a stronger buy.
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    if lo <= x <= hi:
        return 1.0
    d = (lo - x) if x < lo else (x - hi)
    span = max(soft * max(abs(hi), 1e-9), 1e-9)
    return float(max(0.0, 1.0 - d / span))


def score(r, w=None):
    w = {"cb": 1.0, "cluster": 0.7, "turnover": 0.5, "tower": 0.8, **(w or {})}
    s = 0.0
    s += w["cb"] * band(r.get("cb_purity"), 0.35, 0.75)
    s += w["cluster"] * min(float(r.get("cluster_fraction") or 0.0) / 0.4, 1.0)
    s += w["turnover"] * band(r.get("avg_turnover_20"), 60.0, 400.0, soft=0.6)
    s -= w["tower"] * (1.0 if r.get("single_tower") else 0.0)
    return s


def exit_flat(df, e, stop, tgt):
    for j in range(e, min(len(df), e + MAX_HOLD)):
        if float(df.low.iloc[j]) <= stop:
            return stop, "stop"
        if float(df.high.iloc[j]) >= tgt:
            return tgt, "target"
    return float(df.close.iloc[min(len(df) - 1, e + MAX_HOLD - 1)]), "timeout"


def build(symbols, core, tl):
    rows = []
    for k, sym in enumerate(symbols):
        if k % 25 == 0:
            print(f"  {k}/{len(symbols)}", file=sys.stderr, flush=True)
        d = core.load_scan_dataset([sym]).get(sym)
        if d is None or len(d) < 300:
            continue
        d = d.sort_index()
        try:
            f = core.features_fast(str(sym), d).replace([np.inf, -np.inf], np.nan)
        except Exception:
            continue
        if f.empty:
            continue
        pre = {"event": tl.event_frame(d.close), "cb": tl.cb_flags(d.close),
               "turnover": tl.turnover_frame(d.close, d.volume)}
        for s in core.IMPLEMENTED_STRATEGIES:
            try:
                sig = core.strategy_signal(f, s).fillna(False).to_numpy()
            except Exception:
                continue
            for i in np.flatnonzero(sig):
                i = int(i)
                if i < 260 or i >= len(d) - 2:
                    continue
                try:
                    v = tl.evaluate(d, i, None, precomputed=pre)
                except Exception:
                    continue
                e = i + 1
                en = float(d.close.iloc[e])
                if en <= 0:
                    continue
                st = en * (1 - FLAT_STOP)
                x, why = exit_flat(d, e, st, en + R_TARGET * (en - st))
                rows.append({
                    "symbol": sym, "strategy": f"S{s}",
                    "date": pd.Timestamp(d.index[i]).date().isoformat(),
                    "year": pd.Timestamp(d.index[i]).year,
                    "cb_purity": v.get("cb_purity"),
                    "cluster_fraction": v.get("cluster_fraction"),
                    "single_tower": bool(v.get("single_tower")),
                    "avg_turnover_20": v.get("avg_turnover_20"),
                    "ret": (x - en) / en * 100, "r": (x - en) / (en - st), "exit": why,
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["score"] = [score(r) for _, r in df.iterrows()]
    return df


def topn_per_day(df, n, by="score", seed=None):
    if seed is None:
        return (df.sort_values(by, ascending=False).groupby("date", sort=False)
                  .head(n))
    rng = np.random.default_rng(seed)
    return (df.assign(_k=rng.random(len(df))).sort_values("_k")
              .groupby("date", sort=False).head(n))


def summarise(df):
    o = []
    o.append("=" * 96)
    o.append("Ranking, not gating. Every arm uses the same signals and the same exit.")
    o.append("=" * 96)

    def line(lbl, d):
        if d.empty:
            o.append(f"{lbl:40s} (none)"); return
        o.append(f"{lbl:40s} n={len(d):6d}  win={100*(d.ret>0).mean():5.1f}%  "
                 f"mean={d.ret.mean():+6.3f}%  R={d.r.mean():+6.3f}")

    line("ALL signals", df)
    o.append("")
    for n in (1, 2, 3, 5):
        top = topn_per_day(df, n)
        line(f"TOP {n}/day by score", top)
        # The control: same count, chosen at random. If the ranked arm does not
        # beat this, the ranking is doing nothing and the gain is just from
        # trading fewer, more-diversified days.
        means = [topn_per_day(df, n, seed=s).ret.mean() for s in range(20)]
        o.append(f"{'    random ' + str(n) + '/day (20 draws)':40s} "
                 f"mean={np.mean(means):+6.3f}%  sd={np.std(means):5.3f}  "
                 f"edge={top.ret.mean()-np.mean(means):+6.3f}%")
        o.append("")

    o.append("=" * 96)
    o.append("Score decile - is the ranking monotonic at all?")
    o.append("=" * 96)
    d = df.dropna(subset=["score"]).copy()
    d["q"] = pd.qcut(d.score, 10, labels=False, duplicates="drop")
    g = d.groupby("q", observed=True).agg(n=("ret", "size"), mean=("ret", "mean"),
                                          R=("r", "mean")).round(3)
    o.append(g.to_string())

    o.append("")
    o.append("=" * 96)
    o.append("Top 3/day, per year and per strategy")
    o.append("=" * 96)
    top = topn_per_day(df, 3)
    for y in sorted(df.year.unique()):
        a, b = df[df.year == y], top[top.year == y]
        o.append(f"  {y}  all n={len(a):6d} {a.ret.mean():+6.2f}%   "
                 f"top3 n={len(b):5d} " + (f"{b.ret.mean():+6.2f}%" if len(b) else "  --"))
    for s in sorted(df.strategy.unique()):
        a, b = df[df.strategy == s], top[top.strategy == s]
        o.append(f"  {s}  all n={len(a):6d} {a.ret.mean():+6.2f}%   "
                 f"top3 n={len(b):5d} " + (f"{b.ret.mean():+6.2f}%" if len(b) else "  --"))
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--sample", type=int, default=0,
                    help="random subset of symbols; the full store takes hours")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "rank_results.csv"))
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

    if a.sample and a.sample < len(symbols):
        # Random, not the first N alphabetically: an alphabetical slice of an
        # exchange listing is a biased sample, and the full store takes hours.
        rng = np.random.default_rng(a.seed)
        symbols = sorted(rng.choice(symbols, size=a.sample, replace=False).tolist())

    import importlib.util as u
    spec = u.spec_from_file_location(
        "trader_layer", os.path.join(ROOT, "backend", "app", "engine", "trader_layer.py"))
    tl = u.module_from_spec(spec); spec.loader.exec_module(tl)

    print(f"symbols: {len(symbols)}", file=sys.stderr)
    df = build(symbols, core, tl)
    if df.empty:
        print("no signals"); return
    df.to_csv(a.out, index=False)
    print(summarise(df))
    print(f"\nrows -> {a.out}")


if __name__ == "__main__":
    main()
