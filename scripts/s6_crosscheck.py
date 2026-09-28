#!/usr/bin/env python3
"""Cross-check S6 against the data it came from, and against over-fitting.

    python scripts/s6_crosscheck.py OUT.json

1. Top gainers: the biggest 1-year gainers in the store. Did S6 signal them,
   how far into the move, and how much of it did its own exit keep?
2. Robustness: each S6 setting moved down and up one notch, the others held.
   A rule whose result collapses one notch away is fitted to noise.
3. Every variant scored on 2022-24 and 2025-26 separately (the evidence rule).

Uses core.run_s6_backtest (the live rules and the data guard), full history,
stored universe. Read-only with respect to the database backup.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="s6-check-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

from app.engine import core  # noqa: E402

START = "2022-01-01"
GRID = {                                   # setting: (down, up); the live value sits between
    "S6_MIN_BREADTH": (0.40, 0.60),
    "S6_MIN_ATR_PCT": (2.3, 3.3),
    "S6_MIN_ABOVE_52W_LOW_PCT": (50.0, 70.0),
    "S6_MAX_BELOW_52W_HIGH_PCT": (10.0, 20.0),
    "S6_REARM_DAYS": (21, 35),
}


def summary(t: pd.DataFrame) -> dict:
    c = t[t["Exit Reason"].astype(str).str.upper() != "OPEN"]
    if not len(c):
        return {"trades": 0}
    r = c["Return %"].astype(float)
    return {"trades": int(len(c)), "win_pct": round(float((r > 0).mean() * 100), 1),
            "avg_pct": round(float(r.mean()), 2), "median_pct": round(float(r.median()), 2)}


def periods(t: pd.DataFrame) -> dict:
    d = pd.to_datetime(t["Signal Date"])
    return {"all": summary(t), "2022-24": summary(t[d < "2025-01-01"]),
            "2025-26": summary(t[d >= "2025-01-01"])}


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
    out = {"window": f"{START} to {end}", "stocks": len(data)}

    base = core.run_s6_backtest(data, START, end, breadth=breadth)
    out["base"] = periods(base)
    print("base", out["base"], flush=True)

    # 1. Top gainers over the last year.
    rows = []
    for sym, df in data.items():
        c = df.close.dropna()
        if len(c) < 253:
            continue
        rows.append((sym.replace(".NS", ""), float(c.iloc[-1] / c.iloc[-253] - 1) * 100,
                     c.index[-253], float(c.iloc[-253])))
    top = sorted(rows, key=lambda r: -r[1])[:30]
    b = base.assign(sym=base["Ticker"].astype(str).str.replace(".NS", "", regex=False),
                    sd=pd.to_datetime(base["Signal Date"]))
    caught = []
    for sym, gain, since, start_px in top:
        hits = b[(b.sym == sym) & (b.sd >= since)].sort_values("sd")
        if len(hits):
            h = hits.iloc[0]
            into = (float(h["Entry"]) / start_px - 1) * 100 / gain * 100 if gain > 0 else None
            caught.append({"symbol": sym, "gain_1y_pct": round(gain, 1), "signal": str(h["sd"].date()),
                           "entry_after_pct_of_move": round(into, 0) if into is not None else None,
                           "trade_return_pct": round(float(h["Return %"]), 1),
                           "exit": str(h["Exit Reason"])})
        else:
            caught.append({"symbol": sym, "gain_1y_pct": round(gain, 1), "signal": None})
    hit = [c for c in caught if c["signal"]]
    all_syms = {r[0] for r in rows}
    signalled = set(b[b.sd >= top[0][2]].sym) if top else set()
    out["top_gainers"] = {
        "caught": f"{len(hit)} of {len(top)}",
        "base_rate": f"{len(signalled & all_syms)} of {len(all_syms)} stocks signalled in the same year",
        "avg_trade_return_pct_on_caught": round(sum(c["trade_return_pct"] for c in hit) / len(hit), 1) if hit else None,
        "rows": caught,
    }
    print("top gainers", out["top_gainers"]["caught"], out["top_gainers"]["base_rate"], flush=True)

    # 2-3. One notch either side of each setting.
    out["robustness"] = {}
    for name, (down, up) in GRID.items():
        live = getattr(core, name)
        res = {}
        for label, val in (("down", down), ("up", up)):
            setattr(core, name, val)
            try:
                with core._S6_BREADTH_LOCK:
                    core._S6_BREADTH.update(at=0.0, series=None)
                t = core.run_s6_backtest(data, START, end, breadth=breadth)
                res[f"{label} {val}"] = periods(t)
            finally:
                setattr(core, name, live)
            print(name, label, val, res[f"{label} {val}"], flush=True)
        res[f"live {live}"] = out["base"]
        out["robustness"][name] = res

    out_path.write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
