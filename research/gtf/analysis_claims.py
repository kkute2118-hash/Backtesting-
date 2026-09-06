"""Phase 11-14/18: test the video's claims one at a time, on training data,
then report the same cut on validation and test."""
import numpy as np, pandas as pd
import evaluate as E
pd.set_option("display.width", 240)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
d = d[d.gap_through == 0].copy()
d["R"] = E.r_of(d, "R", 2.0)
TR = d[d.date < "2024-04-01"]
VA = d[(d.date >= "2024-04-01") & (d.date < "2025-07-01")]
TE = d[d.date >= "2025-07-01"]
print(f"train {len(TR)}  val {len(VA)}  test {len(TE)}\n")

def cut(col, groups, title, minn=200):
    rows = []
    for label, mask_fn in groups:
        r = []
        for nm, sub in (("train", TR), ("val", VA), ("test", TE)):
            m = mask_fn(sub)
            s = sub[m]
            r.append((len(s), s.R.mean() if len(s) >= minn else np.nan))
        rows.append({"bucket": label,
                     "n_tr": r[0][0], "avgR_tr": r[0][1],
                     "n_va": r[1][0], "avgR_va": r[1][1],
                     "n_te": r[2][0], "avgR_te": r[2][1]})
    t = pd.DataFrame(rows)
    t["agree"] = np.sign(t.avgR_tr) == np.sign(t.avgR_va)
    t["agree3"] = t.agree & (np.sign(t.avgR_tr) == np.sign(t.avgR_te))
    print(f"--- {title}")
    print(t.round(3).to_string(index=False)); print()
    return t

# ---- A12 the trade score: does a higher score mean a better outcome?
cut("score", [(f"score {s}", (lambda s: (lambda x: x.score.eq(s)))(s))
              for s in sorted(d.score.unique())], "CLAIM A12: trade score is monotone in outcome")

cut("freshness", [("fresh (arrival 0)", lambda x: x.arrival.eq(0)),
                  ("tested once", lambda x: x.arrival.eq(1)),
                  ("tested twice", lambda x: x.arrival.eq(2))],
    "CLAIM A4: a fresh zone beats a tested one")

cut("legout", [("1 leg-out, no gap", lambda x: x.legout_n.eq(1) & x.gap.eq(0)),
               ("1 leg-out + gap", lambda x: x.legout_n.eq(1) & x.gap.eq(1)),
               ("2 leg-outs", lambda x: x.legout_n.eq(2)),
               ("3+ leg-outs", lambda x: x.legout_n.ge(3))],
    "CLAIM A12-strength: more/gapped leg-outs mean a stronger zone")

cut("base", [("1-3 base candles", lambda x: x.n_base.le(3)),
             ("4-5 base candles", lambda x: x.n_base.between(4, 5)),
             ("6+ base candles", lambda x: x.n_base.ge(6))],
    "CLAIM A12-time: fewer base candles mean a stronger zone")

cut("closing", [("closing ok", lambda x: x.closing_ok.eq(1)),
                ("closing not ok", lambda x: x.closing_ok.eq(0))],
    "CLAIM A6: the leg-out must close above the leg-in high")

cut("trend", [("weekly trend up", lambda x: x.w_trend50.eq(1)),
              ("weekly sideways", lambda x: x.w_trend50.eq(0)),
              ("weekly trend down", lambda x: x.w_trend50.eq(-1))],
    "CLAIM A7: buy demand only in an uptrend (trending timeframe)")

cut("dtrend", [("daily trend up", lambda x: x.d_trend.eq(1)),
               ("daily trend down", lambda x: x.d_trend.eq(-1))],
    "CLAIM A7-variant: the same rule read on the execution timeframe instead")

cut("mcurve", [(f"monthly {s}", (lambda s: (lambda x: x.m_curve_state.eq(s)))(s))
               for s in ["very_low", "low", "equilibrium", "high", "very_high",
                         "no_supply", "no_demand"]],
    "CLAIM A9: position on the monthly curve decides buyer or seller")

cut("wcurve", [(f"weekly {s}", (lambda s: (lambda x: x.w_curve_state.eq(s)))(s))
               for s in ["very_low", "low", "equilibrium", "high", "very_high",
                         "no_supply", "no_demand"]],
    "CLAIM A9 on the weekly curve (better supported by 5.5y of data)")

cut("pattern", [("DBR (reversal)", lambda x: x.pattern.eq("DBR")),
                ("RBR (continuation)", lambda x: x.pattern.eq("RBR"))],
    "CLAIM A2: reversal vs continuation demand patterns")

cut("coincide", [("daily zone sits on the monthly zone", lambda x: x.coincide.eq(1)),
                 ("it does not", lambda x: x.coincide.eq(0))],
    "CLAIM A13/'fully coinciding': execution stacked on location")

# ---- quintile screen over the continuous features (Phase 18)
print("=" * 120)
print("FEATURE SCREEN - mean R by quintile, train / val / test. 'years_agree' is what separates")
print("a relationship from a coincidence.")
print("=" * 120)
feats = ["dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr", "rsi14", "atr_pct",
         "relvol", "risk_pct", "zone_h_pct", "legout_atr", "zone_age",
         "target_r_available", "gap_in", "turnover_cr", "prev_close_pct", "score"]
rows = []
for f in feats:
    q = pd.qcut(TR[f], 5, labels=False, duplicates="drop")
    if q is None or q.nunique() < 3:
        continue
    edges = np.nanpercentile(TR[f].dropna(), [0, 20, 40, 60, 80, 100])
    def band(sub, k):
        lo, hi = edges[k], edges[k + 1]
        m = (sub[f] >= lo) & (sub[f] <= hi) if k == 4 else (sub[f] >= lo) & (sub[f] < hi)
        return sub[m].R.mean() if m.sum() >= 150 else np.nan
    bt, tt = band(TR, 0), band(TR, 4)
    bv, tv = band(VA, 0), band(VA, 4)
    be, te = band(TE, 0), band(TE, 4)
    rows.append({"feature": f, "bot_tr": bt, "top_tr": tt, "spread_tr": tt - bt,
                 "spread_va": tv - bv, "spread_te": te - be,
                 "agree3": (np.sign(tt - bt) == np.sign(tv - bv) == np.sign(te - be))})
print(pd.DataFrame(rows).sort_values("spread_tr").round(3).to_string(index=False))
