import numpy as np, pandas as pd
import ratchet as R
pd.set_option("display.width", 230)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

ev = pd.read_parquet("/tmp/gtf/events.parquet"); ev["date"] = pd.to_datetime(ev["date"])
ev = ev[(ev.gap_through == 0) & ev.score.eq(7.0) & ev.turnover_cr.ge(10)].reset_index(drop=True)
print(f"{len(ev)} 7/7 trades\n")
res, bars = R.run_all(ev, DB)
for k, v in res.items():
    ev["p_" + k] = v; ev["b_" + k] = bars[k]
ev.to_parquet("/tmp/gtf/ratchet7.parquet", index=False)

TR = ev.date < "2024-04-01"
VA = (ev.date >= "2024-04-01") & (ev.date < "2025-07-01")
TE = ev.date >= "2025-07-01"
rows = []
for k in res:
    r = R.stats(ev["p_" + k], k)
    r["train"] = round(np.nanmean(ev.loc[TR, "p_" + k]), 2)
    r["val"] = round(np.nanmean(ev.loc[VA, "p_" + k]), 2)
    r["test"] = round(np.nanmean(ev.loc[TE, "p_" + k]), 2)
    r["med bars"] = int(np.nanmedian(ev["b_" + k]))
    rows.append(r)
t = pd.DataFrame(rows).sort_values("avg%", ascending=False)
print("=" * 140)
print("RATCHET SCHEDULES on the 7/7 signal set (liquidity floor applied)")
print("=" * 140)
print(t.to_string(index=False))
