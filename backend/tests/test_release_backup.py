"""The whole-database backup as a Release asset, and restoring the NEWER copy.

The asset exists because git rejects any file over 100 MB and the NSE Top 2000
store compresses past that. The newest-copy rule exists because the first
asset (20 Sep) was left behind while the scheduled jobs kept committing to the
branch for a week; "always prefer the asset" would have restored every host to
20 Sep and dropped a week of forward tests.
"""

from __future__ import annotations

import gzip
import sqlite3

import pytest

from app.engine import core


class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.text = "" if payload is None else str(payload)
        self._content = content

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _db_bytes(tmp_path, marker):
    path = tmp_path / f"{marker}.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE marker(name TEXT)")
    con.execute("INSERT INTO marker VALUES (?)", (marker,))
    con.commit()
    con.close()
    return gzip.compress(path.read_bytes())


@pytest.fixture
def github(monkeypatch, tmp_path):
    """A fake GitHub with one asset and one branch copy, each with a date."""
    state = {"asset_time": "2026-09-20T15:52:10Z", "branch_time": "2026-09-27T08:30:21Z",
             "asset": _db_bytes(tmp_path, "asset"), "branch": _db_bytes(tmp_path, "branch")}

    def get(url, headers=None, params=None, timeout=None, stream=False):
        if "/releases/tags/" in url:
            return _Resp(200, {"id": 7, "assets": [
                {"id": 99, "name": core.DB_BACKUP_ASSET, "updated_at": state["asset_time"]}]})
        if url.endswith("/commits"):
            return _Resp(200, [{"commit": {"committer": {"date": state["branch_time"]}}}])
        if "/releases/assets/99" in url:
            return _Resp(200, content=state["asset"])
        if "/contents/" in url and url.endswith(".gz"):
            return _Resp(200, content=state["branch"])
        return _Resp(404, {"message": "Not Found"})

    monkeypatch.setattr(core.requests, "get", get)
    monkeypatch.setattr(core, "_github_configured", lambda: True)
    monkeypatch.setattr(core, "_github_setting",
                        lambda n: {"GITHUB_REPO": "o/r", "GITHUB_TOKEN": "t",
                                   "GITHUB_BACKUP_BRANCH": "db-backup"}.get(n))
    live = tmp_path / "live.sqlite3"
    monkeypatch.setattr(core, "DATA_DB", str(live))
    return state, live


def _restored_marker(live):
    con = sqlite3.connect(live)
    try:
        return con.execute("SELECT name FROM marker").fetchone()[0]
    finally:
        con.close()


def test_an_older_asset_does_not_win_over_a_newer_branch_copy(github):
    state, live = github
    assert core.restore_db_from_github(force=True)
    assert _restored_marker(live) == "branch"


def test_a_newer_asset_is_restored(github):
    state, live = github
    state["asset_time"] = "2026-09-28T02:00:00Z"
    assert core.restore_db_from_github(force=True)
    assert _restored_marker(live) == "asset"


def test_the_asset_wins_when_the_branch_has_no_copy(github, monkeypatch):
    state, live = github
    real_get = core.requests.get
    monkeypatch.setattr(core.requests, "get",
                        lambda url, **k: _Resp(200, []) if url.endswith("/commits")
                        else real_get(url, **k))
    assert core.restore_db_from_github(force=True)
    assert _restored_marker(live) == "asset"


def test_upload_is_checked_against_what_github_stored(monkeypatch, tmp_path):
    packed = tmp_path / "db.gz"
    packed.write_bytes(b"x" * 1234)
    monkeypatch.setattr(core, "_github_setting", lambda n: "t")
    monkeypatch.setattr(core, "_github_release_backup_asset",
                        lambda repo: ({"id": 7}, {"id": 99}))
    deleted = []
    monkeypatch.setattr(core.requests, "delete", lambda url, **k: deleted.append(url))

    monkeypatch.setattr(core.requests, "post",
                        lambda url, **k: _Resp(201, {"size": 1234}))
    ok, why = core._github_upload_release_asset("o/r", str(packed))
    assert ok, why
    assert deleted and deleted[0].endswith("/releases/assets/99")

    monkeypatch.setattr(core.requests, "post",
                        lambda url, **k: _Resp(201, {"size": 10}))
    ok, why = core._github_upload_release_asset("o/r", str(packed))
    assert not ok and "1,234" in why
