"""FastAPI application entry point.

    uvicorn app.main:app --reload --port 8000   (from backend/)

The engine (``app.engine.core``) is imported at startup rather than lazily on
the first request: it opens the SQLite database, applies its schema and, when a
GitHub backup is configured, restores accumulated forward tests and learning
data after a container reboot. Doing that during a request would make the first
user of the day wait for a restore.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
)
log = logging.getLogger("ati.api")

settings = get_settings()

# Set by the startup hook so /health can report what happened on this boot.
BOOT_RESTORE: dict[str, object] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.db import app_store
    from app.engine import core
    from app.services import bootstrap

    log.info("Engine %s — database %s", core.ENGINE_VERSION, core.DATA_DB)

    # Before anything reads the database: on a host with no persistent disk
    # this container starts with an empty one, and the GitHub backup is the
    # only thing that can put the candles and the learning history back.
    try:
        BOOT_RESTORE.update(bootstrap.restore_on_cold_start())
    except Exception:
        log.exception("Cold-start restore failed")

    try:
        app_store.ensure_app_tables()
    except Exception:
        # A database fault must be reported by /health, not kill the server:
        # the Data Manager endpoints are exactly what the user needs to
        # diagnose and fix it.
        log.exception("Could not prepare the product tables")
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version="2.0.0",
    description=(
        "Research and decision-support API for Indian equities: strategies S1-S4, "
        "multi-timeframe scoring, safety, walk-forward backtests, forward testing "
        "and adaptive learning. Research output only — it places no orders."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_error_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
