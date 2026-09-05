"""Cold-start recovery on a host with no persistent disk.

These pin the behaviour that makes a free-tier deployment usable rather than
merely running: after the container is thrown away, the next boot has to put the
candle store and the learning history back, in that order, without ever
destroying data it cannot recover.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.engine import core
from app.services import bootstrap


@pytest.fixture()
def isolated_db(monkeypatch, frames):
    """A throwaway database for each test in this module.

    restore_on_cold_start() deletes the database file by design, so these tests
    must never point at the session-wide store the rest of the suite shares —
    the first deletion would take every later test down with it.
    """
    path = os.path.join(tempfile.mkdtemp(prefix="ati-bootstrap-"), "market_data.sqlite3")
    monkeypatch.setattr(core, "DATA_DB", path)

    con = core._db()
    try:
        for symbol, df in frames.items():
            core._save(con, symbol, df)
        con.commit()
    finally:
        con.close()
    return path


@pytest.fixture()
def empty_candles(isolated_db):
    """An isolated database whose candle store is empty — a fresh container."""
    con = core._db()
    try:
        con.execute("DELETE FROM candles")
        con.commit()
    finally:
        con.close()
    assert bootstrap._candle_count() == 0
    return isolated_db


@pytest.fixture()
def no_backup(monkeypatch):
    monkeypatch.setattr(core, "_github_configured", lambda: False)


@pytest.fixture()
def backup_configured(monkeypatch):
    monkeypatch.setattr(core, "_github_configured", lambda: True)


def test_does_nothing_without_a_backup_configured(no_backup, isolated_db):
    result = bootstrap.restore_on_cold_start()
    assert result["attempted"] is False
    assert result["restored_full"] is False
    # The message has to say what the consequence is, because on an ephemeral
    # host this is the difference between working and losing everything.
    assert "persistent disk" in result["reason"]


def test_leaves_a_populated_candle_store_alone(backup_configured, isolated_db, monkeypatch):
    """The guard that matters: never overwrite a database that holds candles."""
    called = []
    monkeypatch.setattr(core, "restore_db_from_github",
                        lambda: called.append("full") or True)

    result = bootstrap.restore_on_cold_start()

    assert result["attempted"] is False
    assert called == [], "a populated store must never be replaced"
    assert result["candles_before"] > 0
    assert os.path.exists(core.DATA_DB)


def test_restores_the_whole_database_when_there_are_no_candles(
    backup_configured, empty_candles, frames, monkeypatch
):
    """The cold-start path: empty candle store, whole-database backup available."""

    def fake_restore_full():
        # What the real function does: writes a database file with candles in it.
        con = core._db()
        try:
            for symbol, df in frames.items():
                core._save(con, symbol, df)
            con.commit()
        finally:
            con.close()
        return True

    learning_called = []
    monkeypatch.setattr(core, "restore_db_from_github", fake_restore_full)
    monkeypatch.setattr(core, "restore_learning_from_github",
                        lambda return_reason=False: learning_called.append(1) or (True, "ok"))

    result = bootstrap.restore_on_cold_start()

    assert result["attempted"] is True
    assert result["restored_full"] is True
    assert result["candles_after"] > 0
    # The learning backup must be merged on top, so a newer learning backup
    # wins over whatever the older whole-database snapshot carried.
    assert learning_called, "the learning backup must be merged after the full restore"


def test_reports_honestly_when_no_backup_exists_yet(backup_configured, empty_candles,
                                                   monkeypatch):
    monkeypatch.setattr(core, "restore_db_from_github", lambda: False)
    monkeypatch.setattr(core, "restore_learning_from_github",
                        lambda return_reason=False: (False, "no backup"))
    monkeypatch.setattr(core, "_GITHUB_LAST_ERROR", "")

    result = bootstrap.restore_on_cold_start()

    assert result["restored_full"] is False
    assert "no backup" in result["reason"].lower()


def test_never_raises_when_the_restore_blows_up(backup_configured, empty_candles, monkeypatch):
    """A failed restore must leave the app running, not stop it booting."""

    def explode(*_args, **_kwargs):
        raise RuntimeError("GitHub is down")

    monkeypatch.setattr(core, "restore_db_from_github", explode)
    monkeypatch.setattr(core, "restore_learning_from_github", explode)

    result = bootstrap.restore_on_cold_start()
    assert result["restored_full"] is False
    assert result["candles_after"] == 0


def test_protect_helpers_swallow_provider_failures(monkeypatch):
    monkeypatch.setattr(core, "maybe_backup_db", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("network")))
    assert bootstrap.protect_learning_data() is False

    monkeypatch.setattr(core, "backup_db_to_github", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("network")))
    ok, reason = bootstrap.protect_full_database()
    assert ok is False and "network" in reason


def test_health_reports_what_the_boot_recovered(client):
    body = client.get("/api/v1/health").json()
    assert "boot_restore" in body
    assert "reason" in body["boot_restore"]
