"""Random beat every ranking rule. Three things could still change that.

  1. TAKING 3 EVERY WEEK IS NOT SELECTIVITY. The rules above were forced to
     fill a 3-trade budget whether or not the week offered anything good. A
     threshold that lets the system sit out a bad week is a different rule.
  2. FEWER TRADES. If ranking works at all, 1 a week should be better than 3.
  3. THE WRONG TARGET. The model predicts R. You asked for the most PROBABLE
     stocks, which is a different question - a classifier on P(win) ranks by
     probability rather than by expected size.
"""
import numpy as np, pandas as pd, sqlite3
from sklearn.ensemble import HistGradientBoostingClassifier
import portfolio as PF, rank as RK
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04"); FLOOR = 25.0

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values); DMAP = {v: i for i, v in enumerate(CAL)}
NDAYS = len(CAL)

W = pd.read_parquet("/tmp/gtf/pool_scored.parquet"); W["date"] = pd.to_datetime(W["date"])
V = W[W.turnover_cr >= FLOOR].copy()

# ---- 3. a win-probability model, same walk-forward discipline
print("fitting the win-probability model, quarter by quarter ...", flush=True)
d = RK.prepare()
d = d[d.turnover_cr >= FLOOR].copy()
d["win"] = (d.p > 0).astype(int)
d["q"] = d.date.dt.to_period("Q")
feats = RK.FEATS + [c for c in d.columns if c.startswith("is_")]
d["pwin"] = np.nan
for qq in sorted(d.q.unique()):
    past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=RK.RESOLVE_DAYS))]
    if len(past) < RK.MIN_TRAIN:
        continue
    use = [f for f in feats if past[f].notna().sum() > 100 and past[f].nunique() > 1]
    m = HistGradientBoostingClassifier(max_depth=3, max_iter=300, learning_rate=0.05,
                                       min_samples_leaf=100, l2_regularization=1.0,
                                       random_state=0).fit(past[use].to_numpy(),
                                                           past.win.to_numpy())
    sel = d.q == qq
    d.loc[sel, "pwin"] = m.predict_proba(d.loc[sel, use].to_numpy())[:, 1]
V = V.merge(d[["symbol", "bar", "source", "pwin"]], on=["symbol", "bar", "source"], how="left")
print(f"  scored {V.pwin.notna().sum()} candidates\n")

print("=" * 100)
print("DOES THE WIN-PROBABILITY MODEL SORT WIN RATE? out-of-sample, within quarter")
print("=" * 100)
V["pdec"] = V.groupby(V.date.dt.to_period("Q"))["pwin"].transform(
    lambda s: pd.qcut(s, 5, labels=False, duplicates="drop") if s.notna().sum() > 50 else np.nan)
t = V.groupby("pdec").agg(n=("p", "size"), win=("p", lambda s: 100 * (s > 0).mean()),
                          avgR=("R", "mean"), avg_pct=("p", "mean"))
print(t.round(2).to_string())
L = V[V.date >= CUT]
t2 = L.groupby("pdec").agg(n=("p", "size"), win=("p", lambda s: 100 * (s > 0).mean()),
                           avgR=("R", "mean"), avg_pct=("p", "mean"))
print("\nlast 2 years only:")
print(t2.round(2).to_string())


def pick(df, key, per_week, ascending=False, thr_q=None, seed=None):
    """Weekly budget, optionally gated: only take what clears a quantile of
    the PAST distribution of that key, so a poor week can be skipped."""
    d = df.dropna(subset=[key]).copy() if key else df.copy()
    if seed is not None:
        d["_k"] = np.random.default_rng(seed).random(len(d)); key, ascending = "_k", False
    if thr_q is not None:
        d = d.sort_values("date")
        v = d[key].to_numpy()
        # expanding quantile using only prior rows
        thr = pd.Series(v).expanding(min_periods=2000).quantile(thr_q).to_numpy()
        d = d[(v >= thr) if not ascending else (v <= pd.Series(v).expanding(
            min_periods=2000).quantile(1 - thr_q).to_numpy())]
    d = d.sort_values(["date", key], ascending=[True, ascending])
    keep = []; spent = {}
    for day, g in d.groupby("date", sort=True):
        wk = day.to_period("W"); used = spent.get(wk, 0)
        if used >= per_week: continue
        seen = set()
        for r in g.itertuples():
            if used >= per_week: break
            if r.symbol in seen: continue
            seen.add(r.symbol); keep.append(r.Index); used += 1
        spent[wk] = used
    return d.loc[keep].sort_values("date")


print("\n" + "=" * 132)
print("SELECTIVITY SWEEP - portfolio ROI, median of 25 orderings. index: +158.9% full / +7.9% last 2y")
print("=" * 132)
rows = []
for name, key, asc in (("model (expected R)", "pred", False),
                       ("win probability", "pwin", False),
                       ("random", None, False)):
    for per_week in (1, 2, 3):
        for gate in (None, 0.95, 0.99):
            if key is None and gate is not None:
                continue
            s = pick(V, key, per_week, ascending=asc, thr_q=gate,
                     seed=0 if key is None else None)
            if len(s) < 20: continue
            row = {"rule": name, "per week": per_week,
                   "gate": "none" if gate is None else f"top {100-gate*100:.0f}%",
                   "trades": len(s), "avgR": round(s.R.mean(), 3),
                   "win%": round(100 * (s.p > 0).mean(), 1)}
            for lab, sub in (("full", s), ("last2y", s[s.date >= CUT])):
                if len(sub) < 20:
                    row[f"ROI {lab}"] = np.nan; continue
                yrs = (sub.date.max() - sub.date.min()).days / 365.25
                r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=15, years=yrs)
                row[f"ROI {lab}"] = r["ROI%"] if r else np.nan
                row[f"CAGR {lab}"] = r.get("CAGR%") if r else np.nan
            rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
