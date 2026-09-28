"""Read-only mirror mode: the Oracle host follows the GitHub backup and never
writes it, and never takes the Dhan login from a running job."""

from __future__ import annotations

import gzip
import shutil
import sqlite3

import pytest

from app.engine import core


def _db_file(path, candles=1, extra=None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE candles(symbol TEXT, dt TEXT, close REAL)")
    con.executemany("INSERT INTO candles VALUES (?,?,?)", [("A", f"2026-01-{i+1:02d}", 1.0) for i in range(candles)])
    for sql, rows in (extra or []):
        con.execute(sql)
        for r in rows:
            con.execute(f"INSERT INTO {sql.split()[2].split('(')[0]} VALUES ({','.join('?'*len(r))})", r)
    con.commit()
    con.close()


@pytest.fixture
def mirror(tmp_path, monkeypatch):
    local = tmp_path / "market_data.sqlite3"
    _db_file(local, candles=1, extra=[
        ("CREATE TABLE app_watchlists(id INTEGER, name TEXT)", [(1, "mine")]),
        ("CREATE TABLE dhan_token_cache(id INTEGER, access_token TEXT, issued_at TEXT)", [(1, "tok", "x")]),
    ])
    remote = tmp_path / "remote.sqlite3"
    _db_file(remote, candles=5)
    state = {"sha": "aaa", "downloads": 0}

    def download(url, dest, headers, params=None, timeout=120):
        state["downloads"] += 1
        assert params == {"ref": state["sha"]}
        with open(remote, "rb") as fin, gzip.open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        return 200, ""

    monkeypatch.setattr(core, "DATA_DB", str(local))
    monkeypatch.setattr(core, "_github_configured", lambda: True)
    monkeypatch.setattr(core, "latest_backup_commit", lambda: state["sha"])
    monkeypatch.setattr(core, "_download_to", download)
    return local, state


def test_refresh_downloads_only_when_the_backup_changed(mirror):
    local, state = mirror
    first = core.refresh_mirror_from_backup()
    assert first["changed"] and state["downloads"] == 1
    con = sqlite3.connect(local)
    assert con.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 5
    # The mirror's own tables survive the swap.
    assert con.execute("SELECT name FROM app_watchlists").fetchall() == [("mine",)]
    assert con.execute("SELECT access_token FROM dhan_token_cache").fetchall() == [("tok",)]
    con.close()

    again = core.refresh_mirror_from_backup()
    assert not again["changed"] and state["downloads"] == 1          # one small API call, no download

    state["sha"] = "bbb"
    assert core.refresh_mirror_from_backup()["changed"] and state["downloads"] == 2
    assert not list(local.parent.glob("*.mirror-tmp*"))                # nothing left behind


def test_an_empty_download_never_replaces_the_database(mirror, tmp_path, monkeypatch):
    local, state = mirror
    empty = tmp_path / "empty.sqlite3"
    _db_file(empty, candles=0)

    def download(url, dest, headers, params=None, timeout=120):
        with open(empty, "rb") as fin, gzip.open(dest, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        return 200, ""

    monkeypatch.setattr(core, "_download_to", download)
    res = core.refresh_mirror_from_backup()
    assert not res["changed"]
    con = sqlite3.connect(local)
    assert con.execute("SELECT COUNT(*) FROM candles").fetchone()[0] == 1
    con.close()


def test_a_read_only_mirror_never_writes_the_backup(monkeypatch):
    monkeypatch.setenv("BACKUP_READONLY", "1")
    monkeypatch.setattr(core, "_github_configured", lambda: True)
    monkeypatch.setattr(core, "_github_put_file", lambda *a, **k: pytest.fail("pushed"))
    ok, why = core.backup_learning_to_github(return_reason=True)
    assert not ok and "Read-only" in why
    ok, why = core.backup_db_to_github(return_reason=True)
    assert not ok and "Read-only" in why


def test_the_mirror_does_not_take_the_dhan_login_from_a_running_job(monkeypatch):
    monkeypatch.setenv("DHAN_YIELD_TO_JOBS", "1")
    monkeypatch.setattr(core, "_github_configured", lambda: True)
    monkeypatch.setattr(core, "_DHAN_JOB_CHECK", {"at": -1e9, "running": False})

    class R:
        def raise_for_status(self): pass
        def json(self): return {"workflow_runs": [{"path": ".github/workflows/daily-forward-test.yml"}]}

    monkeypatch.setattr(core.requests, "get", lambda *a, **k: R())
    assert core.dhan_job_running()
    monkeypatch.setattr(core, "_dhan_pin_totp_configured", lambda: True)
    monkeypatch.setattr(core, "_dhan_generate_fresh_token", lambda: pytest.fail("minted during a job"))
    assert core._dhan_renew_rejected_token("old") is False
    monkeypatch.setattr(core, "_read_cached_dhan_token", lambda: (None, None))
    with pytest.raises(RuntimeError, match="waits"):
        core._dhan_ensure_fresh_token()


def test_without_the_setting_nothing_yields(monkeypatch):
    monkeypatch.delenv("DHAN_YIELD_TO_JOBS", raising=False)
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: pytest.fail("asked GitHub"))
    assert core.dhan_job_running() is False
