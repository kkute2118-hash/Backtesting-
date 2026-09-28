#!/usr/bin/env python3
"""Can S1-S3 be made better? Rules learned on 2022-24, judged on 2025-26.

    python scripts/s123_improve.py OUT.json

For each retired strategy, from its raw engine signals (every signal, before
any entry filter) with the ~40 readings recorded on the signal day:

  1. baseline: all raw signals, and the live ATR entry filter they ran under;
  2. learned: the single best extra rule (one reading above or below a
     2022-24 quantile), then the best second rule given the first, each
     chosen ONLY on 2022-24 by average R and required to keep >= 30% of the
     trades and >= 60 of them;
  3. S6's traits: market breadth >= 0.50, >= 60% above the 52-week low,
     within 15% of the 52-week high;
  4. every variant scored on 2025-26, which the search never saw.

The evidence rule (CLAUDE.md) accepts a rule only if it helps on both.
Read-only with respect to the database backup.
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
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="s123-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402

START, SPLIT = "2022-01-01", pd.Timestamp("2025-01-01")
OUTCOME = {"created_at", "ticker", "strategy", "signal_date", "entry_date", "exit_date", "outcome",
           "entry", "stop", "target", "exit_price", "return_pct", "r_multiple", "holding_bars",
           "mfe_pct", "mae_pct", "source", "run_id", "fingerprint", "signal_key"}
MIN_SHARE, MIN_N = 0.30, 60


def stats(t: pd.DataFrame) -> dict:
    if not len(t):
        return {"trades": 0}
    r = t.r_multiple.clip(-3, 10)            # a gap through the stop or a freak target cannot swamp the mean
    return {"trades": int(len(t)), "win_pct": round(float((t.return_pct > 0).mean() * 100), 1),
            "avg_r": round(float(r.mean()), 3), "avg_pct": round(float(t.return_pct.mean()), 2)}


def split(t):
    return t[t.signal_date < SPLIT], t[t.signal_date >= SPLIT]


def best_rule(train: pd.DataFrame, cols: list[str], base_n: int):
    """(column, op, threshold, train avg R) of the best single rule on train."""
    best = None
    for c in cols:
        v = pd.to_numeric(train[c], errors="coerce")
        if v.notna().mean() < 0.9 or v.nunique() < 5:
            continue
        for q in (0.2, 0.4, 0.6, 0.8):
            thr = float(v.quantile(q))
            for op in (">=", "<="):
                keep = (v >= thr) if op == ">=" else (v <= thr)
                k = train[keep.fillna(False)]
                if len(k) < max(MIN_N, MIN_SHARE * base_n):
                    continue
                score = float(k.r_multiple.clip(-3, 10).mean())
                if best is None or score > best[3]:
                    best = (c, op, thr, score)
    return best


def apply(t, rule):
    c, op, thr, _ = rule
    v = pd.to_numeric(t[c], errors="coerce")
    return t[((v >= thr) if op == ">=" else (v <= thr)).fillna(False)]


def main():
    out_path = Path(sys.argv[1])
    core.restore_db_from_github(force=True)
    core._persist_raw_fingerprints = lambda *a, **k: None
    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 260")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, lookback_days=2600)
    data = {k: v for k, v in data.items() if v is not None and len(v) >= 260}
    end = str(core.last_expected_nse_session())
    breadth = core.market_breakout_breadth(force=True)

    # S6's traits per stock and day, to join onto the signals
    traits = {}
    for k, df in data.items():
        f = core.strategy6_features(core.attach_market_breadth(df, breadth))
        traits[str(k).replace(".NS", "")] = f[["s6_breadth", "s6_above_52w_low_pct", "s6_below_52w_high_pct"]]

    out = {"window": f"{START} to {end}", "train": "2022-24", "test": "2025-26", "strategies": {}}
    for s in (1, 2, 3):
        raw = core.run_raw_signal_backtest(data, [s], START, end)
        raw = raw[raw.outcome.astype(str).str.upper() != "OPEN"].copy()
        raw["signal_date"] = pd.to_datetime(raw.signal_date)
        raw["sym"] = raw.ticker.astype(str).str.replace(".NS", "", regex=False)
        rows = []
        for sym, g in raw.groupby("sym"):
            tr = traits.get(sym)
            if tr is None:
                continue
            j = tr.reindex(g.signal_date.values)
            rows.append(g.assign(breadth10=j.s6_breadth.values, above_low=j.s6_above_52w_low_pct.values,
                                 below_high=j.s6_below_52w_high_pct.values))
        t = pd.concat(rows, ignore_index=True)
        # the live entry filter these ran under (ATR / turnover on the signal day)
        live = [core.historical_entry_verdict(s, data.get(r.ticker) if r.ticker in data else data.get(r.sym + ".NS"),
                                              r.signal_date)[0] for r in t.itertuples()]
        t["live_filter"] = live
        tr_, te_ = split(t)
        cols = [c for c in t.columns if c not in OUTCOME and c not in ("sym", "live_filter")
                and pd.api.types.is_numeric_dtype(t[c])]

        res = {"raw": {"2022-24": stats(tr_), "2025-26": stats(te_)},
               "live filter": {"2022-24": stats(tr_[tr_.live_filter]), "2025-26": stats(te_[te_.live_filter])}}
        r1 = best_rule(tr_, cols, len(tr_))
        if r1:
            a_tr, a_te = apply(tr_, r1), apply(te_, r1)
            res[f"learned: {r1[0]} {r1[1]} {r1[2]:.3g}"] = {"2022-24": stats(a_tr), "2025-26": stats(a_te)}
            r2 = best_rule(a_tr, [c for c in cols if c != r1[0]], len(tr_))
            if r2:
                b_tr, b_te = apply(a_tr, r2), apply(a_te, r2)
                res[f"learned: + {r2[0]} {r2[1]} {r2[2]:.3g}"] = {"2022-24": stats(b_tr), "2025-26": stats(b_te)}
        s6 = t[(t.breadth10 >= core.S6_MIN_BREADTH) & (t.above_low >= core.S6_MIN_ABOVE_52W_LOW_PCT)
               & (t.below_high <= core.S6_MAX_BELOW_52W_HIGH_PCT)]
        s6_tr, s6_te = split(s6)
        res["S6 traits (breadth, 52w low/high)"] = {"2022-24": stats(s6_tr), "2025-26": stats(s6_te)}
        s6l_tr, s6l_te = split(s6[s6.live_filter])
        res["S6 traits + live filter"] = {"2022-24": stats(s6l_tr), "2025-26": stats(s6l_te)}
        out["strategies"][f"S{s}"] = res
        print(f"S{s}", json.dumps(res), flush=True)

    out_path.write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
