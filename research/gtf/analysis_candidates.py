import numpy as np, pandas as pd
import candidates as K
pd.set_option("display.width", 260)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
d = d[d.gap_through == 0].copy()
d["p"] = K.pct_pnl(d); d["r"] = K.r_pnl(d)
c = c.copy(); c["p"] = K.pct_pnl(c)

SPL = {"train": d.date < "2024-04-01",
       "val": (d.date >= "2024-04-01") & (d.date < "2025-07-01"),
       "test": d.date >= "2025-07-01"}
TR = d[SPL["train"]]

# thresholds are the TRAIN medians / quartiles, never tuned to val or test
q = lambda f, p: float(np.nanpercentile(TR[f], p))
TH = {"atr": q("atr_pct", 50), "legout": q("legout_atr", 50),
      "risk_lo": q("risk_pct", 40), "speed": q("prev_close_pct", 50),
      "liq": q("turnover_cr", 25)}
print("train-derived thresholds:", {k: round(v, 3) for k, v in TH.items()}, "\n")

BUY = {"very_low", "low"}; NEU = {"equilibrium", "no_supply"}
CAND = {
 "C0 every GTF arrival": lambda x: pd.Series(True, index=x.index),
 "C1 video Version A (all its filters)": lambda x: (
     (x.m_curve_state.isin(BUY) | (x.m_curve_state.isin(NEU) & x.w_trend50.eq(1)))
     & x.w_trend50.eq(1) & x.arrival.eq(0) & x.closing_ok.eq(1)
     & x.target_r_available.ge(2.0)),
 "C2 video 7/7 trade score only": lambda x: x.score.eq(7.0),
 "C3 zone width floor only": lambda x: x.risk_pct.ge(TH["risk_lo"]),
 "C4 leg-out achievement only (A5)": lambda x: x.legout_atr.ge(TH["legout"]),
 "C5 volatility only": lambda x: x.atr_pct.ge(TH["atr"]),
 "C6 approach speed only": lambda x: x.prev_close_pct.ge(TH["speed"]),
 "C7 width + achievement": lambda x: x.risk_pct.ge(TH["risk_lo"]) & x.legout_atr.ge(TH["legout"]),
 "C8 width + achievement + vol": lambda x: (x.risk_pct.ge(TH["risk_lo"])
     & x.legout_atr.ge(TH["legout"]) & x.atr_pct.ge(TH["atr"])),
 "C9 C8 + approach speed": lambda x: (x.risk_pct.ge(TH["risk_lo"])
     & x.legout_atr.ge(TH["legout"]) & x.atr_pct.ge(TH["atr"])
     & x.prev_close_pct.ge(TH["speed"])),
 "C10 C9 + weekly uptrend (video A7)": lambda x: (x.risk_pct.ge(TH["risk_lo"])
     & x.legout_atr.ge(TH["legout"]) & x.atr_pct.ge(TH["atr"])
     & x.prev_close_pct.ge(TH["speed"]) & x.w_trend50.eq(1)),
 "C11 C9 + liquidity floor": lambda x: (x.risk_pct.ge(TH["risk_lo"])
     & x.legout_atr.ge(TH["legout"]) & x.atr_pct.ge(TH["atr"])
     & x.prev_close_pct.ge(TH["speed"]) & x.turnover_cr.ge(TH["liq"])),
 "C12 C9 + near 200EMA (prior audit)": lambda x: (x.risk_pct.ge(TH["risk_lo"])
     & x.legout_atr.ge(TH["legout"]) & x.atr_pct.ge(TH["atr"])
     & x.prev_close_pct.ge(TH["speed"]) & x.dist_ema200_atr.le(0.96)),
}

rows = []
for name, fn in CAND.items():
    for split, mask in SPL.items():
        s = d[mask & fn(d)]
        st = K.summarise(s.p, name, s.r)
        st["split"] = split
        st["share%"] = round(100 * len(s) / max(1, mask.sum()), 1)
        rows.append(st)
t = pd.DataFrame(rows)
piv = t.pivot_table(index="strategy", columns="split",
                    values=["n", "avg%", "PF", "win%"], sort=False)
piv = piv.reindex(columns=["train", "val", "test"], level=1)
print("=" * 150)
print("CANDIDATE STRATEGIES - exit fixed at entry-2ATR stop / +4ATR target / 60-bar cap")
print("thresholds chosen on train only; val and test are read-only")
print("=" * 150)
print(piv.round(3).to_string())

print("\nfull detail, all splits:")
print(t[["strategy", "split", "n", "share%", "win%", "avg%", "med%", "PF",
         "maxDD%", "avgR"]].round(3).to_string(index=False))
