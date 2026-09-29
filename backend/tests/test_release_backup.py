"""scripts/release_backup.py: the second copy of the database backup."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_backup.py"
spec = importlib.util.spec_from_file_location("release_backup", SCRIPT)
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)


def _fake_github(existing):
    calls = []
    assets = dict(existing)

    def call(method, url, token, data=None, content_type="application/json"):
        calls.append((method, url.split("?")[0].rsplit("/", 1)[-1] if method == "DELETE" else url))
        if method == "GET":
            return 200, {"upload_url": "https://uploads/x/assets{?name,label}",
                         "assets": [{"name": n, "id": i} for n, i in assets.items()]}
        if method == "DELETE":
            return 204, None
        name = url.split("name=")[1]
        return 201, {"name": name, "size": len(data)}

    return call, calls


def test_uploads_latest_and_dated_and_keeps_seven_days(tmp_path, monkeypatch):
    stage = tmp_path / "db.gz"
    stage.write_bytes(b"x" * 1000)
    old = {f"market_data-2026-09-{d:02d}.sqlite3.gz": 100 + d for d in range(10, 20)}
    old["market_data.sqlite3.gz"] = 1
    call, calls = _fake_github(old)
    monkeypatch.setattr(rb, "call", call)
    monkeypatch.setenv("BACKUP_STAGE_PATH", str(stage))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_PUSH_TOKEN", "t")
    assert rb.main() == 0
    posted = [u for m, u in calls if m == "POST"]
    assert any("name=market_data.sqlite3.gz" in u for u in posted)
    assert any("name=market_data-20" in u for u in posted)
    deleted = {u for m, u in calls if m == "DELETE"}
    assert "1" in deleted                       # the old "latest" is replaced
    # ten dated files plus today's: the four oldest go, seven remain
    assert {"110", "111", "112", "113"} <= deleted and "114" not in deleted


def test_a_short_upload_is_reported(tmp_path, monkeypatch):
    stage = tmp_path / "db.gz"
    stage.write_bytes(b"x" * 1000)
    call, _ = _fake_github({})

    def short(method, url, token, data=None, content_type="application/json"):
        if method == "POST":
            return 201, {"size": 10}
        return call(method, url, token, data, content_type)

    monkeypatch.setattr(rb, "call", short)
    monkeypatch.setenv("BACKUP_STAGE_PATH", str(stage))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_PUSH_TOKEN", "t")
    assert rb.main() == 1


def test_restore_falls_back_to_the_release_copy(tmp_path, monkeypatch):
    import gzip
    import sqlite3

    from app.engine import core

    src = tmp_path / "src.sqlite3"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE forward_tests(id INTEGER)")
    con.execute("INSERT INTO forward_tests VALUES (7)")
    con.commit()
    con.close()
    packed = gzip.compress(src.read_bytes())
    target = tmp_path / "live.sqlite3"
    urls = []

    def download(url, dest, headers, params=None, timeout=120):
        urls.append(url)
        if "releases/download/db-backup/market_data.sqlite3.gz" in url:
            Path(dest).write_bytes(packed)
            return 200, ""
        return 404, "Not Found"

    monkeypatch.setattr(core, "DATA_DB", str(target))
    monkeypatch.setattr(core, "_download_to", download)
    monkeypatch.setattr(core, "_github_configured", lambda: True)
    monkeypatch.setattr(core, "_github_setting", lambda n: "o/r" if n == "GITHUB_REPO" else "t")
    assert core.restore_db_from_github() is True
    assert "api.github.com" in urls[0] and "releases/download" in urls[-1]
    assert sqlite3.connect(target).execute("SELECT id FROM forward_tests").fetchone() == (7,)
