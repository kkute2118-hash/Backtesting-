"""Phase 16/17: candidate strategies. Selection happens on TRAIN only;
validation and test are reported, never optimised against."""
import numpy as np, pandas as pd

STOP = "sM2.0_bar"     # entry - 2 ATR, chosen on the train grid
TGT  = "gA4.0_bar"     # entry + 4 ATR
HOLD = 60

def pct_pnl(df, stop_col=STOP, tgt_col=TGT, max_hold=HOLD, cost=0.23):
    e = df["entry"].to_numpy()
    sp = df[stop_col.replace("_bar", "_px")].to_numpy()
    tp = df[tgt_col.replace("_bar", "_px")].to_numpy()
    sb = df[stop_col].to_numpy().astype(float); tb = df[tgt_col].to_numpy().astype(float)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)
    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)
    col = {5: "ret5", 10: "ret10", 20: "ret20", 40: "ret40", 60: "ret60", 120: "ret120"}
    k = min([h for h in col if h >= max_hold], default=120)
    out = np.where(sb <= tb, 100 * (sp / e - 1),
                   np.where(np.isfinite(tb), 100 * (tp / e - 1), df[col[k]].to_numpy()))
    ok = np.isfinite(sp) & np.isfinite(tp) & (tp > e) & (sp < e)
    return np.where(ok, out - cost, np.nan)

def r_pnl(df, **kw):
    """R against the PLANNED risk (proximal to stop), not the realised fill.

    A gap that opens just above the stop collapses the realised risk to a
    fraction of a percent, and dividing by that turns an ordinary winner into
    a 39R trade. It hits 0.38% of arrivals, which is more than enough to move
    a mean. Planned risk is what the position was actually sized on, so it is
    also the honest denominator.
    """
    p = pct_pnl(df, **kw)
    ep = df["entry_plan"].to_numpy()
    sp = df[kw.get("stop_col", STOP).replace("_bar", "_px")].to_numpy()
    return p / (100 * (ep - sp) / ep)


def outcome(df, max_hold=HOLD):
    sb = df[STOP].to_numpy().astype(float); tb = df[TGT].to_numpy().astype(float)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)
    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)
    return np.where(np.isinf(sb) & np.isinf(tb), "time",
                    np.where(sb <= tb, "stop", "target"))


def bars_held(df, max_hold=HOLD):
    sb = df[STOP].to_numpy().astype(float); tb = df[TGT].to_numpy().astype(float)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)
    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)
    return np.minimum(np.minimum(sb, tb), max_hold)

def summarise(p, label, r=None):
    p = np.asarray(p, float); m = np.isfinite(p); p = p[m]
    if len(p) == 0:
        return {"strategy": label, "n": 0}
    eq = np.cumsum(p)
    w = p[p > 0]; l = p[p <= 0]
    d = {"strategy": label, "n": len(p), "win%": 100 * len(w) / len(p),
         "avg%": p.mean(), "med%": float(np.median(p)), "tot%": p.sum(),
         "PF": w.sum() / -l.sum() if l.sum() < 0 else np.inf,
         "maxDD%": float((eq - np.maximum.accumulate(eq)).min())}
    if r is not None:
        r = np.asarray(r, float)[m]
        d["avgR"] = float(np.nanmean(r))
    return d

def block_boot(dates, p, n=2000, seed=3):
    s = pd.DataFrame({"p": p, "k": pd.DatetimeIndex(dates).to_period("M").astype(str)})
    s = s[np.isfinite(s.p)]
    grp = [g["p"].to_numpy() for _, g in s.groupby("k")]
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    for i in range(n):
        pick = rng.integers(0, len(grp), len(grp))
        out[i] = np.concatenate([grp[q] for q in pick]).mean()
    return np.percentile(out, [2.5, 97.5])
