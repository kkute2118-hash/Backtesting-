"""Market status, data freshness and the dashboard overview."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.db import app_store
from app.engine import core
from app.services import forward as forward_service
from app.services.serialization import clean_value, frame_to_records


def market_status() -> dict[str, Any]:
    """Where the NSE cash session is right now, in the engine's own terms."""
    now = datetime.now()
    is_open = core.nse_market_is_open(now)
    return {
        "exchange": "NSE",
        "segment": "Cash",
        "is_open": bool(is_open),
        "as_of": now.isoformat(timespec="seconds"),
        "session_date": clean_value(core.current_session_date(now)),
        "last_completed_session": clean_value(core.latest_completed_nse_session(now)),
        "open_time": f"{core.NSE_MARKET_OPEN_HOUR:02d}:{core.NSE_MARKET_OPEN_MINUTE:02d}",
        "close_time": f"{core.NSE_MARKET_CLOSE_HOUR:02d}:{core.NSE_MARKET_CLOSE_MINUTE:02d}",
        "timezone": "Asia/Kolkata",
    }


def freshness(universes: list[str] | None = None, tickers: list[str] | None = None) -> dict[str, Any]:
    """How far behind the local candle store is, and what that means for a scan.

    A scan against a stale store ranks yesterday's prices and produces late
    entries, so this is surfaced prominently rather than buried in diagnostics.
    """
    from app.services.universe import resolve

    symbols = list(tickers or [])
    if universes:
        symbols = resolve(universes)
    if not symbols:
        return {"universe_size": 0, "latest": None, "expected": None,
                "current": None, "days_behind": None, "severity": "unknown",
                "message": "Select a universe to check local data freshness."}

    status = core.data_freshness_status(symbols)
    latest, expected = status["latest"], status["expected"]

    if latest is None:
        severity = "error"
        message = ("No local candle data for this universe yet. Run a full sync from "
                   "Data Manager before scanning.")
    elif status["current"]:
        severity = "ok"
        message = f"Stored candles current as of {latest.strftime('%d %b %Y')} (last completed session)."
    else:
        n = status["days_behind"]
        severity = "error"
        message = (f"Stale data — the local cache ends {latest.strftime('%d %b %Y')} but "
                   f"{expected.strftime('%d %b %Y')} has already closed "
                   f"({n} session{'s' if n != 1 else ''} behind). Top up before scanning.")

    return {
        "universe_size": len(symbols),
        "latest": clean_value(latest),
        "expected": clean_value(expected),
        "current": bool(status["current"]),
        "days_behind": status["days_behind"],
        "severity": severity,
        "message": message,
    }


def _candle_store_stats() -> dict[str, Any]:
    con = core._db()
    try:
        row = con.execute(
            "SELECT COUNT(*) AS bars, COUNT(DISTINCT symbol) AS symbols, MAX(dt) AS latest "
            "FROM candles"
        ).fetchone()
    finally:
        con.close()
    bars, symbols, latest = (row or (0, 0, None))
    return {"bars": int(bars or 0), "symbols": int(symbols or 0),
            "latest_session": latest}


def _latest_scan() -> dict[str, Any] | None:
    from app.services import jobs

    runs = jobs.list_runs(kind="scan", limit=1)
    if not runs:
        return None
    run = runs[0]
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "status": run["status"],
        "row_count": run.get("row_count") or 0,
        "universes": (run.get("request") or {}).get("universes", []),
        "strategies": (run.get("request") or {}).get("strategies", []),
    }


def _breadth_from_signals(days: int = 30) -> dict[str, Any]:
    """Signal counts per strategy over the recent window.

    This is genuine breadth from the scanner's own record - how often each
    strategy is finding anything - not an invented advance/decline line. The
    engine never computes A/D, so the dashboard does not claim to show one.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    con = core._db()
    try:
        rows = con.execute(
            """SELECT strategy, COUNT(*) AS signals,
                      SUM(selected_for_forward) AS at_gate,
                      MAX(signal_date) AS last_signal
                 FROM scanner_signals WHERE signal_date >= ?
             GROUP BY strategy ORDER BY signals DESC""",
            (since,),
        ).fetchall()
        recent = con.execute(
            """SELECT signal_date, COUNT(*) AS signals
                 FROM scanner_signals WHERE signal_date >= ?
             GROUP BY signal_date ORDER BY signal_date""",
            (since,),
        ).fetchall()
    finally:
        con.close()
    return {
        "window_days": days,
        "by_strategy": [
            {"strategy": r[0], "signals": int(r[1] or 0),
             "at_gate": int(r[2] or 0), "last_signal": r[3]}
            for r in rows
        ],
        "daily": [{"date": r[0], "signals": int(r[1] or 0)} for r in recent],
    }


def _top_opportunities(limit: int = 8) -> list[dict[str, Any]]:
    """The highest-scoring signals the scanner has actually recorded."""
    con = core._db()
    try:
        df = pd.read_sql_query(
            """SELECT symbol, strategy, score, learned_rank, signal_date, regime,
                      safety_status, entry, stop, target, rsi, relvol,
                      selected_for_forward
                 FROM scanner_signals
                WHERE signal_date = (SELECT MAX(signal_date) FROM scanner_signals)
             ORDER BY score DESC LIMIT ?""",
            con, params=(int(limit),),
        )
    finally:
        con.close()
    return frame_to_records(df)


def overview() -> dict[str, Any]:
    """Everything the dashboard needs, in one round trip.

    The dashboard would otherwise fire eight requests on load; each one opens
    the same SQLite file, and several of them read the same tables.
    """
    status = market_status()
    store = _candle_store_stats()

    try:
        summary = forward_service.summary()
    except Exception:
        summary = {"rows": [], "totals": {}}

    try:
        book = forward_service.book_totals()
    except Exception:
        book = {}

    default_universe = app_store.get_preference("default_universes", ["Nifty 500"])
    fresh: dict[str, Any]
    try:
        fresh = freshness(universes=default_universe)
    except Exception as exc:
        fresh = {"severity": "unknown", "message": str(exc), "universe_size": 0,
                 "latest": None, "expected": None, "current": None, "days_behind": None}

    return {
        "market": status,
        "data_store": store,
        "freshness": fresh,
        "forward": {"summary": summary.get("rows", []), "totals": book},
        "breadth": _breadth_from_signals(),
        "top_opportunities": _top_opportunities(),
        "latest_scan": _latest_scan(),
        "providers": provider_status(),
    }


def provider_status() -> dict[str, Any]:
    """Whether each integration is configured — never the credential itself."""
    token_issued = None
    try:
        _tok, issued = core._read_cached_dhan_token()
        token_issued = issued
    except Exception:
        pass
    return {
        "dhan": {
            "configured": bool(core.dhan_configured()),
            "auto_renew": bool(core._dhan_pin_totp_configured()),
            "token_issued_at": token_issued,
        },
        "twelvedata": {"configured": bool(core.twelvedata_configured())},
        "anthropic": {"configured": bool(core._anthropic_configured())},
        "github_backup": {"configured": bool(core._github_configured())},
    }
