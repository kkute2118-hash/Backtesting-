"""Data Manager: acquisition, diagnostics, backup, token renewal, live feed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.schemas.common import JobEnvelope
from app.schemas.product import FullSyncRequest, LiveFeedRequest, SyncRequest
from app.services import data_manager

router = APIRouter()


@router.get("/data/store")
def store() -> dict[str, Any]:
    return data_manager.store_overview()


@router.post("/data/sync/latest", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def sync_latest(payload: SyncRequest) -> Any:
    """Fast top-up of the newest sessions only."""
    return data_manager.sync_latest(payload.universes, payload.tail_days)


@router.post("/data/sync/full", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def sync_full(payload: FullSyncRequest) -> Any:
    """Walk the full window and fill every gap. Slow, and always explicit."""
    return data_manager.sync_full(payload.universes, payload.period)


@router.post("/data/diagnostics", response_model=JobEnvelope,
             status_code=status.HTTP_202_ACCEPTED)
def run_diagnostics(payload: SyncRequest) -> Any:
    return data_manager.diagnostics(payload.universes)


@router.get("/data/diagnostics")
def stored_diagnostics(limit: int = Query(default=500, ge=1, le=5000)) -> dict[str, Any]:
    return data_manager.stored_diagnostics(limit)


@router.get("/data/history-floor")
def history_floor() -> dict[str, Any]:
    return data_manager.history_floor()


@router.get("/data/errors")
def errors() -> dict[str, Any]:
    return data_manager.recent_errors()


@router.get("/data/connection-test")
def connection_test() -> dict[str, Any]:
    return data_manager.connection_test()


@router.post("/data/smoke-test")
def smoke_test(symbol: str = Query(default="RELIANCE"),
               days: int = Query(default=30, ge=5, le=400)) -> dict[str, Any]:
    return data_manager.smoke_test(symbol, days)


@router.post("/data/token/renew")
def renew_token() -> dict[str, Any]:
    return data_manager.renew_token()


@router.get("/data/backup")
def backup_status() -> dict[str, Any]:
    return data_manager.backup_status()


@router.post("/data/backup")
def backup_now() -> dict[str, Any]:
    return data_manager.backup_now()


@router.post("/data/backup/restore")
def restore_now() -> dict[str, Any]:
    return data_manager.restore_now()


@router.get("/data/backup/diagnostic")
def backup_diagnostic() -> dict[str, Any]:
    """Checks the whole backup path without writing a commit, and names the failure."""
    return data_manager.backup_diagnostic()


@router.post("/data/backup/learning")
def learning_backup() -> dict[str, Any]:
    return data_manager.learning_backup()


@router.post("/data/backup/learning/restore")
def learning_restore() -> dict[str, Any]:
    return data_manager.learning_restore()


@router.post("/live/start")
def live_start(payload: LiveFeedRequest) -> dict[str, Any]:
    return data_manager.live_start(payload.symbols)


@router.post("/live/stop")
def live_stop() -> dict[str, Any]:
    return data_manager.live_stop()


@router.get("/live/prices")
def live_prices(symbols: list[str] = Query(default=[])) -> dict[str, Any]:
    return data_manager.live_prices(symbols or None)
