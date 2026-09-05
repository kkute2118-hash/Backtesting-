"""Cold-start recovery, for hosts that give the process no persistent disk.

On a free-tier container the filesystem is thrown away every time the service
sleeps, so each wake starts with an empty database: no candles, no forward
tests, no learning. The engine already knows how to put both back — this wires
those two restores into the API's startup in the right order.

The order is the whole point. ``core`` runs ``_startup_restore_learning()`` at
*import*, which pulls the small learning backup and thereby makes the database
non-empty. ``restore_db_from_github()`` refuses to overwrite a database that
holds rows — sensibly, since it would clobber live data — so by the time any
startup hook runs, the whole-database restore has already been disqualified and
the candle store stays empty. The app then looks fully configured but can scan
nothing.

So this checks the one table that actually settles it — ``candles`` — and when
that is empty it puts the whole database back, then merges the learning backup
on top. The merge is ``INSERT OR IGNORE`` inside the engine, so it can only add
rows: a newer learning backup wins over whatever the older whole-database
snapshot carried, and nothing is ever destroyed.
"""

from __future__ import annotations

import logging
import os

from app.engine import core

log = logging.getLogger("ati.bootstrap")


def _candle_count() -> int:
    """Rows in the candle store, or -1 if it cannot be read."""
    try:
        con = core._db()
        try:
            return int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
        finally:
            con.close()
    except Exception:
        return -1


def _remove_database() -> None:
    """Delete the SQLite file and its journal siblings."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = f"{core.DATA_DB}{suffix}"
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            log.warning("Could not remove %s", path, exc_info=True)


def restore_on_cold_start() -> dict[str, object]:
    """Rebuild the database from the GitHub backup when this container is new.

    Never raises: a failed restore leaves the app running on an empty store,
    which is exactly what it would have done without a backup configured. The
    returned dict is for logging and the /health payload, not for control flow.
    """
    result: dict[str, object] = {
        "attempted": False, "restored_full": False, "restored_learning": False,
        "candles_before": 0, "candles_after": 0, "reason": "",
    }

    if not core._github_configured():
        result["reason"] = ("No GitHub backup configured, so nothing can be restored. "
                            "On a host without a persistent disk this means the database "
                            "starts empty after every restart.")
        return result

    before = _candle_count()
    result["candles_before"] = before

    if before > 0:
        result["reason"] = "The candle store already holds data; nothing to restore."
        result["candles_after"] = before
        return result
    if before < 0:
        result["reason"] = "The database could not be read; leaving it alone."
        return result

    result["attempted"] = True

    # Safe to discard: zero candles means the only rows present are whatever
    # core's import-time hook just pulled from the learning backup, and the
    # learning restore below puts those back from the same source.
    _remove_database()

    try:
        result["restored_full"] = bool(core.restore_db_from_github())
    except Exception as exc:
        log.warning("Whole-database restore failed: %s", exc)

    try:
        restored, _reason = core.restore_learning_from_github(return_reason=True)
        result["restored_learning"] = bool(restored)
    except Exception as exc:
        log.warning("Learning restore failed: %s", exc)

    after = _candle_count()
    result["candles_after"] = max(0, after)

    if result["restored_full"]:
        result["reason"] = f"Restored the database from the GitHub backup ({after:,} candles)."
    elif result["restored_learning"]:
        result["reason"] = ("No whole-database backup found, so the candle store is empty and "
                            "needs a sync. Forward tests and learning were restored.")
    else:
        result["reason"] = (core._GITHUB_LAST_ERROR
                            or "Nothing was restored — no backup exists yet.")

    log.info("Cold-start restore: %s", result["reason"])
    return result


def protect_learning_data() -> bool:
    """Push the small learning backup, rate-limited by the engine.

    Called after anything that writes something irreplaceable. Cheap enough to
    run inline: it copies only the tables that cannot be rebuilt, which is
    kilobytes, not the tens of megabytes of candle history.
    """
    try:
        return bool(core.maybe_backup_db())
    except Exception:
        log.warning("Learning backup failed", exc_info=True)
        return False


def protect_full_database() -> tuple[bool, str]:
    """Push the whole database, candles included.

    Only worth doing after a sync, which is the expensive thing this protects:
    on a host with no persistent disk, candles downloaded and then lost to a
    restart cost real Dhan rate limit to fetch again.
    """
    try:
        ok, reason = core.backup_db_to_github(return_reason=True)
        if not ok:
            log.warning("Whole-database backup failed: %s", reason)
        return bool(ok), str(reason or "")
    except Exception as exc:
        log.warning("Whole-database backup failed", exc_info=True)
        return False, f"{type(exc).__name__}: {exc}"
