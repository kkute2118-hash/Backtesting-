"""Product-level storage: watchlists, scanner presets, preferences, run history.

These tables live in the same SQLite file as the engine's own, on purpose. The
engine already backs that file up to GitHub and treats any table it does not
list in ``REBUILDABLE_TABLES`` as irreplaceable - so a watchlist survives a
container reboot with no extra machinery, which a second database file would
not have done.

Schema changes are applied by ``ensure_app_tables()``, which is idempotent and
runs on startup and before any read. That mirrors how ``core._db()`` already
manages its own schema; adding an ORM and a migration tool alongside it would
give the same file two owners.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from app.engine import core

SCHEMA_VERSION = 1
_SCHEMA_KEY = "__schema_version"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Engine-managed connection with the product tables guaranteed present."""
    con = core._db()
    con.row_factory = sqlite3.Row
    _apply_schema(con)
    return con


def _apply_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_preferences(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_watchlists(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_watchlist_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id INTEGER NOT NULL
                REFERENCES app_watchlists(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            note TEXT,
            added_at TEXT NOT NULL,
            UNIQUE(watchlist_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS app_scanner_presets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            builtin INTEGER NOT NULL DEFAULT 0,
            config TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT
        );

        CREATE TABLE IF NOT EXISTS app_scan_runs(
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            request TEXT NOT NULL,
            stats TEXT,
            error TEXT,
            row_count INTEGER DEFAULT 0,
            results TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_app_scan_runs_kind
            ON app_scan_runs(kind, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_app_watchlist_items_symbol
            ON app_watchlist_items(symbol);
        """
    )
    con.commit()
    _migrate(con)


def _migrate(con: sqlite3.Connection) -> None:
    """Run one-time setup exactly once, tracked by a stored schema version.

    Seeding lives here rather than behind a startup hook so a process that
    reaches the database another way - a test client, the cron runner, a shell -
    still finds a complete, seeded schema.
    """
    row = con.execute("SELECT value FROM app_preferences WHERE key=?",
                      (_SCHEMA_KEY,)).fetchone()
    try:
        applied = int(json.loads(row["value"])) if row else 0
    except (TypeError, ValueError):
        applied = 0
    if applied >= SCHEMA_VERSION:
        return
    _seed_builtin_presets(con)
    con.execute(
        """INSERT INTO app_preferences(key,value,updated_at) VALUES(?,?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                          updated_at=excluded.updated_at""",
        (_SCHEMA_KEY, json.dumps(SCHEMA_VERSION), _now()))
    con.commit()


def ensure_app_tables() -> None:
    """Idempotent schema + seed. Safe to call on every startup."""
    connect().close()


# --------------------------------------------------------------------------- #
# preferences
# --------------------------------------------------------------------------- #
def get_preference(key: str, default: Any = None) -> Any:
    con = connect()
    try:
        row = con.execute("SELECT value FROM app_preferences WHERE key=?", (key,)).fetchone()
    finally:
        con.close()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return default


def set_preference(key: str, value: Any) -> None:
    con = connect()
    try:
        con.execute(
            """INSERT INTO app_preferences(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                              updated_at=excluded.updated_at""",
            (key, json.dumps(value), _now()),
        )
        con.commit()
    finally:
        con.close()


def all_preferences() -> dict[str, Any]:
    con = connect()
    try:
        rows = con.execute("SELECT key,value FROM app_preferences").fetchall()
    finally:
        con.close()
    out: dict[str, Any] = {}
    for row in rows:
        if str(row["key"]).startswith("__"):
            continue  # internal bookkeeping, not a user preference
        try:
            out[row["key"]] = json.loads(row["value"])
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# built-in presets
# --------------------------------------------------------------------------- #
# Every preset below is expressed only in options the engine actually supports:
# which of strategies S1-S4 to evaluate, the universe, the score gate, whether
# to overlay the live intraday bar, and the post-scan result filters. There is
# deliberately no "Oversold" or "Volume Surge" preset - the engine has no such
# screen, and inventing one would mean inventing rules the scanner never ran.
BUILTIN_PRESETS: list[dict[str, Any]] = [
    {
        "name": "All strategies — forward-test gate",
        "description": "Every rule of S1-S4 evaluated independently, ranked, "
                       "filtered to the score at which a signal is recorded as a forward test.",
        "config": {"universes": ["Nifty 500"], "strategies": [1, 2, 3, 4],
                   "min_score": 85, "use_live_prices": False, "limit": None},
    },
    {
        "name": "Full NSE — research sweep",
        "description": "The whole ~2000-name NSE cash list at a lower gate, for "
                       "research rather than execution. Slowest scan.",
        "config": {"universes": ["NSE All Cash (~2000)"], "strategies": [1, 2, 3, 4],
                   "min_score": 60, "use_live_prices": False, "limit": None},
    },
    {
        "name": "S4 SEPA only",
        "description": "Minervini-style stage analysis: the S4 SEPA rule set on its own.",
        "config": {"universes": ["Nifty 500"], "strategies": [4],
                   "min_score": 60, "use_live_prices": False, "limit": None},
    },
    {
        "name": "Smallcap hunt",
        "description": "Smallcap 250 across all four strategies. The shared "
                       "liquidity and price-action gate still applies to every name.",
        "config": {"universes": ["Nifty Smallcap 250"], "strategies": [1, 2, 3, 4],
                   "min_score": 70, "use_live_prices": False, "limit": None},
    },
    {
        "name": "Intraday live overlay",
        "description": "Scans against today's still-forming candle from Dhan's "
                       "quote feed instead of yesterday's close. Session hours only.",
        "config": {"universes": ["Nifty 500"], "strategies": [1, 2, 3, 4],
                   "min_score": 75, "use_live_prices": True, "limit": None},
    },
]


def _seed_builtin_presets(con: sqlite3.Connection) -> None:
    """Insert the shipped presets once. A user edit is never overwritten."""
    for preset in BUILTIN_PRESETS:
        con.execute(
            """INSERT OR IGNORE INTO app_scanner_presets
                   (name, description, builtin, config, created_at, updated_at)
               VALUES(?,?,1,?,?,?)""",
            (preset["name"], preset["description"], json.dumps(preset["config"]),
             _now(), _now()),
        )
    con.commit()


# --------------------------------------------------------------------------- #
# small helpers shared by the services
# --------------------------------------------------------------------------- #
def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
