"""Saved scanner configurations.

A preset stores only options the scanner really accepts: universes, which of
S1-S4 to evaluate, the score gate, the live-intraday overlay and a result cap.
Presets that would imply screens the engine does not implement are deliberately
not offered - a "Volume Surge" preset would have to invent a rule the scanner
never runs.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import ApiError, NotFound
from app.db import app_store
from app.engine import core

ALLOWED_KEYS = {"universes", "strategies", "min_score", "use_live_prices", "limit"}


def _validate(config: dict[str, Any]) -> dict[str, Any]:
    unknown = set(config) - ALLOWED_KEYS
    if unknown:
        raise ApiError(f"Unsupported preset option(s): {', '.join(sorted(unknown))}")

    universes = config.get("universes") or []
    if not universes:
        raise ApiError("A preset needs at least one universe.")
    bad = [u for u in universes if u not in core.UNIVERSE_CHOICES]
    if bad:
        raise ApiError(f"Unknown universe: {', '.join(bad)}")

    strategies = sorted({int(s) for s in (config.get("strategies") or []) if int(s) in (1, 2, 3, 4)})
    if not strategies:
        raise ApiError("A preset needs at least one of strategies 1-4.")

    min_score = float(config.get("min_score", 85))
    if not 0 <= min_score <= 100:
        raise ApiError("Minimum score must be between 0 and 100.")

    limit = config.get("limit")
    return {
        "universes": list(universes),
        "strategies": strategies,
        "min_score": min_score,
        "use_live_prices": bool(config.get("use_live_prices", False)),
        "limit": int(limit) if limit else None,
    }


def _row_to_preset(row) -> dict[str, Any]:
    record = dict(row)
    try:
        record["config"] = json.loads(record["config"])
    except (TypeError, ValueError):
        record["config"] = {}
    record["builtin"] = bool(record.get("builtin"))
    return record


def list_all() -> list[dict[str, Any]]:
    con = app_store.connect()
    try:
        rows = con.execute(
            "SELECT * FROM app_scanner_presets ORDER BY builtin DESC, name COLLATE NOCASE"
        ).fetchall()
    finally:
        con.close()
    return [_row_to_preset(r) for r in rows]


def get(preset_id: int) -> dict[str, Any]:
    con = app_store.connect()
    try:
        row = con.execute("SELECT * FROM app_scanner_presets WHERE id=?", (preset_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise NotFound(f"Preset {preset_id} does not exist.")
    return _row_to_preset(row)


def create(name: str, description: str | None, config: dict[str, Any]) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ApiError("Give the preset a name.")
    validated = _validate(config)
    con = app_store.connect()
    try:
        if con.execute("SELECT 1 FROM app_scanner_presets WHERE name=?", (name,)).fetchone():
            raise ApiError(f"A preset called '{name}' already exists.")
        cur = con.execute(
            """INSERT INTO app_scanner_presets(name,description,builtin,config,created_at,updated_at)
               VALUES(?,?,0,?,?,?)""",
            (name, description, json.dumps(validated), app_store._now(), app_store._now()))
        con.commit()
        return get(int(cur.lastrowid))
    finally:
        con.close()


def update(preset_id: int, *, name: str | None = None, description: str | None = None,
           config: dict[str, Any] | None = None) -> dict[str, Any]:
    current = get(preset_id)
    if current["builtin"] and config is not None:
        # A shipped preset is a reference point; editing one is done by saving a
        # copy, which keeps the original available to compare against.
        raise ApiError(
            "Built-in presets cannot be edited. Save it under a new name to change its rules."
        )
    merged = _validate(config) if config is not None else current["config"]
    con = app_store.connect()
    try:
        con.execute(
            "UPDATE app_scanner_presets SET name=?, description=?, config=?, updated_at=? WHERE id=?",
            ((name or current["name"]).strip(),
             description if description is not None else current["description"],
             json.dumps(merged), app_store._now(), preset_id))
        con.commit()
    finally:
        con.close()
    return get(preset_id)


def delete(preset_id: int) -> None:
    preset = get(preset_id)
    if preset["builtin"]:
        raise ApiError("Built-in presets cannot be deleted.")
    con = app_store.connect()
    try:
        con.execute("DELETE FROM app_scanner_presets WHERE id=?", (preset_id,))
        con.commit()
    finally:
        con.close()
