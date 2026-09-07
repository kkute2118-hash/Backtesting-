"""The top of the mark scale is the worst part of it.

Win rate rises with the mark up to about 95 and then FALLS:

  full window   75-90: 30.7%   90-95: 30.8%   95-99: 30.5%   99+: 26.7%
  last 2 years  75-90: 25.4%   90-95: 25.7%   95-99: 27.1%   99+: 22.5%

system.py takes the highest-marked candidates of the week, which is exactly
the band that misbehaves. So: does capping the mark - taking the best
candidate BELOW some ceiling instead of the outright best - do better?
"""
import numpy as np, pandas as pd, sqlite3
import portfolio as PF
pd.set_option("display.width", 240)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
CUT = pd.Timestamp("2024-09-04")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con); con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values); DMAP = {v: i for i, v in enumerate(CAL)}
NDAYS = len(CAL)

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet"); V["date"] = pd.to_datetime(V["date"])
V["q"] = V.date.dt.to_period("Q")
V["mark"] = V.groupby("q")["pwin"].rank(pct=True) * 100
V = V.sort_values("date").reset_index(drop=True)
DI = V.date.factorize()[0]
WK = V.date.dt.to_period("W").astype(str).to_numpy()
SY = V.symbol.to_numpy()


def pick(key, per_week=2, eligible=None):
    ok = np.ones(len(V), bool) if eligible is None else eligible.to_numpy()
    k = np.where(ok, key, -np.inf)
    order = np.lexsort((-k, DI))
    spent = {}; keep = []
    n = len(order); i = 0
    while i < n:
        j = i; day = DI[order[i]]
        while j < n and DI[order[j]] == day:
            j += 1
        wk = WK[order[i]]; used = spent.get(wk, 0)
        if used < per_week:
            seen = set()
            for kk in order[i:j]:
                if used >= per_week or not np.isfinite(k[kk]):
                    break
                if SY[kk] in seen:
                    continue
                seen.add(SY[kk]); keep.append(kk); used += 1
            spent[wk] = used
        i = j
    return V.iloc[keep]


print("what marks do the weekly picks actually land on?")
base = pick(V.pwin.to_numpy())
print(base["mark"].describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())
print(f"\nshare of picks above mark 99: {100*(base['mark']>99).mean():.0f}%")

print("\n" + "=" * 124)
print("CAPPING THE MARK - take the best candidate below the ceiling")
print("Rs 10,00,000, 1% risk, no leverage, median of 40 orderings")
print("=" * 124)
rows = []
CAPS = {"no cap (current system)": None, "cap at 99.9": 99.9, "cap at 99.5": 99.5,
        "cap at 99": 99.0, "cap at 98": 98.0, "cap at 95": 95.0}
for name, cap in CAPS.items():
    elig = pd.Series(True, index=V.index) if cap is None else (V["mark"] <= cap)
    s = pick(V.pwin.to_numpy(), eligible=elig)
    for lab, cut in (("full window", None), ("last 2 years", CUT)):
        sub = s if cut is None else s[s.date >= cut]
        if len(sub) < 40: continue
        yrs = (sub.date.max() - sub.date.min()).days / 365.25
        r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=40, years=yrs)
        if not r: continue
        rows.append({"rule": name, "period": lab, "trades": r["trades"],
                     "win%": round(100 * (sub.p > 0).mean(), 1),
                     "avgR": round(sub.R.mean(), 3),
                     "ROI%": r["ROI%"], "CAGR%": r["CAGR%"], "maxDD%": r["maxDD%"],
                     "Sharpe": r["Sharpe"], "worst": r["worst"]})
t = pd.DataFrame(rows)
print(t.sort_values(["period", "rule"]).to_string(index=False))
