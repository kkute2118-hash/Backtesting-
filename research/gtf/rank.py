"""Walk-forward ranking of the pooled candidates, and a weekly budget.

Two decisions matter more than the model.

RANK BY R, NOT BY PERCENT. With fixed-fractional sizing the money put into a
trade is eq*risk/stop_distance, so the contribution to equity is
risk * (percent / stop_percent) - that is, R. Ranking by expected percent
systematically prefers wide, volatile trades that need a big position of
capital to earn the same rupees. Ranking by expected R is what compounds.

NEVER FIT ON THE FUTURE. The model is refit at the start of every quarter on
candidates that had already RESOLVED by then - a 60-bar trade opened three
months before the boundary has not finished, so it is excluded. Each quarter
is then scored by a model that never saw it.

The weekly budget is applied the only way it can be applied live: score every
candidate the day it fires, take it if it clears a threshold set on past data
and the week's budget is not spent. No looking ahead to see if Friday brings
something better than Monday.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

MIN_TRAIN = 8000
RESOLVE_DAYS = 95           # a 60-bar trade needs about this long to finish

FEATS = ["src_score", "n_sources", "atr_pct", "rsi14", "relvol", "turnover_cr",
         "dist_ema20_atr", "dist_ema50_atr", "dist_ema200_atr",
         "ema20_over_50", "ema50_over_200", "pct_from_52w_high",
         "pct_above_52w_low", "ret_5d", "ret_20d", "ret_60d", "ret_120d",
         "vol20d", "slope50", "body_pct", "up_wick_pct", "dn_wick_pct",
         "gap_pct", "w_slope", "m_slope"]


def prepare(path="/tmp/gtf/pool.parquet"):
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"])
    d["stop_pct"] = 100 * (d.entry - d.stop_px) / d.entry
    d = d[d.stop_pct > 0.5].copy()
    d["R"] = d.p / d.stop_pct
    # source is categorical; one column per source so the model can use it
    for s in sorted(d.source.unique()):
        d[f"is_{s}"] = (d.source == s).astype(float)
    d["week"] = d.date.dt.to_period("W")
    return d.sort_values("date").reset_index(drop=True)


def walkforward(d, target="R", feats=None, min_train=MIN_TRAIN, seed=0):
    """Add a `pred` column scored out of sample, quarter by quarter."""
    feats = feats or (FEATS + [c for c in d.columns if c.startswith("is_")])
    d = d.copy()
    d["q"] = d.date.dt.to_period("Q")
    d["pred"] = np.nan
    fitted = []
    for qq in sorted(d.q.unique()):
        past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=RESOLVE_DAYS))]
        if len(past) < min_train:
            continue
        use = [f for f in feats if past[f].notna().sum() > 100 and past[f].nunique() > 1]
        m = HistGradientBoostingRegressor(
            max_depth=3, max_iter=300, learning_rate=0.05, min_samples_leaf=100,
            l2_regularization=1.0, random_state=seed).fit(
                past[use].to_numpy(), past[target].to_numpy())
        sel = d.q == qq
        d.loc[sel, "pred"] = m.predict(d.loc[sel, use].to_numpy())
        # thresholds are read off PAST predictions only
        pp = m.predict(past[use].to_numpy())
        # names must be valid Python identifiers: itertuples exposes them
        # as attributes, so "thr97.5" would be unreachable
        for p_, nm in ((50, "50"), (75, "75"), (90, "90"), (95, "95"),
                       (97.5, "975"), (99, "99"), (99.5, "995"), (99.9, "999")):
            d.loc[sel, f"thr{nm}"] = float(np.percentile(pp, p_))
        fitted.append(str(qq))
    return d, fitted


def weekly_pick(d, thr_col, per_week=3, per_day=2):
    """Greedy, causal: each day take the best-scoring candidates that clear the
    threshold, one per symbol, until the week's budget is spent."""
    d = d[d.pred.notna()].sort_values(["date", "pred"], ascending=[True, False])
    keep = []
    spent = {}
    for day, g in d.groupby("date", sort=True):
        wk = day.to_period("W")
        used = spent.get(wk, 0)
        if used >= per_week:
            continue
        taken_today = 0
        seen = set()
        for r in g.itertuples():
            if used >= per_week or taken_today >= per_day:
                break
            if r.symbol in seen:
                continue
            if r.pred < getattr(r, thr_col):
                break                      # sorted, so nothing later clears it
            seen.add(r.symbol)
            keep.append(r.Index)
            used += 1; taken_today += 1
        spent[wk] = used
    return d.loc[keep].sort_values("date")
