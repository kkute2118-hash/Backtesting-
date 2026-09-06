"""Does the zone carry information, or is this just a bull market?"""
import numpy as np, pandas as pd
import evaluate as E
pd.set_option("display.width", 220)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])
d = d[d.gap_through == 0]

BUY = {"very_low", "low"}; NEU = {"equilibrium", "no_supply"}
A = d[(d.m_curve_state.isin(BUY) | (d.m_curve_state.isin(NEU) & d.w_trend50.eq(1)))
      & d.w_trend50.eq(1) & d.arrival.eq(0) & d.closing_ok.eq(1)
      & d.target_r_available.ge(2.0)]

rows = []
for tgt in (1.0, 2.0, 3.0):
    rows.append(E.summarise(E.r_of(d, "R", tgt), f"all GTF arrivals   @ {tgt}R"))
    rows.append(E.summarise(E.r_of(c, "R", tgt), f"matched control    @ {tgt}R"))
    rows.append(E.summarise(E.r_of(A, "R", tgt), f"Version A (video)  @ {tgt}R"))
print("=" * 100)
print("PLACEBO TEST - same symbol, same month, same planned risk, random bar")
print("=" * 100)
print(E.table(rows).to_string(index=False))

# the control is matched on risk_pct, so compare like-for-like inside risk buckets
print("\navgR @2R by planned-risk bucket (real vs control):")
bins = [0, 1.5, 2.5, 4.0, 6.0, 100]
out = []
for lo, hi in zip(bins[:-1], bins[1:]):
    dr = d[(d.risk_pct >= lo) & (d.risk_pct < hi)]
    cr = c[(c.risk_pct >= lo) & (c.risk_pct < hi)]
    ar = A[(A.risk_pct >= lo) & (A.risk_pct < hi)]
    out.append({"risk%": f"{lo}-{hi}", "n_real": len(dr),
                "real": E.r_of(dr, "R", 2.0).mean() if len(dr) else np.nan,
                "control": E.r_of(cr, "R", 2.0).mean() if len(cr) else np.nan,
                "VersionA": E.r_of(ar, "R", 2.0).mean() if len(ar) > 30 else np.nan,
                "n_A": len(ar)})
print(pd.DataFrame(out).round(3).to_string(index=False))

print("\nby year, avgR @2R:")
yr = []
for y in range(2021, 2027):
    dr = d[d.date.dt.year == y]; cr = c[c.date.dt.year == y]; ar = A[A.date.dt.year == y]
    yr.append({"year": y, "n_real": len(dr),
               "real": E.r_of(dr, "R", 2.0).mean() if len(dr) else np.nan,
               "control": E.r_of(cr, "R", 2.0).mean() if len(cr) else np.nan,
               "VersionA": E.r_of(ar, "R", 2.0).mean() if len(ar) > 30 else np.nan,
               "n_A": len(ar)})
print(pd.DataFrame(yr).round(3).to_string(index=False))

# block bootstrap by calendar month: the events overlap heavily, so the naive
# t-statistic is not a significance test
def block_boot(df, r, n_boot=2000, seed=1):
    s = pd.DataFrame({"r": r, "k": df["date"].dt.to_period("M").astype(str).to_numpy()})
    s = s[np.isfinite(s.r)]
    grp = [g["r"].to_numpy() for _, g in s.groupby("k")]
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(grp), len(grp))
        means[i] = np.concatenate([grp[p] for p in pick]).mean()
    return np.percentile(means, [2.5, 50, 97.5])

print("\nmonth-block bootstrap of mean R (2.5 / 50 / 97.5 pct), 2000 resamples:")
for nm, sub in (("all arrivals", d), ("control", c), ("Version A", A)):
    lo, mid, hi = block_boot(sub, E.r_of(sub, "R", 2.0))
    print(f"  {nm:15s} {lo:+.3f}  {mid:+.3f}  {hi:+.3f}")

print("\nVersion A with the video's own target rule (A11), bug fixed:")
print(E.table([E.summarise(E.r_of(A, "wsup"), "A / weekly-supply target"),
               E.summarise(E.r_of(A, "R", 2.0), "A / flat 2R")]).to_string(index=False))
