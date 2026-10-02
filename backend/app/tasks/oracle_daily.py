"""Daily work for the Oracle server: an NSE Top 2000 scan three times a
trading day and a nightly two-year backtest of every strategy.

    python -m app.tasks.oracle_daily scan       # live prices while the market is open
    python -m app.tasks.oracle_daily research   # nightly, ~2 years, S1-S6, all stored stocks

Both read the server's own copy of the database and write JSON reports to
REPORT_DIR (served behind the site login at /reports/). Neither writes the
database backup or anything on GitHub: the server stays a read-only mirror.

Why on this server: it is the one machine with spare cores, and running real
work every day is also what keeps an Always Free instance from being reclaimed
as idle (deploy/oracle/README.md). deploy/oracle/daily-work.sh runs these from
systemd timers at the lowest CPU and disk priority, so the web app keeps
priority.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

from app.engine import core
from app.engine import portfolio_bt as pb

REPORT_DIR = Path(os.environ.get("REPORT_DIR", "/data/reports"))
KEEP_DAYS = 30
ALL = ("S1", "S2", "S3", "S4_SEPA", "S5_POCKETPIVOT", "S6_BREAKOUT")
RESEARCH_YEARS = 2


def _stored_shares(min_bars=260):
    con = core._db()
    try:
        return [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' GROUP BY symbol "
            "HAVING COUNT(*) >= ?", (int(min_bars),))]
    finally:
        con.close()


def _plain(v):
    if isinstance(v, (pd.Timestamp,)):
        return str(v.date())
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        return v.item()
    return v


def _write(kind, payload):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = core.market_now().strftime("%Y-%m-%d-%H%M")
    path = REPORT_DIR / f"{kind}-{stamp}.json"
    text = json.dumps(payload, indent=1, default=str)
    path.write_text(text)
    (REPORT_DIR / f"{kind}-latest.json").write_text(text)
    cutoff = time.time() - KEEP_DAYS * 86400
    for old in REPORT_DIR.glob(f"{kind}-20*.json"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return path


def scan():
    """S1-S6 over the stored NSE Top 2000, with live Dhan prices when the
    market is open (the same overlay the dashboard uses)."""
    started = time.perf_counter()
    data = core.load_scan_dataset(_stored_shares())
    live = {"used": False, "symbols": 0}
    if core.nse_market_is_open() and core.dhan_configured():
        try:
            data, bars = core.attach_live_bars(data)
            live = {"used": bool(bars), "symbols": len(bars or {})}
        except Exception as exc:                      # stored closes still scan
            live["error"] = f"{type(exc).__name__}: {exc}"[:200]
    proxy, _ = core.market_regime_frame(data)
    regime, regime_score = core.regime_from_index(proxy)
    stats = {}
    result = core.scan_dataset(data, core.DEFAULT_STRATEGIES, regime, stats=stats)
    rows = [] if result is None or result.empty else [
        {k: _plain(v) for k, v in r.items()} for r in result.to_dict("records")]
    breadth = core.market_breakout_breadth().dropna()
    payload = {
        "kind": "scan", "at": core.market_now().isoformat(timespec="minutes"),
        "stocks_scanned": len(data), "live": live, "regime": regime,
        "regime_score": _plain(regime_score),
        "breadth": round(float(breadth.iloc[-1]), 3) if len(breadth) else None,
        "per_strategy": {core.strategy_label_for(s): {
            "raw": int(stats.get("signals", {}).get(s, 0)),
            "qualified": int(stats.get("qualified", {}).get(s, 0))} for s in core.DEFAULT_STRATEGIES},
        "signals": rows,
        "seconds": round(time.perf_counter() - started, 1),
    }
    return _write("scan", payload)


def research():
    """Every strategy over the last RESEARCH_YEARS on every stored stock: trade
    counts, win rate, average return, by market-breadth band, and a Rs 1 lakh
    account per strategy (10 slots, 1% risk, Indian costs)."""
    started = time.perf_counter()
    persist = core._persist_raw_fingerprints
    core._persist_raw_fingerprints = lambda *a, **k: None     # report only, no DB growth
    try:
        return _research(started)
    finally:
        core._persist_raw_fingerprints = persist


def _research(started):
    data = core.load_scan_dataset(_stored_shares(), lookback_days=365 * RESEARCH_YEARS + 500)
    end = core.last_expected_nse_session()
    start = end - timedelta(days=365 * RESEARCH_YEARS)
    trades = pb.collect_trades(data, str(start), str(end), strategies=ALL)
    closes = pb.close_matrix(data)
    breadth = core.market_breakout_breadth().dropna()

    out = {"kind": "research", "at": core.market_now().isoformat(timespec="minutes"),
           "window": f"{start} to {end}", "stocks": len(data), "strategies": {}}
    if not trades.empty:
        t = trades.copy()
        t["ret_pct"] = (t["exit"] / t["entry"] - 1) * 100
        sig = pd.to_datetime(t["signal_date"])
        t["breadth"] = breadth.reindex(sig, method="ffill").to_numpy()
        t["band"] = pd.cut(t["breadth"], [-1, 0.25, 0.5, 9], labels=["<0.25", "0.25-0.50", ">=0.50"])
        for s in ALL:
            ts = t[t.strategy == s]
            if ts.empty:
                out["strategies"][s] = {"trades": 0}
                continue
            acct = pb.run_portfolio(trades[trades.strategy == s], closes, capital=100_000,
                                    max_positions=10, risk_pct=1.0, costs=pb.IndianDeliveryCosts(),
                                    start=str(start), end=str(end)).stats
            out["strategies"][s] = {
                "trades": int(len(ts)),
                "win_pct": round(float((ts.ret_pct > 0).mean() * 100), 1),
                "avg_pct": round(float(ts.ret_pct.mean()), 2),
                "by_breadth": {str(b): {"trades": int(len(g)), "avg_pct": round(float(g.ret_pct.mean()), 2)}
                               for b, g in ts.groupby("band", observed=True)},
                "account_1L": {k: _plain(acct.get(k)) for k in
                               ("final", "cagr_pct", "max_drawdown_pct", "trades", "win_pct")},
            }
    out["seconds"] = round(time.perf_counter() - started, 1)
    return _write("research", out)


if __name__ == "__main__":
    job = sys.argv[1] if len(sys.argv) > 1 else ""
    if job not in ("scan", "research"):
        sys.exit("usage: python -m app.tasks.oracle_daily scan|research")
    print(f"{job}: wrote {globals()[job]()}", flush=True)
