"""Index timing as a GATE, not as a model feature.

Three different things have now been asked of index position, and they are not
the same question:

  1. as model features        - tested, failed badly (-12.9% last 2 years,
                                86% of score variance between-day)
  2. as a strength gate       - tested, failed monotonically (index above its
                                200 DMA, breadth > 40%, > 50%)
  3. as a "how far off the
     recent low" gate         - NOT yet tested as a gate. The band table
                                pointed at it, so it is tested here.

Caveat carried into the result: the 10% threshold comes from looking at the
band table on this same data. That is one step short of fitting, so the
thresholds either side are shown too, and a rule that only works at one of
them is a fitted rule rather than an effect.
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
# the index columns are already on the pool: rank.prepare() attaches them
W = W.sort_values("date").reset_index(drop=True)
DI = W.date.factorize()[0]
WK = W.date.dt.to_period("W").astype(str).to_numpy()
SY = W.symbol.to_numpy()
KEY = W["p_+ volume"].to_numpy()          # the marking we actually ship


def pick(eligible=None, per_week=2):
    k = KEY.copy()
    if eligible is not None:
        k = np.where(eligible.to_numpy(), k, -np.inf)
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
                if used >= per_week or not np.isfinite(k[kk]): break
                if SY[kk] in seen: continue
                seen.add(SY[kk]); keep.append(kk); used += 1
            spent[wk] = used
        i = j
    return W.iloc[keep]


GATES = {
    "no gate (the system)": None,
    "index > 5% above its 60d low": W.idx_above_60d_low > 5,
    "index > 10% above its 60d low": W.idx_above_60d_low > 10,
    "index > 15% above its 60d low": W.idx_above_60d_low > 15,
    "index within 1 SD of its 20 EMA": W.idx_from_ema20_sd.abs() < 1,
    "index above its 20 EMA": W.idx_from_ema20_sd > 0,
    "index above its 50 EMA": W.idx_from_ema50_sd > 0,
}

print("=" * 132)
print("INDEX TIMING AS A GATE - 2 a week, Rs 10,00,000, 1% risk, median of 40 orderings")
print("=" * 132)
rows = []
for name, g in GATES.items():
    s = pick(None if g is None else g.fillna(False))
    for lab, cut in (("full window", None), ("last 2 years", CUT)):
        sub = s if cut is None else s[s.date >= cut]
        if len(sub) < 30: 
            rows.append({"gate": name, "period": lab, "trades": len(sub)}); continue
        yrs = (sub.date.max() - sub.date.min()).days / 365.25
        r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=40, years=yrs)
        if not r: continue
        rows.append({"gate": name, "period": lab, "signals": len(sub),
                     "trades": r["trades"], "win%": round(100 * (sub.p > 0).mean(), 1),
                     "avgR": round(sub.R.mean(), 3), "ROI%": r["ROI%"],
                     "CAGR%": r["CAGR%"], "maxDD%": r["maxDD%"], "Sharpe": r["Sharpe"],
                     "worst": r["worst"]})
t = pd.DataFrame(rows)
print(t.sort_values(["period", "gate"]).to_string(index=False))

print("\n" + "=" * 132)
print("TIME OUT OF THE MARKET - what each gate costs you in opportunity")
print("=" * 132)
day = W.drop_duplicates("date").set_index("date").sort_index()
for name, g in GATES.items():
    if g is None: continue
    m = g.reindex(W.index).fillna(False)
    dd = W.assign(ok=m.values).drop_duplicates("date").set_index("date")["ok"].sort_index()
    yr = dd.groupby(dd.index.year).mean().mul(100).round(0).astype(int)
    print(f"  {name:<36} " + "  ".join(f"{y}:{v:>3}%" for y, v in yr.items()))
