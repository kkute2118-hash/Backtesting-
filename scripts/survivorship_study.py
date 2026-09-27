#!/usr/bin/env python3
"""How much does "today's Nifty 500" flatter the S4/S5/S6 backtests?

    python scripts/survivorship_study.py OUT_DIR [--download] [--years 5] [--top-n 500]

Every earlier study replayed the strategies over the stocks in TODAY's index.
That list knows the future: companies that grew into the index are in it,
companies that shrank out are not. This study replays the same three
strategies, with the scanner's own entry filters, over a point-in-time
universe instead: on each day, the `top_n` stocks by trailing traded value
among EVERY stock with data (engine: point_in_time_universe()).

With --download it first fetches history for the whole NSE cash market
(every ordinary NSE share in Dhan's instrument list) into a throwaway database, so stocks
that have since left the index are included. Without it, it runs on the
stored universe only, which bounds the bias but cannot remove it.

It never writes to the database backup. Results go to OUT_DIR as JSON and a
Markdown summary. Run it through .github/workflows/survivorship-study.yml.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import warnings
from datetime import timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("GTF_DATA_DIR", tempfile.mkdtemp(prefix="survivorship-"))
os.environ.setdefault("DB_BACKUP_REPO", "kkute2118-hash/Backtesting-")
os.environ.setdefault("DB_BACKUP_BRANCH", "db-backup")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.engine import core  # noqa: E402


def log(msg):
    print(f"[survivorship] {msg}", file=sys.stderr, flush=True)


def pit_breadth(data, eligible):
    """S6 breadth measured over the point-in-time universe only.

    S6's 0.50 threshold was fitted on a ~500-stock universe. Measured over
    2,000 stocks the same number would mean something else, so breadth here is
    the share of the day's ELIGIBLE stocks making a fresh 50-day-high close,
    summed over S6_BREADTH_WINDOW sessions.
    """
    n = core.S6_BREAKOUT_LOOKBACK
    flags = {}
    for sym, df in data.items():
        key = str(sym).upper().replace(".NS", "")
        flags[key] = df.close > df.high.rolling(n, min_periods=n).max().shift(1)
    f = pd.DataFrame(flags).reindex(index=eligible.index, columns=eligible.columns)
    e = eligible.reindex(index=f.index, columns=f.columns).fillna(False).astype(bool)
    share = (f.where(e).astype(float)).sum(axis=1) / e.sum(axis=1).replace(0, np.nan)
    return share.rolling(core.S6_BREADTH_WINDOW).sum().rename(core.S6_BREADTH_COLUMN)


def eligible_on(eligible, sym, d):
    try:
        return bool(eligible.at[pd.Timestamp(d), str(sym).upper().replace(".NS", "")])
    except KeyError:
        return False


def summarise(trades, today_list, label):
    if trades.empty:
        return {"strategy": label, "trades": 0}
    t = trades.copy()
    t["year"] = pd.to_datetime(t["date"]).dt.year
    t["in_today_list"] = t["sym"].isin(today_list)
    def block(x):
        return {"trades": int(len(x)), "win_pct": round(float((x.ret > 0).mean() * 100), 1) if len(x) else None,
                "avg_pct": round(float(x.ret.mean()), 2) if len(x) else None}
    out = {"strategy": label, **block(t),
           "by_year": {int(y): block(g) for y, g in t.groupby("year")},
           "in_today_list": block(t[t.in_today_list]),
           "not_in_today_list": block(t[~t.in_today_list])}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--top-n", type=int, default=500)
    ap.add_argument("--start", default=None, help="first signal date (default: years ago + 1 year warm-up)")
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    core.restore_db_from_github(force=True)
    end = core.last_expected_nse_session()
    data_start = end - timedelta(days=365 * args.years)
    start = pd.Timestamp(args.start) if args.start else pd.Timestamp(data_start + timedelta(days=400))
    if args.download:
        # purpose="download": every ordinary NSE share Dhan lists, not today's
        # 2000 most liquid, which would itself be a list chosen with hindsight.
        tickers = core.resolve_universe(core.FULL_NSE_UNIVERSE, purpose="download")
        log(f"downloading {len(tickers)} symbols {data_start} .. {end}")
        got = core.sync_missing_backtest_data(tickers, data_start, end)
        errs = list(core._DHAN_LAST_DATA_ERRORS)
        log(f"download: {len(got)} of {len(tickers)} symbols returned candles; "
            f"{len(errs)} errors (last 100 kept)")
        for e in errs[:15]:
            log(f"  {e}")

    con = core._db()
    try:
        syms = [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol HAVING COUNT(*) >= 60")]
    finally:
        con.close()
    data = core.load_scan_dataset(syms, min_bars=60, lookback_days=365 * args.years + 30)
    today_list = {s.replace(".NS", "") for s in core.resolve_universes(["Nifty 500"], allow_network=args.download)}
    log(f"{len(data)} stocks with data; today's Nifty 500 list has {len(today_list)}")

    eligible = core.point_in_time_universe(data, top_n=args.top_n)
    breadth = pit_breadth(data, eligible)
    lookup = core.sector_map(source="index")
    sranks = core.sector_rank_history()
    long_data = {k: v for k, v in data.items() if len(v) >= 260}

    results = []
    # S6: point-in-time universe and point-in-time breadth
    s6 = core.run_s6_backtest(long_data, start, end, breadth=breadth, eligible=eligible)
    s6t = pd.DataFrame({"sym": s6["Ticker"], "date": s6["Signal Date"], "ret": s6["Return %"]}) if len(s6) else pd.DataFrame()
    results.append(summarise(s6t, today_list, "S6_BREAKOUT"))

    # S5: its own backtest, then the live entry filter replayed on the signal day
    s5 = core.run_s5_pocket_pivot_backtest(long_data, start, end)["trades"]
    s5f = s5[[eligible_on(eligible, str(t).replace(".NS", ""), d) and
              core.historical_entry_verdict(5, long_data[t], d)[0] for t, d in zip(s5.Ticker, s5.Date)]]
    s5t = pd.DataFrame({"sym": s5f.Ticker.str.replace(".NS", ""), "date": s5f.Date, "ret": s5f["Return %"]})
    results.append(summarise(s5t, today_list, "S5_POCKETPIVOT"))

    # S4: raw signals, then eligibility + the live sector/turnover filter
    s4 = core.run_raw_signal_backtest(long_data, [4], start, end)
    if len(s4):
        mask = [eligible_on(eligible, str(t).replace(".NS", ""), d) and
                core.historical_entry_verdict(4, long_data[t], d, sector_ranks=sranks,
                                              sector_lookup=lookup, ticker=t)[0]
                for t, d in zip(s4.ticker, s4.signal_date)]
        s4f = s4[mask]
        s4t = pd.DataFrame({"sym": s4f.ticker.str.replace(".NS", ""), "date": s4f.signal_date, "ret": s4f.return_pct})
    else:
        s4t = pd.DataFrame()
    results.append(summarise(s4t, today_list, "S4_SEPA"))

    meta = {"download": args.download, "stocks": len(data), "top_n": args.top_n,
            "signals_from": str(start.date()), "to": str(end),
            "today_list_size": len(today_list),
            "stocks_not_in_today_list": len(set(k.replace('.NS', '') for k in data) - today_list)}
    (out / "survivorship.json").write_text(json.dumps({"meta": meta, "results": results}, indent=1, default=str))

    lines = [f"# Survivorship check ({'full NSE download' if args.download else 'stored universe only'})", "",
             f"{meta['stocks']} stocks with data, {meta['stocks_not_in_today_list']} of them not in today's Nifty 500. "
             f"Point-in-time universe: top {args.top_n} by trailing traded value each day. "
             f"Signals {meta['signals_from']} to {meta['to']}.", "",
             "| Strategy | Trades | Win % | Avg % | In today's list: n / avg % | Not in it: n / avg % |",
             "|---|---|---|---|---|---|"]
    for r in results:
        if not r.get("trades"):
            lines.append(f"| {r['strategy']} | 0 | | | | |"); continue
        a, b = r["in_today_list"], r["not_in_today_list"]
        lines.append(f"| {r['strategy']} | {r['trades']} | {r['win_pct']} | {r['avg_pct']} | "
                     f"{a['trades']} / {a['avg_pct']} | {b['trades']} / {b['avg_pct']} |")
    (out / "survivorship.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
