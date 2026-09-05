"""Watchlists and scanner presets — the product-level state Streamlit never had."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.schemas.product import (PresetCreate, PresetUpdate, WatchlistCreate,
                                 WatchlistSymbols, WatchlistUpdate)
from app.services import presets as preset_service
from app.services import watchlists as watchlist_service

router = APIRouter()


# --------------------------------------------------------------------------- #
# watchlists
# --------------------------------------------------------------------------- #
@router.get("/watchlists")
def list_watchlists(quotes: bool = Query(default=True)) -> dict[str, Any]:
    return {"watchlists": watchlist_service.list_all(with_quotes=quotes)}


@router.post("/watchlists", status_code=status.HTTP_201_CREATED)
def create_watchlist(payload: WatchlistCreate) -> dict[str, Any]:
    return watchlist_service.create(payload.name, payload.description)


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: int, quotes: bool = Query(default=True)) -> dict[str, Any]:
    return watchlist_service.get(watchlist_id, with_quotes=quotes)


@router.patch("/watchlists/{watchlist_id}")
def update_watchlist(watchlist_id: int, payload: WatchlistUpdate) -> dict[str, Any]:
    return watchlist_service.rename(watchlist_id, payload.name, payload.description)


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(watchlist_id: int) -> None:
    watchlist_service.delete(watchlist_id)


@router.post("/watchlists/{watchlist_id}/symbols")
def add_symbols(watchlist_id: int, payload: WatchlistSymbols) -> dict[str, Any]:
    return watchlist_service.add_symbols(watchlist_id, payload.symbols, payload.note)


@router.delete("/watchlists/{watchlist_id}/symbols/{symbol}")
def remove_symbol(watchlist_id: int, symbol: str) -> dict[str, Any]:
    return watchlist_service.remove_symbol(watchlist_id, symbol)


# --------------------------------------------------------------------------- #
# presets
# --------------------------------------------------------------------------- #
@router.get("/presets")
def list_presets() -> dict[str, Any]:
    return {"presets": preset_service.list_all()}


@router.post("/presets", status_code=status.HTTP_201_CREATED)
def create_preset(payload: PresetCreate) -> dict[str, Any]:
    return preset_service.create(payload.name, payload.description,
                                 payload.config.model_dump())


@router.get("/presets/{preset_id}")
def get_preset(preset_id: int) -> dict[str, Any]:
    return preset_service.get(preset_id)


@router.patch("/presets/{preset_id}")
def update_preset(preset_id: int, payload: PresetUpdate) -> dict[str, Any]:
    return preset_service.update(
        preset_id, name=payload.name, description=payload.description,
        config=payload.config.model_dump() if payload.config else None)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(preset_id: int) -> None:
    preset_service.delete(preset_id)
