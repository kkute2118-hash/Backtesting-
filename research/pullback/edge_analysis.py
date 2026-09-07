"""Does the setup itself select stocks that go up?

The portfolio run mixes two questions — signal quality and exit quality.  This
module isolates the first.  For every signal whose trigger actually fired, it
measures forward return from the real fill price and nets off the equal-weighted
market over identical dates, then compares against the null of buying any stock
on any day (same market adjustment, same window).

The market adjustment matters twice over: the proxy index is rebalanced daily,
so single names carry a volatility drag against it.  That drag is present in
both the signal sample and the null, which is why the null is what the signal
has to beat, not zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20)


def _market_return(market: pd.DataFrame, d, h: int) -> float:
    if d not in market.index:
        return np.nan
    i = market.index.get_loc(d)
    j = min(i + h, len(market) - 1)
    return 100.0 * (market["level"].iloc[j] / market["level"].iloc[i] - 1.0)


def triggered_edge(feats, setups, market, start, end, horizons=HORIZONS) -> pd.DataFrame:
    """Forward excess returns from the actual fill, for signals that triggered."""
    all_dates = sorted({d for f in feats.values() for d in f.index})
    pos_of = {d: i for i, d in enumerate(all_dates)}
    lo_d, hi_d = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for row in setups.itertuples(index=False):
        if not (lo_d <= row.setup_date <= hi_d):
            continue
        f = feats[row.symbol]
        i = pos_of.get(row.setup_date)
        if i is None or i + 1 >= len(all_dates):
            continue
        ed = all_dates[i + 1]
        if ed not in f.index:
            continue
        j = f.index.get_loc(ed)
        bar = f.iloc[j]
        if bar["high"] < row.trigger:            # trigger never fired
            continue
        fill = max(bar["open"], row.trigger)
        rec = {"symbol": row.symbol, "entry_date": ed, "fill": fill,
               "confluence": row.confluence, "rs_rank": row.rs_rank,
               "adr20": row.adr20, "dv20": row.dv20}
        for h in horizons:
            k = j + h
            rec[f"fwd{h}"] = 100.0 * (f.iloc[k]["close"] / fill - 1.0) if k < len(f) else np.nan
            rec[f"exc{h}"] = rec[f"fwd{h}"] - _market_return(market, ed, h)
        rows.append(rec)
    return pd.DataFrame(rows)


def null_sample(feats, market, start, end, horizons=HORIZONS, stride: int = 3) -> pd.DataFrame:
    """Buy any stock on any day, same measurement, as the null hypothesis."""
    lo_d, hi_d = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for sym, f in feats.items():
        idx = f.index
        sel = np.where((idx >= lo_d) & (idx <= hi_d))[0][::stride]
        for j in sel:
            if j + 1 >= len(f):
                continue
            ed = idx[j + 1]
            fill = f.iloc[j + 1]["open"]
            rec = {"symbol": sym, "entry_date": ed}
            for h in horizons:
                k = j + 1 + h
                rec[f"fwd{h}"] = 100.0 * (f.iloc[k]["close"] / fill - 1.0) if k < len(f) else np.nan
                rec[f"exc{h}"] = rec[f"fwd{h}"] - _market_return(market, ed, h)
            rows.append(rec)
    return pd.DataFrame(rows)


def compare(sig: pd.DataFrame, null: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    """Welch two-sample comparison of signal excess return against the null."""
    rows = []
    for h in horizons:
        a = sig[f"exc{h}"].dropna()
        b = null[f"exc{h}"].dropna()
        if not len(a) or not len(b):
            continue
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        rows.append(
            {
                "horizon_bars": h,
                "n_signals": len(a),
                "signal_excess_mean_pct": a.mean(),
                "signal_excess_median_pct": a.median(),
                "signal_win_rate_pct": 100.0 * (a > 0).mean(),
                "null_excess_mean_pct": b.mean(),
                "null_win_rate_pct": 100.0 * (b > 0).mean(),
                "difference_pct": a.mean() - b.mean(),
                "welch_t": (a.mean() - b.mean()) / se if se > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)
