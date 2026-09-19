"""Health, configuration status and preferences."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import ttl_cache
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


CONFIG_TTL_SECONDS = 60
DASHBOARD_TTL_SECONDS = 30


@router.get("/config")
def config() -> dict[str, Any]:
    """Which integrations are configured. Never returns a credential value.

    Pure: environment variables and two literal lists, no database and no
    network. It is a 1 KB response that the whole UI blocks on, and it was
    taking tens of seconds because it read the cached Dhan token out of SQLite
    while a scan held the file.
    """
    return ttl_cache.cached("config", CONFIG_TTL_SECONDS, _build_config)


def _build_config() -> dict[str, Any]:
    return {
        "providers": market.provider_status(),
        "universes": core.UNIVERSE_CHOICES,
        "strategies": [
            {"id": 1, "label": "S1", "name": "Monthly base continuation"},
            {"id": 2, "label": "S2", "name": "Tight pullback in an uptrend"},
            {"id": 3, "label": "S3", "name": "Liquid pullback to EMA50"},
            {"id": 4, "label": "S4_SEPA", "name": "SEPA stage analysis"},
            {"id": 5, "label": "S5_POCKETPIVOT", "name": "Pocket pivot (O'Neil disciple)"},
        ],
        "default_strategies": list(core.DEFAULT_STRATEGIES),
        "forward_gate_default": 85,
        "market": market.market_status(),
    }


@router.get("/dashboard")
def dashboard() -> dict[str, Any]:
    """Everything the dashboard needs, in one request.

    The page was firing about seven in parallel; on a single free-plan
    instance they queue behind each other on the same SQLite file and the same
    GIL, so the slowest one sets the page's load time. The individual
    endpoints all still work - this composes them rather than replacing them.
    """
    return ttl_cache.cached("dashboard", DASHBOARD_TTL_SECONDS, _build_dashboard)


def _build_dashboard() -> dict[str, Any]:
    payload: dict[str, Any] = {"config": _build_config()}
    # One slow or broken section must not blank the whole page, so each is
    # reported on its own terms and its failure named where the UI can show it.
    for key, build in (("overview", market.overview),
                       ("preferences", lambda: app_store.all_preferences())):
        try:
            payload[key] = build()
        except Exception as exc:  # noqa: BLE001 - the message is the product
            payload[key] = None
            payload.setdefault("errors", {})[key] = str(exc)
    return payload


@router.get("/cache-stats", include_in_schema=False)
def cache_stats() -> dict[str, Any]:
    """What the caches are holding. Diagnostics for the 512 MB ceiling."""
    from app.engine import st_compat
    return {"response_cache": ttl_cache.stats(),
            "memoised": st_compat.cache_report()[:12],
            "rss_mb": core.process_rss_mb()}


@router.get("/preferences")
def preferences() -> dict[str, Any]:
    return {"preferences": app_store.all_preferences()}


@router.put("/preferences")
def set_preference(payload: PreferenceUpdate) -> dict[str, Any]:
    app_store.set_preference(payload.key, payload.value)
    return {"preferences": app_store.all_preferences()}
