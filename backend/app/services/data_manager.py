"""Dhan data acquisition, diagnostics and database backup.

Data acquisition is always an explicit action here. No scan, backtest or page
load downloads anything: the persistent candle store exists precisely so that
research runs against a fixed, already-paid-for dataset, and a background
download would both burn the 5 req/s Dhan budget and change a study's inputs
while it was running.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError, NotConfigured
from app.engine import core
from app.services import bootstrap, jobs
from app.services.jobs import JobHandle
from app.services.serialization import clean_value, frame_to_records
from app.services.universe import resolve

SYNC_LATEST_KIND = "sync_latest"
SYNC_FULL_KIND = "sync_full"
DIAGNOSTIC_KIND = "sync_diagnostics"


def _require_dhan() -> None:
    if not core.dhan_configured():
        raise NotConfigured(
            "Dhan is not configured. Set DHAN_CLIENT_ID plus DHAN_PIN and "
            "DHAN_TOTP_SECRET (or DHAN_ACCESS_TOKEN) in the backend environment."
        )


def store_overview() -> dict[str, Any]:
    """What the local candle store currently holds."""
    con = core._db()
    try:
        totals = con.execute(
            "SELECT COUNT(*) , COUNT(DISTINCT symbol), MIN(dt), MAX(dt) FROM candles"
        ).fetchone()
        thin = con.execute(
            """SELECT symbol, COUNT(*) AS bars, MAX(dt) AS latest FROM candles
            GROUP BY symbol HAVING bars < 260 ORDER BY bars LIMIT 200"""
        ).fetchall()
        freshness_log = pd.read_sql_query(
            "SELECT synced_at, most_recent_date_pulled, symbols_updated "
            "FROM sync_freshness_log ORDER BY id DESC LIMIT 20", con)
    finally:
        con.close()

    bars, symbols, first, last = totals or (0, 0, None, None)
    return {
        "database_path": core.DATA_DB,
        "bars": int(bars or 0),
        "symbols": int(symbols or 0),
        "earliest_session": first,
        "latest_session": last,
        "thin_symbols": [{"symbol": r[0], "bars": int(r[1]), "latest": r[2]} for r in thin],
        "sync_log": frame_to_records(freshness_log),
        "tail_days": core.LATEST_SYNC_TAIL_DAYS,
    }


def sync_latest(universes: list[str], tail_days: int | None = None) -> dict[str, Any]:
    """Fast top-up: only the last few sessions per symbol.

    Also re-requests the newest already-stored bars, so a candle first written
    while its session was still open gets corrected once it really closes.
    """
    _require_dhan()
    tickers = resolve(universes)
    days = int(tail_days or core.LATEST_SYNC_TAIL_DAYS)
    request = {"universes": universes, "tail_days": days, "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.02, f"Requesting the last {days} days for {len(tickers):,} stocks")
        summary = core.sync_latest_sessions(
            tickers, tail_days=days,
            progress_cb=lambda f: handle.progress(min(0.99, float(f)), "Downloading"))

        # Candles just cost real Dhan rate limit to fetch. On a host with no
        # persistent disk they are gone at the next restart unless pushed now.
        handle.progress(0.99, "Backing up the candle store")
        backed_up, reason = bootstrap.protect_full_database()

        stats = {str(k): clean_value(v) for k, v in (summary or {}).items()}
        stats["backed_up"] = backed_up
        stats["backup_note"] = reason
        return {"stats": stats, "rows": [], "request": request}

    job = jobs.registry.submit(SYNC_LATEST_KIND, "Top up latest sessions", work,
                               request=request, persist=True)
    return job.to_public()


def sync_full(universes: list[str], period: str = "2 Years") -> dict[str, Any]:
    """Walk the full window per symbol and fill every gap. Slow, and explicit."""
    _require_dhan()
    from app.services.backtest import period_window

    tickers = resolve(universes)
    start, end = period_window(period)
    request = {"universes": universes, "period": period, "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.02, f"Filling missing history for {len(tickers):,} stocks")
        data = core.sync_missing_backtest_data(tickers, start, end)
        handle.progress(0.9, "Recording diagnostics")
        try:
            core.compute_and_store_sync_diagnostics(tickers)
        except Exception:
            pass
        handle.progress(0.95, "Backing up the candle store")
        backed_up, backup_note = bootstrap.protect_full_database()
        return {
            "stats": {
                "symbols_requested": len(tickers),
                "symbols_with_data": len(data or {}),
                "errors": [str(e) for e in (core._DHAN_LAST_DATA_ERRORS or [])][:20],
                "no_data": [str(e) for e in (core._DHAN_LAST_NO_DATA or [])][:20],
                "backed_up": backed_up,
                "backup_note": backup_note,
            },
            "rows": [], "request": request,
        }

    job = jobs.registry.submit(SYNC_FULL_KIND, f"Full sync — {period}", work,
                               request=request, persist=True)
    return job.to_public()


def diagnostics(universes: list[str]) -> dict[str, Any]:
    """Why each thin symbol is thin: not in the master, an API error, or new."""
    tickers = resolve(universes)
    request = {"universes": universes, "universe_size": len(tickers)}

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.1, "Classifying symbols below the 260-bar threshold")
        df = core.compute_and_store_sync_diagnostics(tickers)
        return {"rows": frame_to_records(df) if isinstance(df, pd.DataFrame) else [],
                "columns": [str(c) for c in df.columns] if isinstance(df, pd.DataFrame) else [],
                "stats": {"universe_size": len(tickers)}, "request": request}

    job = jobs.registry.submit(DIAGNOSTIC_KIND, "Sync diagnostics", work,
                               request=request, persist=True)
    return job.to_public()


def stored_diagnostics(limit: int = 500) -> dict[str, Any]:
    con = core._db()
    try:
        df = pd.read_sql_query(
            "SELECT symbol, checked_at, bar_count, reason FROM sync_diagnostics "
            "ORDER BY bar_count ASC LIMIT ?", con, params=(int(limit),))
    finally:
        con.close()
    return {"rows": frame_to_records(df)}


def history_floor() -> dict[str, Any]:
    """Per symbol, the earliest date Dhan admits to having — so we stop asking."""
    df = core.dhan_history_floor_table()
    return {"rows": frame_to_records(df)}


def connection_test() -> dict[str, Any]:
    """Read-only Dhan connectivity check. Never writes, never places an order."""
    result = core.dhan_connection_diagnostic()
    return {"checks": clean_value(result)}


def smoke_test(symbol: str = "RELIANCE", days: int = 30) -> dict[str, Any]:
    _require_dhan()
    result = core.dhan_historical_smoke_test(symbol, days=days)
    return {"symbol": symbol, "days": days, "result": clean_value(result)}


def recent_errors() -> dict[str, Any]:
    """The last Dhan errors and DH-907 'no data' notes, for the diagnostics panel."""
    return {
        "errors": [str(e) for e in (core._DHAN_LAST_DATA_ERRORS or [])][:50],
        "no_data": [str(e) for e in (core._DHAN_LAST_NO_DATA or [])][:50],
        "schema_error": str(core._STARTUP_SCHEMA_ERROR or ""),
    }


# --------------------------------------------------------------------------- #
# database backup
# --------------------------------------------------------------------------- #
def backup_status() -> dict[str, Any]:
    return {
        "configured": bool(core._github_configured()),
        "repo": core._github_setting("GITHUB_REPO"),
        "branch": core._github_backup_branch(),
        "db_path": core.DATA_DB,
        "db_rows": core.db_row_count(),
        "last_error": str(core._GITHUB_LAST_ERROR or ""),
    }


def backup_now() -> dict[str, Any]:
    ok, reason = core.backup_db_to_github(return_reason=True)
    if not ok:
        raise ApiError(reason or "The backup did not complete.")
    return {"ok": True, "message": reason or "Database backed up."}


def restore_now() -> dict[str, Any]:
    restored = core.restore_db_from_github()
    return {"ok": bool(restored),
            "message": "Database restored from the GitHub backup."
                       if restored else "No backup was restored — see the diagnostic."}


def backup_diagnostic() -> dict[str, Any]:
    """Check the whole backup path without writing a commit, and name the failure."""
    return {"result": clean_value(core.github_backup_diagnostic())}


def learning_backup() -> dict[str, Any]:
    ok, reason = core.backup_learning_to_github(return_reason=True)
    if not ok:
        raise ApiError(reason or "The learning backup did not complete.")
    return {"ok": True, "message": reason}


def learning_restore() -> dict[str, Any]:
    ok, reason = core.restore_learning_from_github(return_reason=True)
    if not ok:
        raise ApiError(reason or "The learning restore did not complete.")
    return {"ok": True, "message": reason}


def renew_token() -> dict[str, Any]:
    """Mint a fresh 24h Dhan access token via headless PIN + TOTP."""
    if not core._dhan_pin_totp_configured():
        raise NotConfigured(
            "Automatic renewal needs DHAN_PIN and DHAN_TOTP_SECRET alongside "
            "DHAN_CLIENT_ID. With only a manual DHAN_ACCESS_TOKEN there is nothing to renew."
        )
    core._dhan_generate_fresh_token()
    _token, issued = core._read_cached_dhan_token()
    return {"ok": True, "issued_at": issued}


# --------------------------------------------------------------------------- #
# live feed
# --------------------------------------------------------------------------- #
def live_start(symbols: list[str] | None = None) -> dict[str, Any]:
    _require_dhan()
    clean = [str(s).upper().replace(".NS", "") for s in (symbols or []) if str(s).strip()]
    if not clean:
        con = core._db()
        try:
            clean = [r[0] for r in con.execute(
                "SELECT DISTINCT symbol FROM forward_tests WHERE status='ACTIVE'")]
        finally:
            con.close()
    if not clean:
        raise ApiError("There is nothing to stream — no active forward tests and no symbols given.")
    core.start_persistent_live_feed(clean)
    return {"ok": True, "symbols": clean, "count": len(clean)}


def live_stop() -> dict[str, Any]:
    core.stop_persistent_live_feed()
    return {"ok": True}


def live_prices(symbols: list[str] | None = None) -> dict[str, Any]:
    df = core.read_live_prices(symbols)
    return {"rows": frame_to_records(df)}
