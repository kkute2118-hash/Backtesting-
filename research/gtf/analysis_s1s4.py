"""S1-S4: is the setup score still inversely predictive after the look-ahead
fix, and can a score built from the outcomes do better?

Same discipline as the GTF work: discovery on train only, a model refit
quarterly on past data, and the held-out periods read once.
"""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/s1s4.parquet")
d["date"] = pd.to_datetime(d["signal_date"])
d = d.sort_values("date").reset_index(drop=True)
print(f"{len(d)} signals, {d.ticker.nunique()} symbols, "
      f"{d.date.min().date()} .. {d.date.max().date()}")
print(d.groupby("strategy").agg(n=("score", "size"), win=("r_multiple", lambda s: 100*(s>0).mean()),
                                avgR=("r_multiple", "mean"), avg_pct=("return_pct", "mean")).round(3).to_string())

COST_R = None   # the engine's r_multiple is already net of its own assumptions
d["y"] = d["r_multiple"].astype(float)
TR = d.date < "2024-04-01"
VA = (d.date >= "2024-04-01") & (d.date < "2025-07-01")
TE = d.date >= "2025-07-01"
print(f"\ntrain {TR.sum()}  val {VA.sum()}  test {TE.sum()}")

print("\n" + "=" * 108)
print("1. THE EXISTING SETUP SCORE, after the look-ahead fix")
print("=" * 108)
bands = [(0,50),(50,60),(60,70),(70,75),(75,80),(80,85),(85,90),(90,101)]
rows = []
for lo, hi in bands:
    m = (d.score >= lo) & (d.score < hi)
    r = {"score band": f"{lo}-{hi-1}", "n": int(m.sum())}
    for nm, sp in (("train", TR), ("val", VA), ("test", TE)):
        s = d.loc[m & sp, "y"]
        r[f"avgR_{nm}"] = round(s.mean(), 3) if len(s) >= 100 else np.nan
        r[f"win%_{nm}"] = round(100*(s > 0).mean(), 1) if len(s) >= 100 else np.nan
    rows.append(r)
t = pd.DataFrame(rows)
print(t.to_string(index=False))
lo_band = d.loc[(d.score < 70), "y"].mean(); hi_band = d.loc[(d.score >= 85), "y"].mean()
print(f"\n  under 70 -> {lo_band:+.3f} R      85 and over -> {hi_band:+.3f} R      "
      f"spread {hi_band-lo_band:+.3f}")

print("\n" + "=" * 108)
print("2. THE SCORE'S OWN COMPONENTS")
print("=" * 108)
for c in ["score_htf", "score_footprint", "score_entry_quality", "score_relative_strength",
          "safety_score"]:
    if c not in d.columns: continue
    q = pd.qcut(d[c], 5, labels=False, duplicates="drop")
    if q is None or pd.isna(q).all(): continue
    g = d.assign(q=q).groupby("q")["y"].mean()
    if len(g) >= 3:
        print(f"  {c:<26} bottom {g.iloc[0]:+.3f}  top {g.iloc[-1]:+.3f}  "
              f"spread {g.iloc[-1]-g.iloc[0]:+.3f}")

FEATS = [c for c in ["dist_ema20_atr","dist_ema50_atr","dist_ema200_atr","atr_pct","relvol",
          "relvol_trend","candle_body_pct","candle_upper_wick_pct","candle_lower_wick_pct",
          "breakout_20d","breakout_50d","pullback_depth_pct","dist_recent_high_atr",
          "dist_recent_low_atr","dist_resistance_atr","dist_support_atr","gap_pct","macd_hist",
          "rsi14","retracement_pct","retracement_duration_bars","retracement_volume_ratio",
          "reclaim_candle","rejection_candle","market_breadth","safety_score","expected_rr",
          "stop_distance_pct","target_distance_pct","atr_adjusted_stop","score_htf",
          "score_footprint","score_entry_quality","score_relative_strength","score"]
         if c in d.columns]
for c in FEATS:
    d[c] = pd.to_numeric(d[c], errors="coerce")

print("\n" + "=" * 108)
print("3. A REPLACEMENT SCORE, refit every quarter on past data only")
print("=" * 108)
d["q"] = d.date.dt.to_period("Q")
d["pred"] = np.nan; d["thr"] = np.nan
for qq in sorted(d.q.unique()):
    past = d[(d.q < qq) & (d.date < qq.start_time - pd.Timedelta(days=95))]
    if len(past) < 8000: continue
    use = [f for f in FEATS if past[f].notna().sum() > 200 and past[f].nunique() > 1]
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                      min_samples_leaf=100, l2_regularization=1.0,
                                      random_state=0).fit(past[use].to_numpy(), past.y.to_numpy())
    sel = d.q == qq
    d.loc[sel, "pred"] = m.predict(d.loc[sel, use].to_numpy())
    d.loc[sel, "thr"] = float(np.percentile(m.predict(past[use].to_numpy()), 90))
W = d[d.pred.notna()].copy()
print(f"scored out of sample: {len(W)} signals, {W.date.min().date()} .. {W.date.max().date()}")
W["dec"] = W.groupby("q")["pred"].transform(lambda s: pd.qcut(s, 10, labels=False, duplicates="drop"))
print("\ndecile of the NEW score (walk-forward), against the OLD score's decile:")
W["odec"] = W.groupby("q")["score"].transform(lambda s: pd.qcut(s.rank(method="first"), 10, labels=False, duplicates="drop"))
cmp = pd.DataFrame({
    "new score avgR": W.groupby("dec")["y"].mean(),
    "new score win%": W.groupby("dec")["y"].apply(lambda s: 100*(s > 0).mean()),
    "old score avgR": W.groupby("odec")["y"].mean(),
    "old score win%": W.groupby("odec")["y"].apply(lambda s: 100*(s > 0).mean()),
    "n": W.groupby("dec").size()})
print(cmp.round(3).to_string())

print("\n" + "=" * 108)
print("4. HEAD TO HEAD, walk-forward")
print("=" * 108)
rows = []
for nm, m in (("every signal", pd.Series(True, index=W.index)),
              ("old score >= 85 (the live gate)", W.score >= 85),
              ("old score >= 90", W.score >= 90),
              ("new score, top decile", W.pred >= W.thr),
              ("new score top decile AND old >= 85", (W.pred >= W.thr) & (W.score >= 85))):
    s = W.loc[m, "y"]
    if len(s) < 30: 
        rows.append({"selection": nm, "n": len(s)}); continue
    w = s[s > 0]; l = s[s <= 0]
    rows.append({"selection": nm, "n": len(s), "win%": round(100*len(w)/len(s), 1),
                 "avgR": round(s.mean(), 3), "totR": round(s.sum(), 1),
                 "PF": round(w.sum()/-l.sum(), 2) if l.sum() < 0 else np.inf})
print(pd.DataFrame(rows).to_string(index=False))

print("\nby strategy, new score top decile:")
sub = W[W.pred >= W.thr]
print(sub.groupby("strategy").agg(n=("y","size"), win=("y", lambda s: 100*(s>0).mean()),
                                  avgR=("y","mean")).round(3).to_string())
W.to_parquet("/tmp/gtf/s1s4_scored.parquet", index=False)
