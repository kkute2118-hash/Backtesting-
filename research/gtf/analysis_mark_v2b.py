"""Portfolio impact of the two new feature groups, and the risk in one of them.

Volume features are stock-level: two candidates on the same day get different
values. Index-position features are shared by every candidate on a given day,
so a model given them can rank by DATE as much as by stock - which is market
timing, and market timing is the thing that has inverted every time it has
been tested here. That shows in the quarterly record: index features gave the
biggest average gap but were negative in four quarters including a run of
three, while volume features were positive in 15 of 16 and 9 of 9 recently.
"""
import numpy as np, pandas as pd, sqlite3
import portfolio as PF
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values); DMAP = {v: i for i, v in enumerate(CAL)}
NDAYS = len(CAL)

W = pd.read_parquet("/tmp/gtf/pool_v2.parquet"); W["date"] = pd.to_datetime(W["date"])
W = W.sort_values("date").reset_index(drop=True)
DI = W.date.factorize()[0]
WK = W.date.dt.to_period("W").astype(str).to_numpy()
SY = W.symbol.to_numpy()


def pick(key, per_week=2):
    order = np.lexsort((-key, DI))
    spent = {}; keep = []
    n = len(order); i = 0
    while i < n:
        j = i; day = DI[order[i]]
        while j < n and DI[order[j]] == day:
            j += 1
        wk = WK[order[i]]; used = spent.get(wk, 0)
        if used < per_week:
            seen = set()
            for k in order[i:j]:
                if used >= per_week: break
                if SY[k] in seen: continue
                seen.add(SY[k]); keep.append(k); used += 1
            spent[wk] = used
        i = j
    return W.iloc[keep]


print("=" * 128)
print("2 A WEEK, Rs 10,00,000, 1% risk, no leverage, median of 40 orderings")
print("=" * 128)
rows = []
for name in ["original", "+ volume", "+ index position", "+ both"]:
    s = pick(W[f"p_{name}"].to_numpy())
    for lab, cut in (("full window", None), ("last 2 years", CUT)):
        sub = s if cut is None else s[s.date >= cut]
        yrs = (sub.date.max() - sub.date.min()).days / 365.25
        r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=40, years=yrs)
        if not r: continue
        rows.append({"features": name, "period": lab, "trades": r["trades"],
                     "win%": round(100 * (sub.p > 0).mean(), 1),
                     "avgR": round(sub.R.mean(), 3), "ROI%": r["ROI%"],
                     "CAGR%": r["CAGR%"], "maxDD%": r["maxDD%"],
                     "Sharpe": r["Sharpe"],
                     "10-90": f"[{r['worst']:.0f}, {r['best']:.0f}]"})
print(pd.DataFrame(rows).sort_values(["period", "features"]).to_string(index=False))

print("\n" + "=" * 128)
print("IS THE INDEX MODEL RANKING STOCKS, OR RANKING DAYS?")
print("   If its score is mostly a property of the day, it is timing the")
print("   market rather than choosing stocks, and it will invert like every")
print("   other timing rule tested here.")
print("=" * 128)
for name in ["original", "+ volume", "+ index position", "+ both"]:
    col = f"p_{name}"
    day_mean = W.groupby("date")[col].transform("mean")
    total = W[col].var()
    between = day_mean.var()
    print(f"  {name:<18} share of score variance that is between-day: "
          f"{100*between/total:5.1f}%")
