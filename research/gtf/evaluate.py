"""Turn GTF arrival events into trades under an explicit exit policy.

Kept separate from event generation on purpose: events are expensive and fixed,
exit policies are cheap and are the thing under study, so every policy is
scored against exactly the same arrivals.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COST_PCT = 0.23      # round-trip brokerage + STT + impact, from the prior audit


def r_of(df, target_mode="R", target=2.0, max_hold=60, cost_pct=COST_PCT,
         stop_first=True):
    """Realised R per event.

    target_mode:
      "R"    - fixed R multiple
      "pct"  - fixed percentage move
      "wsup" - the video's rule: proximal of the fresh supply zone on the
               trending timeframe, read at arrival (A11)
    Ties on the same bar resolve to the stop, because intrabar order is
    unknowable and the optimistic reading is how backtests flatter themselves.
    """
    risk_pct = df["risk_pct"].to_numpy()
    cost_r = cost_pct / risk_pct

    if target_mode == "R":
        tb = df[f"t{target}R_bar"].to_numpy().astype(float)
        tgt_r = np.full(len(df), float(target))
    elif target_mode == "pct":
        tb = df[f"t{target}pct_bar"].to_numpy().astype(float)
        tgt_r = target / risk_pct
    elif target_mode == "wsup":
        avail = df["target_r_available"].to_numpy()
        tgt_r = np.clip(avail, 0.0, 20.0)
        # nearest R on the recorded grid, rounded down so we never claim a
        # touch that was not measured
        grid = np.array([0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0])
        # round the available distance DOWN to a measured grid point, so we
        # never claim a touch that was not recorded
        idx = np.searchsorted(grid, tgt_r, side="right") - 1
        ok = np.isfinite(avail) & (idx >= 0)
        idx = np.clip(idx, 0, len(grid) - 1)
        cols = np.column_stack([df[f"t{g}R_bar"].to_numpy() for g in grid]).astype(float)
        tb = np.where(ok, cols[np.arange(len(df)), idx], -1.0)
        tgt_r = np.where(ok, grid[idx], np.nan)
    else:
        raise ValueError(target_mode)

    sb = df["stop_bar"].to_numpy().astype(float)
    stop_fill = df["stop_fill"].to_numpy()
    entry = df["entry"].to_numpy()
    prox = df["entry_plan"].to_numpy()
    stop = df["stop"].to_numpy()
    risk = prox - stop

    tb = np.where((tb >= 0) & (tb <= max_hold), tb, np.inf)
    sb = np.where((sb >= 0) & (sb <= max_hold), sb, np.inf)

    # realised stop R uses the actual fill, so a gap through the level costs
    # more than the planned -1R
    stop_r = np.where(np.isfinite(stop_fill), (stop_fill - entry) / risk, -1.0)
    # entering below the line is a better fill than planned; keep that too
    slip = (prox - entry) / risk

    hit_stop = sb <= tb if stop_first else sb < tb
    out = np.where(
        np.isinf(sb) & np.isinf(tb),
        _timeout_r(df, max_hold, risk_pct),
        np.where(hit_stop & np.isfinite(sb), stop_r, tgt_r + slip),
    )
    return out - cost_r


def _timeout_r(df, max_hold, risk_pct):
    col = {5: "ret5", 10: "ret10", 20: "ret20", 40: "ret40",
           60: "ret60", 120: "ret120"}
    k = min([h for h in col if h >= max_hold], default=120)
    return df[col[k]].to_numpy() / risk_pct


def summarise(r, label="", extra=None):
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n == 0:
        return {"label": label, "n": 0}
    wins = r[r > 0]; losses = r[r <= 0]
    gross_w = wins.sum(); gross_l = -losses.sum()
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(eq)).min() if n else 0.0
    d = {
        "label": label, "n": n,
        "win%": 100.0 * len(wins) / n,
        "avgR": r.mean(),
        "medR": float(np.median(r)),
        "totR": r.sum(),
        "PF": gross_w / gross_l if gross_l > 0 else np.inf,
        "maxDD_R": dd,
        "t": r.mean() / (r.std(ddof=1) / np.sqrt(n)) if n > 1 and r.std(ddof=1) > 0 else np.nan,
    }
    if extra:
        d.update(extra)
    return d


def table(rows, sort=None):
    df = pd.DataFrame(rows)
    if sort:
        df = df.sort_values(sort, ascending=False)
    for c in ("win%", "avgR", "medR", "totR", "PF", "maxDD_R", "t"):
        if c in df:
            df[c] = df[c].astype(float).round(3)
    return df


def by_period(df, r, freq="YE"):
    s = pd.Series(r, index=pd.DatetimeIndex(df["date"]))
    s = s[np.isfinite(s)]
    g = s.groupby(pd.Grouper(freq=freq))
    return pd.DataFrame({"n": g.size(), "totR": g.sum(), "avgR": g.mean(),
                         "win%": g.apply(lambda x: 100.0 * (x > 0).mean())}).round(3)


def by_symbol(df, r):
    s = pd.Series(r, index=df["symbol"].to_numpy())
    s = s[np.isfinite(s)]
    g = s.groupby(level=0)
    out = pd.DataFrame({"n": g.size(), "totR": g.sum(), "avgR": g.mean()})
    return out.sort_values("totR", ascending=False)


def concentration(df, r):
    bs = by_symbol(df, r)
    tot = bs["totR"].sum()
    pos = bs[bs["totR"] > 0]["totR"].sum()
    top5 = bs["totR"].head(5).sum()
    return {
        "symbols": len(bs),
        "pct_symbols_profitable": 100.0 * (bs["totR"] > 0).mean(),
        "median_symbol_R": float(bs["totR"].median()),
        "median_symbol_avgR": float(bs["avgR"].median()),
        "top5_share_of_gross_profit%": 100.0 * top5 / pos if pos > 0 else np.nan,
        "total_R": tot,
    }
