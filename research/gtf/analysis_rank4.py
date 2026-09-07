"""Two to three trades a week: what actually gets picked, and what it returns.

Ranking rules are compared against two controls that matter:
  random    3 a week drawn at random from the same candidate pool. Any ranking
            worth having must beat this, or the ranking is decoration.
  index     the equal-weight universe over the same span.

Selection is causal: each day the candidates are scored, the best are taken if
they clear a threshold set on past data, until the week's budget is spent. No
waiting to see whether Friday offers something better than Monday.
"""
import numpy as np, pandas as pd, sqlite3
import portfolio as PF
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04")
FLOOR, PER_WEEK = 25.0, 3

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values)
DMAP = {v: i for i, v in enumerate(CAL)}
NDAYS = len(CAL)

W = pd.read_parquet("/tmp/gtf/pool_scored.parquet")
W["date"] = pd.to_datetime(W["date"])
V = W[W.turnover_cr >= FLOOR].copy()
V["week"] = V.date.dt.to_period("W")
print(f"tradeable pool: {len(V)} candidates >= Rs {FLOOR:.0f} Cr turnover, "
      f"{V.symbol.nunique()} symbols, {V.date.min().date()} .. {V.date.max().date()}")


def pick(df, key, per_week=PER_WEEK, ascending=False, seed=None):
    """Take the top `per_week` per week by `key`, causally, one per symbol."""
    d = df.copy()
    if seed is not None:
        d["_k"] = np.random.default_rng(seed).random(len(d))
        key, ascending = "_k", False
    d = d.sort_values(["date", key], ascending=[True, ascending])
    keep = []; spent = {}
    for day, g in d.groupby("date", sort=True):
        wk = day.to_period("W")
        used = spent.get(wk, 0)
        if used >= per_week:
            continue
        seen = set()
        for r in g.itertuples():
            if used >= per_week:
                break
            if r.symbol in seen:
                continue
            seen.add(r.symbol); keep.append(r.Index); used += 1
        spent[wk] = used
    return d.loc[keep].sort_values("date")


RULES = {
    "model (walk-forward)": ("pred", False),
    "weakest 6-month momentum": ("ret_120d", True),
    "furthest below 200 EMA": ("dist_ema200_atr", True),
    "furthest below 52w high": ("pct_from_52w_high", True),
    "source's own score": ("src_score", False),
    "strongest weekly trend": ("w_slope", False),
    "most sources agreeing": ("n_sources", False),
}

print("\n" + "=" * 126)
print(f"{PER_WEEK} TRADES A WEEK - trade quality of what each rule selects")
print("=" * 126)
rows = []
sets = {}
for name, (key, asc) in RULES.items():
    s = pick(V, key, ascending=asc)
    sets[name] = s
    s2 = s[s.date >= CUT]
    rows.append({"rule": name, "trades": len(s), "avgR": round(s.R.mean(), 3),
                 "avg%": round(s.p.mean(), 2), "win%": round(100 * (s.p > 0).mean(), 1),
                 "last2y n": len(s2), "last2y avgR": round(s2.R.mean(), 3),
                 "last2y avg%": round(s2.p.mean(), 2),
                 "last2y win%": round(100 * (s2.p > 0).mean(), 1)})
rnd = [pick(V, None, seed=s) for s in range(5)]
sets["random from the pool"] = rnd[0]
r_all = pd.concat(rnd); r2 = r_all[r_all.date >= CUT]
rows.append({"rule": "random from the pool", "trades": len(rnd[0]),
             "avgR": round(r_all.R.mean(), 3), "avg%": round(r_all.p.mean(), 2),
             "win%": round(100 * (r_all.p > 0).mean(), 1),
             "last2y n": len(r2) // 5, "last2y avgR": round(r2.R.mean(), 3),
             "last2y avg%": round(r2.p.mean(), 2),
             "last2y win%": round(100 * (r2.p > 0).mean(), 1)})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 126)
print("PORTFOLIO: Rs 10,00,000, 1% risk, no leverage, median of 25 selection orders")
print("=" * 126)
for label, sub in (("FULL WINDOW (2022-10 to 2026-08)", None),
                   ("LAST 2 YEARS", CUT)):
    print(f"\n{label}")
    rows = []
    for name, s in sets.items():
        d = s if sub is None else s[s.date >= sub]
        if len(d) < 20: continue
        yrs = (d.date.max() - d.date.min()).days / 365.25
        a = PF.arrays(d, DMAP, NDAYS)
        r = PF.summary(a, CAL, years=yrs)
        if r: rows.append({"rule": name, **r, "years": round(yrs, 2)})
    print(pd.DataFrame(rows).to_string(index=False))

idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
for lab, sl in (("full window", idx.loc[V.date.min():]), ("last 2 years", idx.loc[CUT:])):
    yrs = (sl.index[-1] - sl.index[0]).days / 365.25
    print(f"  index, {lab:<13} ROI {100*(sl.iloc[-1]/sl.iloc[0]-1):+6.1f}%   "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+5.1f}%")
