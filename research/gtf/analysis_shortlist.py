"""How many names should reach your eyes each week?

You will read the charts and pick. That changes what the system is for: it is
no longer choosing trades, it is choosing what you look at. Two things decide
the right size.

  QUALITY  a longer shortlist has a worse average, because it reaches deeper
           into the ranking. Every extra name you review is a slightly worse
           name than the one before it.
  FLOOR    whatever you pick, you cannot know in advance that your judgement
           helps. So the honest baseline is: what does picking at RANDOM from
           this shortlist return? Your chart reading has to beat that number
           to be worth the time. If a 5-name shortlist has a random-pick floor
           of +4% and a 12-name one has +1%, the shorter list is doing work
           your eyes would otherwise have to do.

Hard screens are applied before ranking, so nothing reaches you that failed a
rule with evidence behind it. They are deliberately few: every screen tested
here either earned its place or was dropped.
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

V = pd.read_parquet("/tmp/gtf/pool_pwin.parquet"); V["date"] = pd.to_datetime(V["date"])
V["q"] = V.date.dt.to_period("Q")
V["mark"] = V.groupby("q")["pwin"].rank(pct=True) * 100

print("=" * 112)
print("1. CANDIDATE HARD SCREENS - each tested alone, on top of the 25 Cr floor")
print("   keep a screen only if it raises avg R in BOTH periods")
print("=" * 112)
base = V
rows = [{"screen": "none (25 Cr floor only)", "kept": len(base), "share": "100%",
         "avgR full": round(base.R.mean(), 3),
         "avgR last2y": round(base[base.date >= CUT].R.mean(), 3),
         "win% last2y": round(100 * (base[base.date >= CUT].p > 0).mean(), 1)}]
SCREENS = {
    "not extended: < 3 ATR above 200 EMA": V.dist_ema200_atr < 3,
    "not extended: < 2 ATR above 200 EMA": V.dist_ema200_atr < 2,
    "above the 200 EMA at all": V.dist_ema200_atr > 0,
    "calm: 20-day vol < 40": V.vol20d < 40,
    "calm: 20-day vol < 30": V.vol20d < 30,
    "not a 6-month leader: ret_120d < 50%": V.ret_120d < 50,
    "off the 52w high: < -5%": V.pct_from_52w_high < -5,
    "not oversold-broken: RSI > 35": V.rsi14 > 35,
    "stop not absurd: ATR% < 6": V.atr_pct < 6,
    "liquid enough to exit: > 50 Cr": V.turnover_cr > 50,
}
for name, m in SCREENS.items():
    g = V[m.fillna(False)]
    g2 = g[g.date >= CUT]
    rows.append({"screen": name, "kept": len(g),
                 "share": f"{100*len(g)/len(V):.0f}%",
                 "avgR full": round(g.R.mean(), 3),
                 "avgR last2y": round(g2.R.mean(), 3),
                 "win% last2y": round(100 * (g2.p > 0).mean(), 1)})
t = pd.DataFrame(rows)
b_full, b_l2 = t.iloc[0]["avgR full"], t.iloc[0]["avgR last2y"]
t["helps both"] = ["-" if i == 0 else
                   ("yes" if (r["avgR full"] > b_full and r["avgR last2y"] > b_l2) else "no")
                   for i, r in t.iterrows()]
print(t.to_string(index=False))

# Not one screen helped in both periods, and the combination made things
# worse than no screen at all (+0.212 R against +0.258 full window, -0.150
# against -0.148 over the last two years, after discarding 61% of the pool).
# So there are no hard screens beyond the turnover floor. The ranking already
# knows about volatility and extension - they were the top features in the
# permutation test - and applying them again as hard cuts only throws away
# candidates the model had already priced.
S = V.sort_values("date").reset_index(drop=True)
DI = S.date.factorize()[0]
WK = S.date.dt.to_period("W").astype(str).to_numpy()
SY = S.symbol.to_numpy()


def shortlist(per_week):
    """Top `per_week` marks each week, one per symbol, taken as they fire."""
    order = np.lexsort((-S.pwin.to_numpy(), DI))
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
    return S.iloc[keep]


print("\n" + "=" * 124)
print("2. SHORTLIST SIZE - quality of the list, and the floor if you pick 2 at random from it")
print("=" * 124)
rows = []
for n in (2, 3, 5, 8, 12):
    sl = shortlist(n)
    sl2 = sl[sl.date >= CUT]
    row = {"shortlist/week": n, "names/year": round(len(sl) / 3.83, 0),
           "list avgR full": round(sl.R.mean(), 3),
           "list avgR last2y": round(sl2.R.mean(), 3),
           "list win% last2y": round(100 * (sl2.p > 0).mean(), 1)}
    # floor: pick 2 at random from the shortlist each week, 40 draws
    if n > 2:
        rois_f, rois_l = [], []
        for seed in range(40):
            rng = np.random.default_rng(seed)
            pick = (sl.assign(_k=rng.random(len(sl)))
                      .sort_values(["date", "_k"])
                      .groupby(sl.date.dt.to_period("W").values, group_keys=False)
                      .head(2))
            rois_f.append(PF.run(PF.arrays(pick, DMAP, NDAYS), seed=seed))
            p2 = pick[pick.date >= CUT]
            rois_l.append(PF.run(PF.arrays(p2, DMAP, NDAYS), seed=seed))
        row["floor ROI full"] = round(float(np.median(rois_f)), 1)
        row["floor ROI last2y"] = round(float(np.median(rois_l)), 1)
    else:
        r = PF.summary(PF.arrays(sl, DMAP, NDAYS), CAL, seeds=40)
        r2 = PF.summary(PF.arrays(sl2, DMAP, NDAYS), CAL, seeds=40)
        row["floor ROI full"] = r["ROI%"]; row["floor ROI last2y"] = r2["ROI%"]
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
print("\n'floor' = you review the shortlist and your judgement adds nothing.")
print("Your chart reading has to beat that number to be worth the time.")


print("\n" + "=" * 116)
print("3. WHAT A VETO COSTS - you look at the list and skip the top name")
print("   You cannot test chart judgement here, but you CAN price the")
print("   substitution: every name you skip is replaced by a worse-ranked one.")
print("=" * 116)


def pick_ranked(per_week=2, skip=0):
    """Take `per_week` names starting from rank `skip+1` of the week."""
    order = np.lexsort((-S.pwin.to_numpy(), DI))
    spent = {}; keep = []
    n = len(order); i = 0
    while i < n:
        j = i; day = DI[order[i]]
        while j < n and DI[order[j]] == day:
            j += 1
        wk = WK[order[i]]
        seen_wk, taken = spent.get(wk, (0, 0))
        if taken < per_week:
            seen = set()
            for k in order[i:j]:
                if taken >= per_week: break
                if SY[k] in seen: continue
                seen.add(SY[k])
                seen_wk += 1
                if seen_wk > skip:
                    keep.append(k); taken += 1
            spent[wk] = (seen_wk, taken)
        i = j
    return S.iloc[keep]


rows = []
for skip, lab in ((0, "take ranks 1-2 (the system)"),
                  (1, "veto rank 1, take 2-3"),
                  (2, "veto ranks 1-2, take 3-4"),
                  (4, "veto ranks 1-4, take 5-6")):
    s = pick_ranked(2, skip)
    for period, cut in (("full window", None), ("last 2 years", CUT)):
        sub = s if cut is None else s[s.date >= cut]
        if len(sub) < 40: continue
        r = PF.summary(PF.arrays(sub, DMAP, NDAYS), CAL, seeds=40)
        rows.append({"choice": lab, "period": period, "trades": r["trades"],
                     "win%": round(100 * (sub.p > 0).mean(), 1),
                     "avgR": round(sub.R.mean(), 3), "ROI%": r["ROI%"],
                     "maxDD%": r["maxDD%"]})
print(pd.DataFrame(rows).sort_values(["period", "choice"]).to_string(index=False))
