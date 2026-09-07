"""Is the win-probability ranking real, or the best of 21 cells I looked at?

The sweep tried 21 configurations and the best one returned +11.0% over the
last two years. Reporting that number as the system's expectation would be
picking the winner after seeing the results. Two checks instead:

  paired   the same 200 random selection orderings, win-probability ranking
           against random selection from the same pool. Same weeks, same
           budget, same capital. If the ranking adds nothing the difference
           distribution sits on zero.
  stable   the ranking's decile behaviour quarter by quarter, which is what
           has to hold for the rule to be worth running at all.
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

d = RK.prepare(); d = d[d.turnover_cr >= FLOOR].copy()
d["win"] = (d.p > 0).astype(int); d["q"] = d.date.dt.to_period("Q")
feats = RK.FEATS + [c for c in d.columns if c.startswith("is_")]
d["pwin"] = np.nan
for qq in sorted(d.q.unique()):
    past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=RK.RESOLVE_DAYS))]
    if len(past) < RK.MIN_TRAIN: continue
    use = [f for f in feats if past[f].notna().sum() > 100 and past[f].nunique() > 1]
    m = HistGradientBoostingClassifier(max_depth=3, max_iter=300, learning_rate=0.05,
                                       min_samples_leaf=100, l2_regularization=1.0,
                                       random_state=0).fit(past[use].to_numpy(), past.win.to_numpy())
    d.loc[d.q == qq, "pwin"] = m.predict_proba(d.loc[d.q == qq, use].to_numpy())[:, 1]
V = d[d.pwin.notna()].copy()
V.to_parquet("/tmp/gtf/pool_pwin.parquet", index=False)
print(f"{len(V)} scored candidates, {V.date.min().date()} .. {V.date.max().date()}\n")

print("=" * 100)
print("1. QUARTER BY QUARTER: win rate of the top fifth vs the bottom fifth")
print("=" * 100)
rows = []
for per, g in V.groupby("q"):
    if len(g) < 1500: continue
    q5 = pd.qcut(g.pwin, 5, labels=False, duplicates="drop")
    top, bot = g.p[q5 == q5.max()], g.p[q5 == 0]
    rows.append({"quarter": str(per), "n": len(g),
                 "top fifth win%": round(100 * (top > 0).mean(), 1),
                 "bottom fifth win%": round(100 * (bot > 0).mean(), 1),
                 "gap": round(100 * ((top > 0).mean() - (bot > 0).mean()), 1)})
q = pd.DataFrame(rows)
print(q.to_string(index=False))
print(f"\nmean gap {q.gap.mean():+.1f} points, positive in {int((q.gap>0).sum())}/{len(q)} quarters")
rec = q[q.quarter >= "2024Q3"]
print(f"last 2 years: {rec.gap.mean():+.1f} points, positive in "
      f"{int((rec.gap>0).sum())}/{len(rec)} quarters")


def pick_idx(dates_i, weeks_i, syms_i, key, per_week):
    """Weekly budget, vectorised. Highest key first within each day, one per
    symbol, stop once the week's budget is spent. Causal: a day is resolved
    using only that day's candidates and the budget already spent that week."""
    order = np.lexsort((-key, dates_i))
    spent = {}; keep = []
    n = len(order); i = 0
    while i < n:
        j = i; day = dates_i[order[i]]
        while j < n and dates_i[order[j]] == day:
            j += 1
        wk = weeks_i[order[i]]
        used = spent.get(wk, 0)
        if used < per_week:
            seen = set()
            for k in order[i:j]:
                if used >= per_week:
                    break
                s_ = syms_i[k]
                if s_ in seen:
                    continue
                seen.add(s_); keep.append(k); used += 1
            spent[wk] = used
        i = j
    return np.array(keep, dtype=int)


V2 = V.sort_values("date").reset_index(drop=True)
DI = V2.date.factorize()[0]
WK = V2.date.dt.to_period("W").astype(str).to_numpy()
SY = V2.symbol.to_numpy()


print("\n" + "=" * 116)
print("2. PAIRED AGAINST RANDOM - same 60 orderings, same weeks, same budget")
print("=" * 116)
rows = []
for per_week in (1, 2, 3):
    sw = V2.iloc[pick_idx(DI, WK, SY, V2.pwin.to_numpy(), per_week)]
    rand_sets = [V2.iloc[pick_idx(DI, WK, SY,
                                  np.random.default_rng(1000 + s_).random(len(V2)),
                                  per_week)] for s_ in range(60)]
    for lab, cut in (("full window", None), ("last 2 years", CUT)):
        sub_w = sw if cut is None else sw[sw.date >= cut]
        aw = PF.arrays(sub_w, DMAP, NDAYS)
        r_model = np.array([PF.run(aw, seed=s_) for s_ in range(60)])
        r_rand = np.array([
            PF.run(PF.arrays(rs if cut is None else rs[rs.date >= cut], DMAP, NDAYS),
                   seed=s_) for s_, rs in enumerate(rand_sets)])
        ok = np.isfinite(r_model) & np.isfinite(r_rand)
        diff = r_model[ok] - r_rand[ok]
        rows.append({"per week": per_week, "period": lab, "trades": len(sub_w),
                     "model ROI% (median)": round(float(np.median(r_model[ok])), 1),
                     "random ROI% (median)": round(float(np.median(r_rand[ok])), 1),
                     "model minus random": round(float(np.median(diff)), 1),
                     "model won": f"{100*(diff>0).mean():.0f}% of runs",
                     "model 10-90pct": f"[{np.percentile(r_model[ok],10):.0f}, "
                                       f"{np.percentile(r_model[ok],90):.0f}]"})
print(pd.DataFrame(rows).to_string(index=False))
