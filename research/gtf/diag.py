import numpy as np, pandas as pd
tr = pd.read_csv("trades_audit_window.csv", parse_dates=["date"])
pd.set_option("display.width", 220)
print("\n" + "=" * 96)
print("What F5 actually admits (I called it 'near the 200 EMA' - it is not that)")
print("=" * 96)
print(tr.dist_ema200_atr.describe([.05, .25, .5, .75, .95]).round(2).to_string())
print(f"\nshare of trades BELOW the 200 EMA: {100*(tr.dist_ema200_atr < 0).mean():.1f}%")
print("F5 is 'not extended ABOVE the 200 EMA'. It admits deeply-below names, and")
print("most of the trades are exactly that.")

print("\n" + "=" * 96)
print("Are the results carried by a handful of very volatile names?")
print("=" * 96)
tr["atr_band"] = pd.cut(tr.atr_pct, [0, 4, 5, 6, 8, 100],
                        labels=["3.2-4%", "4-5%", "5-6%", "6-8%", ">8%"])
print(tr.groupby("atr_band", observed=True).agg(
    n=("pnl%", "size"), avg_pct=("pnl%", "mean"), avgR=("R", "mean"),
    win=("pnl%", lambda s: 100 * (s > 0).mean())).round(2).to_string())

print("\n" + "=" * 96)
print("How long does the zone wait before price comes back?")
print("=" * 96)
print(tr.zone_age.describe([.25, .5, .75, .9]).round(0).to_string())
print("\nresult by how long the zone waited:")
tr["age_band"] = pd.cut(tr.zone_age, [0, 5, 20, 60, 150, 10000],
                        labels=["1-5 bars", "6-20", "21-60", "61-150", ">150"])
print(tr.groupby("age_band", observed=True).agg(
    n=("pnl%", "size"), avg_pct=("pnl%", "mean"), avgR=("R", "mean"),
    win=("pnl%", lambda s: 100 * (s > 0).mean())).round(2).to_string())

print("\n" + "=" * 96)
print("Duplicate signals: the same zone re-entered, and clusters in one name")
print("=" * 96)
dup = tr.groupby(["symbol", "base_start"]).size()
print(f"distinct zones traded         {len(dup)}")
print(f"trades                        {len(tr)}")
print(f"zones traded more than once   {(dup > 1).sum()}  ({100*(dup>1).mean():.0f}%)")
print("\ntop symbols by trade count (one position per symbol is enforced only in the")
print("portfolio run, not in the per-trade averages):")
print(tr.symbol.value_counts().head(8).to_string())
print("\nde-duplicated to ONE trade per zone (first arrival only):")
first = tr.sort_values("date").groupby(["symbol", "base_start"], as_index=False).first()
print(f"  n={len(first)}  win={100*(first['pnl%']>0).mean():.1f}%  "
      f"avg%={first['pnl%'].mean():.2f}  avgR={first.R.mean():.3f}  "
      f"PF={first.loc[first['pnl%']>0,'pnl%'].sum()/-first.loc[first['pnl%']<=0,'pnl%'].sum():.3f}")

print("\n" + "=" * 96)
print("The gate going dark")
print("=" * 96)
q = tr.set_index("date").groupby(pd.Grouper(freq="QE")).size()
print(q.to_string())
print("\nTwo full quarters with zero signals (2025 Q3 and Q4). The volatility gate")
print("closed for six months. That is real: the strategy is not always available.")
