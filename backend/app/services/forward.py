"""Forward-test book: open positions with live P/L, closed results, scorecard."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError
from app.engine import core
from app.services.serialization import clean_mapping, clean_value, frame_to_records


def positions(use_live: bool = True) -> dict[str, Any]:
    """Every forward test with a real current price and what it is doing.

    ``use_live`` decides whether a live tick may be used at all. Provenance
    (``Price Source`` / ``Price As Of``) comes back with the rows so a stale
    price can never be mistaken for a live one in the UI.
    """
    df, meta = core.forward_positions_view(use_live=use_live)
    return {
        "rows": frame_to_records(df),
        "meta": clean_mapping(meta),
    }


def summary() -> dict[str, Any]:
    """Per-strategy scorecard built from forward-test records only."""
    df = core.forward_summary_table()
    return {"rows": frame_to_records(df)}


def book_totals() -> dict[str, Any]:
    con = core._db()
    try:
        row = con.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS open_count,
                      SUM(CASE WHEN status<>'ACTIVE' THEN 1 ELSE 0 END) AS closed_count,
                      SUM(CASE WHEN result_r > 0 THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN result_r <= 0 AND result_r IS NOT NULL THEN 1 ELSE 0 END) AS losses,
                      AVG(result_r) AS avg_r,
                      SUM(result_r) AS total_r
                 FROM forward_tests"""
        ).fetchone()
    finally:
        con.close()
    total, open_count, closed_count, wins, losses, avg_r, total_r = row or (0,) * 7
    decided = int(wins or 0) + int(losses or 0)
    return {
        "total": int(total or 0),
        "open": int(open_count or 0),
        "closed": int(closed_count or 0),
        "wins": int(wins or 0),
        "losses": int(losses or 0),
        "win_rate": round(100.0 * int(wins or 0) / decided, 1) if decided else None,
        "avg_r": clean_value(avg_r),
        "total_r": clean_value(total_r),
    }


def results(limit: int = 500) -> dict[str, Any]:
    """Closed forward tests with their measured outcome."""
    con = core._db()
    try:
        df = pd.read_sql_query(
            """SELECT symbol, strategy, signal_date, entry, exit_price, result_r,
                      return_pct, outcome, holding_bars, mfe_pct, mae_pct,
                      regime, score, closed_at
                 FROM forward_results ORDER BY closed_at DESC LIMIT ?""",
            con, params=(int(limit),),
        )
    finally:
        con.close()
    return {"rows": frame_to_records(df)}


def refresh() -> dict[str, Any]:
    """Resolve open positions against completed daily candles.

    Resolution deliberately never uses a live tick: a price touching a level
    intraday raises an alert in the positions table, it does not close a record.
    """
    checked, closed = core.refresh_forward_positions()
    core._metric_set("forward_last_resolved_at",
                     pd.Timestamp.now().isoformat(timespec="seconds"))
    return {"checked": int(checked), "closed": int(closed)}


def add_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Record scanner rows as forward tests.

    The engine refuses a duplicate for the same symbol/strategy/date, so this is
    safe to call twice with an overlapping selection.
    """
    if not rows:
        raise ApiError("Select at least one candidate to forward test.")
    frame = pd.DataFrame(rows)
    required = {"Ticker", "Strategy", "Score", "Entry", "SL 7%", "Target 3R"}
    missing = required - set(frame.columns)
    if missing:
        raise ApiError(f"Candidate rows are missing required fields: {', '.join(sorted(missing))}")
    added = core.add_forward_candidates(frame)
    return {"added": int(added), "submitted": len(frame)}


def signals(limit: int = 500, signal_date: str | None = None) -> dict[str, Any]:
    """The persisted scanner signal log — every qualified setup, gated or not."""
    con = core._db()
    try:
        if signal_date:
            df = pd.read_sql_query(
                "SELECT * FROM scanner_signals WHERE signal_date=? "
                "ORDER BY score DESC LIMIT ?",
                con, params=(signal_date, int(limit)),
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM scanner_signals ORDER BY signal_date DESC, score DESC LIMIT ?",
                con, params=(int(limit),),
            )
    finally:
        con.close()
    return {"rows": frame_to_records(df)}


def live_table() -> dict[str, Any]:
    """Forward tests joined to the persistent WebSocket feed's latest ticks."""
    df = core.live_forward_test_table()
    return {"rows": frame_to_records(df)}
