"""Phases 26-28 again, this time with the placebo alongside, and in percent of
capital as well as R - because R with a variable stop distance quietly rewards
the thinnest zones with leverage nobody can actually take."""
import numpy as np, pandas as pd
import exits as X
pd.set_option("display.width", 260)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
d = d[d.gap_through == 0]
TR = d[d.date < "2024-04-01"]; CTR = c[c.date < "2024-04-01"]
print(f"train: {len(TR)} events, {len(CTR)} controls\n")

def pct_pnl(df, stop_col, tgt_col, max_hold=60, cost=0.23):
    """P&L in percent of the position, which is size-neutral."""
    e = df["entry"].to_numpy()
    sp = df[stop_col.replace("_bar", "_px")].to_numpy()
    tp = df[tgt_col.replace("_bar", "_px")].to_numpy()
    sb = df[stop_col].to_numpy().astype(float); tb = df[tgt_col].to_numpy().astype(float)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)
    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)
    col = {5: "ret5", 10: "ret10", 20: "ret20", 40: "ret40", 60: "ret60", 120: "ret120"}
    k = min([h for h in col if h >= max_hold], default=120)
    timeout = df[col[k]].to_numpy()
    out = np.where(sb <= tb, 100 * (sp / e - 1),
                   np.where(np.isfinite(tb), 100 * (tp / e - 1), timeout))
    ok = np.isfinite(sp) & np.isfinite(tp) & (tp > e) & (sp < e)
    return np.where(ok, out - cost, np.nan)

STOPS = [("sK0.0_bar", "distal (video)"), ("sK0.5_bar", "distal-0.5ATR"),
         ("sM1.5_bar", "entry-1.5ATR"), ("sM2.0_bar", "entry-2.0ATR"),
         ("sM3.0_bar", "entry-3.0ATR")]
TGTS = [("gA2.0_bar", "+2ATR"), ("gA3.0_bar", "+3ATR"), ("gA4.0_bar", "+4ATR"),
        ("gA5.0_bar", "+5ATR"), ("gA6.0_bar", "+6ATR"), ("gA8.0_bar", "+8ATR")]

for metric, fn, unit in (("avg R", X.trade_r, "R"), ("avg % per trade", pct_pnl, "%")):
    print("=" * 128)
    print(f"{metric.upper()} - GTF arrivals MINUS matched placebo (train, 60-bar cap)")
    print("=" * 128)
    real = pd.DataFrame(index=[s[1] for s in STOPS], columns=[t[1] for t in TGTS], dtype=float)
    ctrl = real.copy(); edge = real.copy()
    for sc, sl in STOPS:
        for tc, tl in TGTS:
            real.loc[sl, tl] = np.nanmean(fn(TR, sc, tc))
            ctrl.loc[sl, tl] = np.nanmean(fn(CTR, sc, tc))
            edge.loc[sl, tl] = real.loc[sl, tl] - ctrl.loc[sl, tl]
    print(f"real ({unit}):");  print(real.round(3).to_string())
    print(f"\nplacebo ({unit}):"); print(ctrl.round(3).to_string())
    print(f"\nEDGE = real - placebo ({unit}):"); print(edge.round(3).to_string())
    print()

print("=" * 128)
print("Holding cap, real vs placebo, at distal stop / +4ATR target")
print("=" * 128)
rows = []
for h in (10, 20, 40, 60, 120):
    rr = X.trade_r(TR, "sK0.0_bar", "gA4.0_bar", max_hold=h)
    cc = X.trade_r(CTR, "sK0.0_bar", "gA4.0_bar", max_hold=h)
    rp = pct_pnl(TR, "sK0.0_bar", "gA4.0_bar", max_hold=h)
    cp = pct_pnl(CTR, "sK0.0_bar", "gA4.0_bar", max_hold=h)
    rows.append({"hold": h, "real_R": np.nanmean(rr), "ctrl_R": np.nanmean(cc),
                 "edge_R": np.nanmean(rr) - np.nanmean(cc),
                 "real_%": np.nanmean(rp), "ctrl_%": np.nanmean(cp),
                 "edge_%": np.nanmean(rp) - np.nanmean(cp)})
print(pd.DataFrame(rows).round(3).to_string(index=False))
