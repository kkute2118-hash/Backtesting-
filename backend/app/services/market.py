"""Market status, data freshness and the dashboard overview."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.core.errors import ApiError
from app.db import app_store
from app.engine import core
from app.services import forward as forward_service
from app.services.serialization import clean_value, frame_to_records


def market_status(now: datetime | None = None) -> dict[str, Any]:
    """Where the NSE cash session is right now, in the engine's own terms."""
    # IST wall-clock, not datetime.now(): the web host runs UTC, and the core
    # clock helpers read a naive datetime as IST, so a host-clock `now` put the
    # dashboard 5h30 behind the exchange — "closed" until 14:45 IST, and every
    # date on it was a session late until 21:00 IST.
    now = core.market_now(now)
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


def freshness(universes: list[str] | None = None, tickers: list[str] | None = None,
              allow_network: bool = True) -> dict[str, Any]:
    """How far behind the local candle store is, and what that means for a scan.

    A scan against a stale store ranks yesterday's prices and produces late
    entries, so this is surfaced prominently rather than buried in diagnostics.
    """
    from app.services.universe import resolve

    symbols = list(tickers or [])
    if universes:
        # allow_network=False on the dashboard path: a freshness READING is not
        # worth blocking the page on a 30-second index download.
        symbols = resolve(universes, allow_network=allow_network)
    if not symbols:
        return {"universe_size": 0, "latest": None, "expected": None,
                "published": None, "current": None, "days_behind": None,
                "awaiting_publication": False, "severity": "unknown",
                "message": "Select a universe to check local data freshness."}

    status = core.data_freshness_status(symbols)
    latest, expected = status["latest"], status["expected"]

    if latest is None:
        severity = "error"
        message = ("No local candle data for this universe yet. Run a full sync from "
                   "Data Manager before scanning.")
    elif status["awaiting_publication"]:
        # The exchange has traded since the newest stored candle, but Dhan
        # publishes daily bars the next morning, so there is genuinely nothing
        # to download yet. Flagging this red was the banner crying wolf every
        # single weekday evening.
        severity = "info"
        message = (f"Stored candles current as of {latest.strftime('%d %b %Y')}. "
                   f"{expected.strftime('%d %b %Y')} has closed but Dhan publishes daily "
                   f"candles the next morning, so it is not downloadable yet.")
    elif status["current"]:
        severity = "ok"
        note = status.get("expected_note")
        if note and expected > latest:
            message = (f"Stored candles current as of {latest.strftime('%d %b %Y')} — "
                       f"{expected.strftime('%d %b %Y')} was not a trading day ({note}).")
        else:
            message = f"Stored candles current as of {latest.strftime('%d %b %Y')} (last completed session)."
    else:
        n = status["days_behind"]
        published = status["published"]
        severity = "error"
        message = (f"Stale data — the local cache ends {latest.strftime('%d %b %Y')} but "
                   f"{published.strftime('%d %b %Y')} has closed and been published "
                   f"({n} session{'s' if n != 1 else ''} behind). Top up before scanning.")

    return {
        "universe_size": len(symbols),
        "latest": clean_value(latest),
        "expected": clean_value(expected),
        "published": clean_value(status["published"]),
        "current": bool(status["current"]),
        "days_behind": status["days_behind"],
        "awaiting_publication": bool(status["awaiting_publication"]),
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
    since = (core.market_today() - timedelta(days=days)).isoformat()
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
        fresh = freshness(universes=default_universe, allow_network=False)
    except Exception as exc:
        fresh = {"severity": "unknown", "message": str(exc), "universe_size": 0,
                 "latest": None, "expected": None, "published": None,
                 "current": None, "days_behind": None, "awaiting_publication": False}

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


def sector_strength(lookbacks: tuple[int, ...] = (21, 63, 126)) -> dict[str, Any]:
    """Which sectors are leading, and how that was measured.

    Degrades deliberately rather than failing. Sector MEMBERSHIP comes from the
    NSE constituent lists and needs one fetch; index PRICES need Dhan. With
    membership alone the strength of each sector is computed from an
    equal-weighted composite of its members in the local candle store, which is
    usable on day one. The `source` column on every row says which it was, so a
    composite is never mistaken for the real index.
    """
    members = core.sector_map()
    if not members:
        return {"ready": False,
                "reason": "No sector membership stored yet. Sync it first — it needs one "
                          "fetch of the NSE constituent lists and no Dhan credentials.",
                "sectors": [], "benchmark": core.REGIME_INDEX, "as_of": None}

    tickers = sorted({sym for sym in members})
    try:
        data = core.load_scan_dataset(tickers)
    except Exception:
        data = {}

    try:
        table = core.sector_relative_strength(data=data, lookbacks=lookbacks)
    except Exception as exc:
        raise ApiError(f"Could not compute sector strength: {exc}") from exc

    rows = frame_to_records(table) if table is not None and not table.empty else []
    as_of = None
    if data:
        try:
            as_of = str(max(df.index[-1] for df in data.values() if df is not None and len(df)).date())
        except Exception:
            as_of = None
    benchmark_priced = not core.load_index_history(core.REGIME_INDEX).empty
    return {
        "ready": bool(rows),
        "sectors": rows,
        "benchmark": core.REGIME_INDEX,
        "benchmark_priced": benchmark_priced,
        "lookbacks": list(lookbacks),
        "symbols_mapped": len(members),
        "as_of": as_of,
        "note": (None if benchmark_priced else
                 "Index prices are not synced, so sector returns are compared against "
                 "each other rather than against a priced benchmark. The 'vs' columns "
                 "will be empty until an index sync runs."),
    }


def sync_sectors() -> dict[str, Any]:
    """Fetch sector membership. Needs outbound access, not Dhan."""
    try:
        report = core.sync_sector_membership()
    except Exception as exc:
        raise ApiError(f"Sector sync failed: {exc}") from exc
    ok = [k for k, v in report.items() if isinstance(v, dict) and v.get("ok")]
    bad = {k: v.get("reason") for k, v in report.items()
           if isinstance(v, dict) and not v.get("ok")}
    return {"synced": ok, "failed": bad, "rows": report.get("_total_rows", 0),
            "symbols_mapped": len(core.sector_map()),
            "from_index": len(core.sector_map(source="index")),
            "from_industry": len(core.sector_map(source="industry")),
            # A renamed NSE industry drops stocks silently; surface it.
            "unmapped_industries": report.get("_unmapped_industries", {})}


def sync_indices(years: int = 5) -> dict[str, Any]:
    """Fetch index OHLC. Needs Dhan."""
    if not core.dhan_configured():
        raise ApiError("Index prices come from Dhan, which is not configured.")
    try:
        report = core.sync_index_history(years=years)
    except Exception as exc:
        raise ApiError(f"Index sync failed: {exc}") from exc
    ok = {k: v for k, v in report.items() if v.get("ok")}
    bad = {k: v.get("reason") for k, v in report.items() if not v.get("ok")}
    return {"synced": ok, "failed": bad}


def provider_detail() -> dict[str, Any]:
    """Per-variable presence, for the Data Manager's diagnostics only.

    Never a value - only whether each name is set. Which variable is missing
    is the whole question when credentials are supposedly already in place,
    but it does not belong in an open endpoint.
    """
    return {"dhan": {"variables": core.credential_presence(core.DHAN_CREDENTIAL_NAMES)}}


def provider_status() -> dict[str, Any]:
    """Whether each integration is configured - never the credential itself.

    Reads the process environment only. It used to also read the cached Dhan
    token out of SQLite for a `token_issued_at` field nothing needed, which
    put a database hit on /config - the one endpoint that has to answer while
    a scan is saturating the database and the GIL.
    """
    return {
        "dhan": {
            "configured": bool(core.dhan_configured()),
            "auto_renew": bool(core._dhan_pin_totp_configured()),
            # Deliberately no per-variable map and no token timestamp. /config
            # is unauthenticated, and naming the exact environment variables a
            # server reads - and which of them are unset - tells an attacker
            # what to look for and when the credential was last rotated. The
            # Data Manager's diagnostics endpoint still reports the per-
            # variable detail to an operator who asks for it.
        },
        "twelvedata": {"configured": bool(core.twelvedata_configured())},
        "anthropic": {"configured": bool(core._anthropic_configured())},
        "github_backup": {"configured": bool(core._github_configured())},
    }
