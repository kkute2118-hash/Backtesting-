"""Yahoo Finance as the backup candle source when Dhan refuses."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.engine import core

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # daily_job.py at the repository root


def _chart(days, close0=100.0):
    ts = [int(pd.Timestamp(d).tz_localize("Asia/Kolkata").replace(hour=9, minute=15).timestamp()) for d in days]
    n = len(days)
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{
        "open": [close0 + i for i in range(n)], "high": [close0 + i + 2 for i in range(n)],
        "low": [close0 + i - 2 for i in range(n)], "close": [close0 + i + 1 for i in range(n)],
        "volume": [1000 + i for i in range(n)]}]}}]}}


class _R:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def test_yahoo_daily_parses_ist_dates(monkeypatch):
    days = [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)]
    seen = {}
    monkeypatch.setattr(core.requests, "get", lambda url, **k: seen.update(url=url) or _R(_chart(days)))
    df = core.yahoo_daily("M&M", days[0], days[-1])
    assert seen["url"].endswith("M%26M.NS")
    assert [d.date() for d in df.index] == days
    assert df.iloc[-1].close == 103.0 and df.iloc[-1].volume == 1002


def test_yahoo_sync_stores_completed_sessions_only(monkeypatch):
    end = core.latest_completed_nse_session()
    days = [end - timedelta(days=1), end, end + timedelta(days=1)]     # the last one is not complete
    monkeypatch.setattr(core.requests, "get", lambda url, **k: _R(_chart(days)))
    out = core.sync_latest_sessions_yahoo(["ZZYAHOO.NS"], tail_days=5)
    assert out["source"] == "yahoo" and out["advanced"] == 1 and out["latest"] == str(end)
    con = core._db()
    try:
        dts = [r[0] for r in con.execute("SELECT dt FROM candles WHERE symbol='ZZYAHOO' ORDER BY dt")]
    finally:
        con.close()
    assert dts[-1] == str(end) and str(end + timedelta(days=1)) not in dts


def test_yahoo_errors_never_raise(monkeypatch):
    def boom(*a, **k):
        raise OSError("blocked")
    monkeypatch.setattr(core.requests, "get", boom)
    out = core.sync_latest_sessions_yahoo(["ZZERR"], tail_days=5)
    assert out["advanced"] == 0 and out["errors"] and "OSError" in out["errors"][0]


def test_daily_job_continues_without_dhan(monkeypatch):
    import daily_job
    monkeypatch.setattr(core, "_dhan_pin_totp_configured", lambda: True)
    monkeypatch.setattr(core, "_dhan_generate_fresh_token", lambda: (_ for _ in ()).throw(RuntimeError("Invalid TOTP")))
    monkeypatch.setattr(core, "_read_cached_dhan_token", lambda: (None, None))
    assert daily_job.step_token(force=True) is None          # no Dhan: carry on
    calls = []
    monkeypatch.setattr(core, "sync_latest_sessions_yahoo",
                        lambda t, tail_days: calls.append(t) or {"advanced": 1, "symbols": 1, "latest": "x", "errors": []})
    monkeypatch.setattr(daily_job, "step_sync", lambda *a: pytest.fail("Dhan must not be asked"))
    daily_job.step_sync_with_fallback(["A.NS"], 5, None)
    assert calls == [["A.NS"]]
    monkeypatch.setenv("DATA_FALLBACK", "off")
    with pytest.raises(RuntimeError):
        daily_job.step_token(force=True)


def test_dhan_behind_tops_up_from_yahoo(monkeypatch):
    import daily_job
    monkeypatch.setattr(daily_job, "step_sync", lambda t, d: {"advanced": 0})
    monkeypatch.setattr(core, "data_freshness_status", lambda t: {"current": False, "awaiting_publication": False, "latest": "2026-10-09"})
    calls = []
    monkeypatch.setattr(core, "sync_latest_sessions_yahoo",
                        lambda t, tail_days: calls.append(1) or {"advanced": 5, "symbols": 5, "latest": "2026-10-12", "errors": []})
    daily_job.step_sync_with_fallback(["A.NS"], 5, True)
    assert calls == [1]
    monkeypatch.setattr(core, "data_freshness_status", lambda t: {"current": True, "awaiting_publication": False, "latest": "2026-10-12"})
    daily_job.step_sync_with_fallback(["A.NS"], 5, True)
    assert calls == [1]                                       # Dhan current: Yahoo not used
