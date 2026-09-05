"""Health, configuration status and preferences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import app_store
from app.engine import core
from app.schemas.product import PreferenceUpdate
from app.services import market

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus whether the engine's database is actually readable."""
    database_ok, database_error = True, None
    try:
        con = core._db()
        con.close()
    except Exception as exc:
        database_ok, database_error = False, str(exc)
    from app.main import BOOT_RESTORE

    return {
        "status": "ok" if database_ok else "degraded",
        "engine_version": core.ENGINE_VERSION,
        "app_version": core.APP_VERSION,
        "database": {"ok": database_ok, "path": core.DATA_DB, "error": database_error},
        # What this container recovered when it woke up. On a host with a
        # persistent disk this is a no-op; on a free tier it is the difference
        # between an empty app and a working one.
        "boot_restore": dict(BOOT_RESTORE),
    }


@router.get("/config")
def config() -> dict[str, Any]:
    """Which integrations are configured. Never returns a credential value."""
    return {
        "providers": market.provider_status(),
        "universes": core.UNIVERSE_CHOICES,
        "strategies": [
            {"id": 1, "label": "S1", "name": "Monthly base continuation"},
            {"id": 2, "label": "S2", "name": "Tight pullback in an uptrend"},
            {"id": 3, "label": "S3", "name": "Liquid pullback to EMA50"},
            {"id": 4, "label": "S4_SEPA", "name": "SEPA stage analysis"},
        ],
        "forward_gate_default": 85,
        "market": market.market_status(),
    }


@router.get("/preferences")
def preferences() -> dict[str, Any]:
    return {"preferences": app_store.all_preferences()}


@router.put("/preferences")
def set_preference(payload: PreferenceUpdate) -> dict[str, Any]:
    app_store.set_preference(payload.key, payload.value)
    return {"preferences": app_store.all_preferences()}
