"""One scorecard for every strategy being front-tested (paper traded live).

Each row compares what the strategy has done since it went live with what its
backtest said to expect on the 2025-26 hold-out, so a strategy drifting away
from its research shows up in one place:

- NSE S1-S6: the forward_tests book (the mirrored database).
- Crypto/gold 4h trend, long and short: the Oracle paper book
  (REPORT_DIR/trend-state.json, written by app/tasks/trend_paper.py).
- Forex liquidity B: the GitHub paper workflow's state.json on the public
  fx-paper branch (scripts/fx_paper.py).
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from app.engine import core

FX_STATE_URL = "https://raw.githubusercontent.com/kkute2118-hash/Backtesting-/fx-paper/state.json"
FX_TTL_SECONDS = 300
FX_RS_PER_R = 100.0          # Rs 10,000 account, 1% risk a trade
MIN_TRADES = 20              # below this a live average says little

# Hold-out (2025-26) average R per trade from the research notes.
EXPECTED = {
    "trend_long": (0.60, "research/fx_crypto/STEP17_SHORTS.md"),
    "trend_short": (0.17, "research/fx_crypto/STEP17_SHORTS.md"),
    "fx_b": (0.32, "research/fx_crypto/STEP3_FINDINGS.md"),
}

_fx_cache: tuple[float, dict] | None = None


def verdict(closed: int, avg_r: float | None, expected: float | None) -> str:
    if closed < MIN_TRADES:
        return f"Too early ({closed} of {MIN_TRADES} trades)"
    if avg_r is None:
        return "No result"
    if avg_r <= 0:
        return "Losing: review"
    if expected is not None and avg_r < expected / 2:
        return "Below backtest"
    return "On track"


def _row(**kw: Any) -> dict[str, Any]:
    rs = kw.pop("rs", [])
    closed = len(rs)
    wins = sum(1 for r in rs if r > 0)
    avg = round(sum(rs) / closed, 3) if closed else None
    exp = kw.get("expected_r")
    return {**kw, "closed": closed, "wins": wins, "losses": closed - wins,
            "win_pct": round(100 * wins / closed, 1) if closed else None,
            "avg_r": avg, "total_r": round(sum(rs), 2),
            "verdict": verdict(closed, avg, exp)}


def _trend_rows() -> tuple[list[dict], list[dict]]:
    from app.tasks import trend_paper

    path = trend_paper.REPORT_DIR / "trend-state.json"
    if not path.exists():
        return [], []
    book = json.loads(path.read_text())
    closed = [t for st in book.get("markets", {}).values() for t in st.get("closed", [])]
    open_long = sum(1 for st in book.get("markets", {}).values()
                    if st.get("status") in ("long", "exit_next"))
    open_short = sum(1 for st in book.get("markets", {}).values()
                     if st.get("status") in ("short", "cover_next"))
    rows, trades = [], []
    for side, n_open, key, name, markets in (
            ("long", open_long, "trend_long", "4h trend: buy breakouts", "BTC, ETH, SOL, gold"),
            ("short", open_short, "trend_short", "4h trend: short breakdowns", "BTC, ETH, SOL")):
        mine = [t for t in closed if t.get("side", "long") == side]
        rows.append(_row(id=key, book="Crypto & gold", strategy=name, markets=markets,
                         since=book.get("start"), open=n_open, rs=[t["r"] for t in mine],
                         pnl_rs=round(trend_paper._equity(mine) - trend_paper.START_EQUITY, 0),
                         expected_r=EXPECTED[key][0], source=EXPECTED[key][1]))
        trades += [{"book": "Crypto & gold", "strategy": name, "symbol": t.get("symbol"), "side": side,
                    "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"),
                    "entry": t.get("entry"), "exit": t.get("exit"), "r": t.get("r"),
                    "why": t.get("why")} for t in mine]
    return rows, trades


def _fx_state() -> dict:
    global _fx_cache
    if _fx_cache and time.time() - _fx_cache[0] < FX_TTL_SECONDS:
        return _fx_cache[1]
    try:
        resp = requests.get(FX_STATE_URL, timeout=10)
        resp.raise_for_status()
        _fx_cache = (time.time(), resp.json())
    except Exception:
        if not _fx_cache:
            raise
    return _fx_cache[1]


def _fx_rows() -> tuple[list[dict], list[dict]]:
    st = _fx_state()
    all_trades = list((st.get("trades") or {}).values())
    closed = [t for t in all_trades if t.get("status") == "closed"]
    n_open = sum(1 for t in all_trades if t.get("status") == "open")
    first = min((t.get("entry_time") or t.get("event_time") or "" for t in all_trades), default=None)
    rs = [float(t.get("r") or 0) for t in closed]
    row = _row(id="fx_b", book="Forex & gold", strategy="Liquidity run, first retest (B)",
               markets="EUR/USD, GBP/USD, AUD/USD, USD/JPY, gold", since=first or None,
               open=n_open, pending=len(st.get("pending") or []), rs=rs,
               pnl_rs=round(sum(rs) * FX_RS_PER_R, 0), updated=st.get("updated"),
               expected_r=EXPECTED["fx_b"][0], source=EXPECTED["fx_b"][1])
    trades = [{"book": "Forex & gold", "strategy": row["strategy"], "symbol": t.get("symbol"),
               "side": "long" if t.get("direction", 1) > 0 else "short",
               "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"),
               "entry": t.get("entry"), "exit": None, "r": t.get("r"), "why": t.get("outcome")}
              for t in closed]
    return [row], trades


def _nse_rows() -> list[dict]:
    con = core._db()
    try:
        cur = con.execute(
            """SELECT strategy, MIN(COALESCE(signal_date, created_at)),
                      SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END)
                 FROM forward_tests GROUP BY strategy""")
        meta = {s: (since, n_open) for s, since, n_open in cur.fetchall()}
        rows = []
        for strategy, (since, n_open) in sorted(meta.items()):
            rs = [r for (r,) in con.execute(
                "SELECT result_r FROM forward_tests WHERE strategy=? AND status<>'ACTIVE' "
                "AND result_r IS NOT NULL", (strategy,)).fetchall()]
            rows.append(_row(id=f"nse_{strategy}", book="NSE shares", strategy=strategy,
                             markets="NSE Top 2000", since=since, open=int(n_open or 0), rs=rs,
                             pnl_rs=None, expected_r=None, source=None))
        return rows
    finally:
        con.close()


def scorecard() -> dict[str, Any]:
    rows, trades, errors = [], [], {}
    for name, fn in (("trend", _trend_rows), ("forex", _fx_rows)):
        try:
            r, t = fn()
            rows += r
            trades += t
        except Exception as exc:
            errors[name] = str(exc)[:200]
    try:
        rows += _nse_rows()
    except Exception as exc:
        errors["nse"] = str(exc)[:200]
    trades.sort(key=lambda t: str(t.get("exit_time") or ""), reverse=True)
    return {"rows": rows, "recent_trades": trades[:50], "errors": errors,
            "min_trades": MIN_TRADES}
