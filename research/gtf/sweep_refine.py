"""Refine the sweep on pre-2024 data only, then read the last two years once."""
import numpy as np, pandas as pd
pd.set_option("display.width", 230)
d = pd.read_parquet("/tmp/gtf/sweep.parquet"); d["date"] = pd.to_datetime(d["date"])
TR = d[d.date < "2024-01-01"]; TE = d[d.date >= "2024-09-04"]
print(f"train (pre-2024) {len(TR)}   held out (last 2y) {len(TE)}\n")

def st(x, lab):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 20: return {"filter": lab, "n": len(x)}
    w = x[x > 0]; l = x[x <= 0]
    return {"filter": lab, "n": len(x), "win%": round(100*len(w)/len(x), 1),
            "avg%": round(x.mean(), 2), "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf}

# thresholds are the pre-2024 medians of the features that looked strongest
q = lambda f, p: float(np.nanpercentile(TR[f], p))
TH = {"depth": q("sweep_depth_atr", 50), "slope": q("weekly_slope_pct", 60),
      "atr": q("atr_pct", 60), "ema200": q("dist_ema200_atr", 40)}
print("pre-2024 thresholds:", {k: round(v, 2) for k, v in TH.items()}, "\n")

FILTERS = {
    "all setups": lambda x: pd.Series(True, index=x.index),
    "deep sweep": lambda x: x.sweep_depth_atr >= TH["depth"],
    "steep weekly trend": lambda x: x.weekly_slope_pct >= TH["slope"],
    "high volatility": lambda x: x.atr_pct >= TH["atr"],
    "above 200 EMA": lambda x: x.dist_ema200_atr >= TH["ema200"],
    "deep + steep": lambda x: (x.sweep_depth_atr >= TH["depth"]) & (x.weekly_slope_pct >= TH["slope"]),
    "deep + steep + vol": lambda x: ((x.sweep_depth_atr >= TH["depth"])
                                     & (x.weekly_slope_pct >= TH["slope"])
                                     & (x.atr_pct >= TH["atr"])),
    "all four": lambda x: ((x.sweep_depth_atr >= TH["depth"])
                           & (x.weekly_slope_pct >= TH["slope"])
                           & (x.atr_pct >= TH["atr"])
                           & (x.dist_ema200_atr >= TH["ema200"])),
}
rows = []
for nm, fn in FILTERS.items():
    a = st(TR.loc[fn(TR), "p_be15"], nm); b = st(TE.loc[fn(TE), "p_be15"], nm)
    rows.append({"filter": nm,
                 "train n": a.get("n"), "train avg%": a.get("avg%"), "train PF": a.get("PF"),
                 "HELD OUT n": b.get("n"), "HELD OUT avg%": b.get("avg%"), "HELD OUT PF": b.get("PF")})
print("=" * 108)
print("REFINED ON PRE-2024, READ ONCE ON THE LAST TWO YEARS")
print("=" * 108)
print(pd.DataFrame(rows).to_string(index=False))

print("\nfor reference, on the same exit and the same held-out window:")
g = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g["date"] = pd.to_datetime(g["date"])
g = g[(g.date >= "2024-09-04") & g.turnover_cr.ge(10)]
print(" ", st(g["p_breakeven only at +15%"], "GTF 7/7 + liquidity"))
s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet"); s4["date"] = pd.to_datetime(s4["entry_date"])
print(" ", st(s4.loc[s4.strategy.eq("S4") & (s4.date >= "2024-09-04"), "p_be15"], "S4"))
