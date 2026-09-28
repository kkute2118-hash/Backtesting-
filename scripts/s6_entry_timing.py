#!/usr/bin/env python3
"""Is S6's entry too late? Earlier and pullback entries against the breakout.

    python scripts/s6_entry_timing.py OUT.json

Every variant keeps S6's stock rules (ATR, 52-week location), the market
breadth gate, the 28-day re-arm and S6's exit (3 x ATR stop, 20% trail from
the highest close), and enters at a close:

  breakout   close above the prior 50-day high (S6 as it is)
  early_3    close within 3% BELOW the prior 50-day high, before any breakout
  early_5    the same within 5%
  pullback   after an S6 breakout, the first close >= 3% below the breakout
             close within 10 sessions; no dip, no trade

Also splits the breakout trades by distance from the 52-week high at entry,
to test "buying at an all-time high is buying too late". Scored on 2022-24
and 2025-26 separately. Read-only with respect to the database backup.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="s6-timing-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402

START = pd.Timestamp("2022-01-01")


def fresh(mask: pd.Series) -> pd.Series:
    """True on days `mask` fires more than S6_REARM_DAYS after its last firing."""
    dates = pd.Series(pd.to_datetime(mask.index), index=mask.index)
    prev = dates.where(mask).ffill().shift(1)
    recent = ((dates - prev) <= pd.Timedelta(days=core.S6_REARM_DAYS)).fillna(False)
    return mask & ~recent


def trade(x, feats, i, name, sym, rows, extra=None):
    entry = float(x.close.iloc[i])
    atr = float(feats.s6_atr.iloc[i])
    if not np.isfinite(atr) or atr <= 0 or core.recent_price_gap(x.iloc[:i + 1]) is not None:
        return
    stop = entry - core.S6_INITIAL_STOP_ATR * atr
    status, px, j = core.s6_exit_walk(x.iloc[i:], entry, stop)
    if status == "ACTIVE":
        return                                    # still open: leave out of the scoring
    rows.append({"variant": name, "sym": sym, "date": x.index[i], "ret": (px / entry - 1) * 100,
                 "r": (px - entry) / (entry - stop), "bars": j, **(extra or {})})


def score(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"trades": 0}
    return {"trades": int(len(t)), "win_pct": round(float((t.ret > 0).mean() * 100), 1),
            "avg_pct": round(float(t.ret.mean()), 2), "median_pct": round(float(t.ret.median()), 2),
            "avg_r": round(float(t.r.mean()), 2), "avg_days": round(float(t.bars.mean()), 0)}


def main():
    out_path = Path(sys.argv[1])
    core.restore_db_from_github(force=True)
    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 260")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, lookback_days=2600)
    breadth = core.market_breakout_breadth(force=True)
    n = core.S6_BREAKOUT_LOOKBACK
    rows = []
    for ticker, df in data.items():
        if df is None or len(df) < 260:
            continue
        sym = str(ticker).replace(".NS", "")
        x = core.attach_market_breadth(df, breadth)
        f = core.strategy6_features(x)
        prior_hi = x.high.rolling(n, min_periods=n).max().shift(1)
        stock_ok = ((f.s6_breadth >= core.S6_MIN_BREADTH) & (f.s6_atr_pct >= core.S6_MIN_ATR_PCT)
                    & (f.s6_above_52w_low_pct >= core.S6_MIN_ABOVE_52W_LOW_PCT)
                    & (f.s6_below_52w_high_pct <= core.S6_MAX_BELOW_52W_HIGH_PCT)).fillna(False)
        in_window = pd.Series(x.index >= START, index=x.index)
        breakout = core.strategy6_signal(x) & in_window
        near3 = fresh(((x.close <= prior_hi) & (x.close >= prior_hi * 0.97)).fillna(False)) & stock_ok & in_window
        near5 = fresh(((x.close <= prior_hi) & (x.close >= prior_hi * 0.95)).fillna(False)) & stock_ok & in_window
        for i in np.flatnonzero(breakout.to_numpy()):
            trade(x, f, i, "breakout", sym, rows,
                  {"below_high_pct": float(f.s6_below_52w_high_pct.iloc[i])})
            # pullback: first close >= 3% under the breakout close within 10 sessions
            level = float(x.close.iloc[i]) * 0.97
            window = x.close.iloc[i + 1:i + 11]
            hit = np.flatnonzero((window <= level).to_numpy())
            if len(hit):
                trade(x, f, i + 1 + int(hit[0]), "pullback", sym, rows)
        for name, mask in (("early_3", near3), ("early_5", near5)):
            for i in np.flatnonzero(mask.to_numpy()):
                trade(x, f, i, name, sym, rows)

    t = pd.DataFrame(rows)
    out = {"variants": {}, "breakout_by_distance_from_52w_high": {}}
    for name, g in t.groupby("variant"):
        out["variants"][name] = {"all": score(g), "2022-24": score(g[g.date < "2025-01-01"]),
                                 "2025-26": score(g[g.date >= "2025-01-01"])}
    b = t[t.variant == "breakout"]
    for lo, hi, label in ((0, 1, "at the 52w high (0-1% below)"), (1, 5, "1-5% below"),
                          (5, 15.01, "5-15% below")):
        g = b[(b.below_high_pct >= lo) & (b.below_high_pct < hi)]
        out["breakout_by_distance_from_52w_high"][label] = {
            "all": score(g), "2022-24": score(g[g.date < "2025-01-01"]),
            "2025-26": score(g[g.date >= "2025-01-01"])}
    out_path.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
