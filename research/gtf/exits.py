"""Score any (stop, target) pair in R, on the training split only."""
import numpy as np, pandas as pd

COST_PCT = 0.23

def trade_r(df, stop_col, tgt_col, max_hold=60, cost_pct=COST_PCT, time_exit=True):
    """R per trade for an arbitrary stop level and target level.

    R is measured against the actual planned risk of THIS stop, so wider stops
    are not silently credited with the tighter stop's R. Ties on a bar go to
    the stop.
    """
    entry = df["entry"].to_numpy()
    sp = df[stop_col.replace("_bar", "_px")].to_numpy()
    tp = df[tgt_col.replace("_bar", "_px")].to_numpy()
    sb = df[stop_col].to_numpy().astype(float)
    tb = df[tgt_col].to_numpy().astype(float)

    risk = entry - sp
    ok = np.isfinite(risk) & (risk > 0) & np.isfinite(tp) & (tp > entry)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)
    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)

    stop_r = (sp - entry) / risk                       # = -1 by construction
    tgt_r = (tp - entry) / risk
    # time exit at the close of the horizon
    col = {5: "ret5", 10: "ret10", 20: "ret20", 40: "ret40", 60: "ret60", 120: "ret120"}
    k = min([h for h in col if h >= max_hold], default=120)
    exit_r = (df[col[k]].to_numpy() / 100.0) * df["entry_plan"].to_numpy() / risk

    out = np.where(sb <= tb, stop_r,
                   np.where(np.isfinite(tb), tgt_r,
                            exit_r if time_exit else 0.0))
    cost_r = cost_pct / 100.0 * entry / risk
    out = out - cost_r
    return np.where(ok, out, np.nan)


def stats(r, label=""):
    r = np.asarray(r, float); r = r[np.isfinite(r)]
    if len(r) == 0:
        return {"label": label, "n": 0}
    w = r[r > 0]; l = r[r <= 0]
    eq = np.cumsum(r)
    return {"label": label, "n": len(r), "win%": 100 * len(w) / len(r),
            "avgR": r.mean(), "totR": r.sum(),
            "PF": w.sum() / -l.sum() if len(l) and l.sum() < 0 else np.inf,
            "maxDD_R": float((eq - np.maximum.accumulate(eq)).min()),
            "expR_per_100": r.mean() * 100}
