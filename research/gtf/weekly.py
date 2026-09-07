"""The marking system: score every candidate, mark it 0-100, take 2 a week.

What this is, and what it is not.

IT IS a probability model. It was chosen because it is the only ranking that
survived every test: out of sample, quarter by quarter, its top fifth wins
more often than its bottom fifth by 6.4 points on average, positive in 12 of
16 quarters and 7 of the last 9. Nothing else in this project has held up
that consistently, including the expected-return model, the source scores,
and every hand-picked feature.

IT IS NOT a return forecast. The mark says how likely the trade is to end
green, not how much it makes. Win rates are around 25-35 %, so most marked
trades still lose. The money comes from the winners running.

The mark is the model's out-of-sample percentile among the candidates of that
same quarter, so 90 means "in the best 10 % of what this market was offering
at the time", not "90 % likely to win".
"""
from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import rank as RK

FLOOR_CR = 25.0          # turnover floor: below this the backtest is fiction
PER_WEEK = 2
RESOLVE_DAYS = RK.RESOLVE_DAYS


def fit(train):
    feats = [f for f in RK.FEATS + [c for c in train.columns if c.startswith("is_")]
             if f in train.columns and train[f].notna().sum() > 100
             and train[f].nunique() > 1]
    m = HistGradientBoostingClassifier(
        max_depth=3, max_iter=300, learning_rate=0.05, min_samples_leaf=100,
        l2_regularization=1.0, random_state=0).fit(
            train[feats].to_numpy(), (train.p > 0).astype(int).to_numpy())
    return m, feats


def mark(pool, asof=None):
    """Score `pool` using only candidates that had RESOLVED before `asof`."""
    asof = pd.Timestamp(asof) if asof is not None else pool.date.max()
    train = pool[pool.date < asof - pd.Timedelta(days=RESOLVE_DAYS)]
    if len(train) < RK.MIN_TRAIN:
        raise ValueError(f"only {len(train)} resolved candidates before {asof.date()}")
    m, feats = fit(train)
    live = pool[pool.date == asof].copy()
    if not len(live):
        return live.assign(pwin=[], mark=[])
    live["pwin"] = m.predict_proba(live[feats].to_numpy())[:, 1]
    ref = m.predict_proba(train[feats].to_numpy())[:, 1]
    live["mark"] = [100 * (ref < v).mean() for v in live.pwin]
    return live.sort_values("mark", ascending=False)


def shortlist(pool, asof=None, n=PER_WEEK, floor_cr=FLOOR_CR):
    live = mark(pool[pool.turnover_cr >= floor_cr], asof)
    out = live.drop_duplicates("symbol").head(n)
    cols = ["date", "symbol", "source", "mark", "entry", "stop_px",
            "atr_pct", "turnover_cr", "rsi14", "dist_ema200_atr", "ret_120d"]
    return out[[c for c in cols if c in out.columns]]


if __name__ == "__main__":
    import sys
    pool = RK.prepare()
    asof = pd.Timestamp(sys.argv[1]) if len(sys.argv) > 1 else None
    s = shortlist(pool, asof)
    if not len(s):
        print("no candidates that day"); raise SystemExit
    s = s.copy()
    s["stop %"] = (100 * (s.entry - s.stop_px) / s.entry).round(1)
    s["target (+8ATR)"] = (s.entry * (1 + 8 * s.atr_pct / 100)).round(1)
    print(s.round(2).to_string(index=False))
