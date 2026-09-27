"""The two things that took the 512 MB API down, and the Dhan refusal behind them.

Render's event log showed the API OOM-killed within seconds of every
"Top up latest sessions": the sync finished by pushing the whole database to
GitHub, and that push held the 160 MB file about five times over. Meanwhile
Dhan was answering every request with DH-902 (no Data API subscription), which
a 500-symbol sync repeated 500 times and the smoke test reported as a
traceback. These pin the fixes.
"""

from __future__ import annotations

import io
import json
import os
import tempfile

import pytest

from app.engine import core


class _Resp:
    def __init__(self, status_code, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode(errors="replace")
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


DH902 = (b'{"errorType":"Invalid_Access","errorCode":"DH-902","errorMessage":'
         b'"HTTP Status 451. User has not subscribed to Data APIs"}')


# --------------------------------------------------------------- Dhan access
def test_dh902_raises_an_access_error_at_once(monkeypatch):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return _Resp(401, DH902)

    monkeypatch.setattr(core.requests, "post", post)
    monkeypatch.setattr(core, "_dhan_headers", lambda: {})
    with pytest.raises(core.DhanAccessError) as err:
        core._dhan_post("/charts/historical", {}, label="historical")
    assert len(calls) == 1, "an account-level refusal must not be retried"
    assert "Data API subscription" in str(err.value)
    # Still a RuntimeError, so every existing `except RuntimeError` keeps working.
    assert isinstance(err.value, RuntimeError)


def test_the_top_up_stops_at_the_first_account_refusal(monkeypatch):
    requested = []

    def refuse(symbol, start, end, refresh_tail_days=0):
        requested.append(symbol)
        raise core.DhanAccessError("DH-902: renew the Data API plan")

    monkeypatch.setattr(core, "update_dhan_symbol", refuse)
    summary = core.sync_latest_sessions([f"SYM{i}" for i in range(200)], max_workers=1)
    assert summary["aborted"].startswith("DH-902")
    assert len(requested) == 1, f"asked Dhan {len(requested)} times after it refused the account"


def test_the_smoke_test_reports_a_refusal_as_a_message(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(core, "dhan_configured", lambda: True)

    def refuse(symbol, days=30):
        raise core.DhanAccessError("DH-902: renew the Data API plan")

    monkeypatch.setattr(core, "dhan_historical_smoke_test", refuse)
    with TestClient(app) as client:
        r = client.post("/api/v1/data/smoke-test?symbol=RELIANCE&days=30")
    assert r.status_code == 502
    assert r.json() == {"error": {"code": "dhan_access",
                                  "message": "DH-902: renew the Data API plan"}}


# ---------------------------------------------------------- instrument master
_MASTER_CSV = (
    "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,"
    "SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,"
    "SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,"
    "SM_SYMBOL_NAME\n"
    "NSE,E,2885,EQUITY,,RELIANCE,1,Reliance Industries,,,,5,,ES,EQ,RELIANCE INDUSTRIES LTD\n"
    "NSE,E,11536,EQUITY,,TCS,1,Tata Consultancy,,,,5,,ES,EQ,TATA CONSULTANCY SERV LT\n"
    "BSE,E,500325,EQUITY,,RELIANCE,1,Reliance Industries,,,,5,,ES,A,RELIANCE INDUSTRIES LTD\n"
    "NSE,I,13,INDEX,,NIFTY,1,Nifty 50,,,,5,,INDEX,,NIFTY 50\n"
) + "".join(
    f"NSE,D,{50000 + i},OPTSTK,0,RELIANCE-Oct2026-{1000 + i}-CE,250,RELIANCE {1000 + i} CALL,"
    f"2026-10-29,{1000 + i},CE,5,M,OP,,RELIANCE\n"
    for i in range(500)
)


def test_the_master_keeps_only_what_the_app_reads(monkeypatch):
    core.dhan_master.clear()
    core.dhan_map.clear()
    monkeypatch.setattr(core.requests, "get",
                        lambda url, **k: _Resp(200, _MASTER_CSV.encode()))
    try:
        master = core.dhan_master()
        assert len(master) == 4, "derivative rows should be dropped at load"
        assert "SEM_STRIKE_PRICE" not in master.columns
        assert core.dhan_master() is master, "cached once, never copied per call"

        assert core.dhan_map()["RELIANCE"] == "2885"      # NSE cash, not BSE
        assert core.dhan_map()["TCS"] == "11536"
        assert "RELIANCE-Oct2026-1000-CE" not in core.dhan_map()
        assert str(core.dhan_index_map()["NIFTY"]) == "13"
    finally:
        core.dhan_master.clear()
        core.dhan_map.clear()


# -------------------------------------------------------------------- backup
@pytest.fixture()
def backup_env(monkeypatch, frames):
    path = os.path.join(tempfile.mkdtemp(prefix="ati-backup-"), "market_data.sqlite3")
    monkeypatch.setattr(core, "DATA_DB", path)
    con = core._db()
    try:
        for symbol, df in frames.items():
            core._save(con, symbol, df)
    finally:
        con.close()
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setattr(core, "_github_ensure_branch", lambda repo, branch: (True, ""))
    monkeypatch.setattr(core, "_LAST_BACKUP_RATIO", None)
    return path


def test_an_oversized_backup_is_declined_before_anything_is_sent(monkeypatch, backup_env):
    sent = []
    monkeypatch.setattr(core, "GITHUB_CONTENTS_MAX_BYTES", 1)
    monkeypatch.setattr(core.requests, "put", lambda *a, **k: sent.append(1) or _Resp(201))
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: _Resp(404))

    ok, reason = core.backup_db_to_github(return_reason=True)
    assert not ok and not sent
    assert "scheduled GitHub Actions" in reason

    # The second attempt knows the ratio and does not rebuild the archive.
    monkeypatch.setattr(core, "_snapshot_db", lambda dest: pytest.fail("rebuilt the snapshot"))
    ok, reason = core.backup_db_to_github(return_reason=True)
    assert not ok and "would be about" in reason


def test_the_upload_is_streamed_from_a_file(monkeypatch, backup_env):
    bodies = []

    def put(url, headers=None, json=None, data=None, timeout=None):
        assert json is None, "the body must not be built in memory"
        assert hasattr(data, "read"), "the body must be a file requests can stream"
        bodies.append(data.read())
        return _Resp(201)

    monkeypatch.setattr(core.requests, "put", put)
    monkeypatch.setattr(core.requests, "get", lambda *a, **k: _Resp(404))
    ok, reason = core.backup_db_to_github(return_reason=True)
    assert ok, reason

    import base64
    import gzip
    import sqlite3

    body = json.loads(bodies[0])
    restored = os.path.join(os.path.dirname(backup_env), "roundtrip.sqlite3")
    with open(restored, "wb") as f:
        f.write(gzip.decompress(base64.b64decode(body["content"])))
    con = sqlite3.connect(restored)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("SELECT COUNT(*) FROM candles").fetchone()[0] > 0
    finally:
        con.close()
