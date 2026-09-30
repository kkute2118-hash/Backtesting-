"""The interactive chart's data: pages of candles per timeframe, the shared
live quote and its event stream."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ApiError, NotFound
from app.engine import core
from app.services import charting


@pytest.fixture(autouse=True)
def _fresh_cache():
    charting.clear_cache()
    yield
    charting.clear_cache()


# ----------------------------------------------------------------- daily
def test_daily_pages_walk_back_without_gaps_or_overlap(seeded_db, monkeypatch):
    monkeypatch.setitem(charting.DAILY_PAGE_BARS, "1D", 100)
    first = charting.candles("TRENDUP", "1D")
    assert len(first["candles"]) == 100 and first["has_more"]
    times = [c["time"] for c in first["candles"]]
    assert times == sorted(times)
    second = charting.candles("TRENDUP", "1D", before=first["next_before"])
    assert second["candles"][-1]["time"] < times[0]              # strictly older, no overlap
    # a daily bar is stamped at midnight of its date, read as UTC
    assert all(t % 86_400 == 0 for t in times)


def test_weekly_bars_are_built_from_the_daily_ones(seeded_db, frames):
    daily = frames["TRENDUP"]
    weekly = charting.candles("TRENDUP", "1W")["candles"]
    last_week = daily[daily.index.to_period("W-FRI") == daily.index[-1].to_period("W-FRI")]
    w = weekly[-1]
    assert w["open"] == round(float(last_week.open.iloc[0]), 2)
    assert w["high"] == round(float(last_week.high.max()), 2)
    assert w["close"] == round(float(last_week.close.iloc[-1]), 2)
    assert w["volume"] == pytest.approx(float(last_week.volume.sum()))
    assert pd.Timestamp(w["time"], unit="s").date() == last_week.index[0].date()


def test_bad_requests_are_explained(seeded_db):
    with pytest.raises(NotFound):
        charting.candles("NOSUCHSTOCK", "1D")
    with pytest.raises(NotFound):
        charting.candles("../etc", "1D")
    with pytest.raises(ApiError, match="Unsupported timeframe"):
        charting.candles("TRENDUP", "2m")
    with pytest.raises(ApiError, match="Unsupported timeframe"):
        charting.candles("TRENDUP", "1m")                        # dropped to keep the server light


def test_intraday_needs_the_dhan_feed(seeded_db, monkeypatch):
    monkeypatch.setattr(core, "dhan_configured", lambda: False)
    with pytest.raises(ApiError) as err:
        charting.candles("TRENDUP", "15m")
    assert err.value.status_code == 503 and "Daily" in err.value.message
    assert charting.available_timeframes() == ["1D", "1W"]


# -------------------------------------------------------------- intraday
def _session(day: str, minutes: int) -> pd.DataFrame:
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq=f"{minutes}min")
    base = np.arange(len(idx), dtype=float) + 100
    return pd.DataFrame({"open": base, "high": base + 1, "low": base - 1, "close": base + 0.5,
                         "volume": 10.0}, index=idx)


@pytest.fixture
def fake_dhan(seeded_db, monkeypatch):
    calls = []

    def fetch(sym, interval, start, end):
        calls.append((sym, interval, start, end))
        days = pd.bdate_range(start.date(), end.date())
        frames = [_session(str(d.date()), int(interval)) for d in days]
        return pd.concat(frames) if frames else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    monkeypatch.setattr(core, "dhan_configured", lambda: True)
    monkeypatch.setattr(core, "market_now", lambda now=None: pd.Timestamp("2026-09-25 16:00").to_pydatetime())
    monkeypatch.setattr(charting, "dhan_intraday", fetch)
    return calls


def test_fifteen_minute_bars_keep_india_time(fake_dhan):
    out = charting.candles("TRENDUP", "15m")
    day = [c for c in out["candles"] if pd.Timestamp(c["time"], unit="s").date() == pd.Timestamp("2026-09-25").date()]
    first = pd.Timestamp(day[0]["time"], unit="s")
    assert (first.hour, first.minute) == (9, 15)                  # India time on the axis
    assert len(day) == 25                                         # 09:15 ... 15:15
    assert fake_dhan[0][1] == "15"


def test_intraday_pages_are_cached_and_walk_back(fake_dhan):
    first = charting.candles("TRENDUP", "1H")
    charting.candles("TRENDUP", "1H")
    assert len(fake_dhan) == 1                                    # the second view is served from memory
    assert first["has_more"] and first["next_before"]
    older = charting.candles("TRENDUP", "1H", before=first["next_before"])
    assert older["candles"][-1]["time"] < first["candles"][0]["time"]


# ------------------------------------------------------------------ live
def test_live_falls_back_to_the_stored_close(seeded_db, frames, monkeypatch):
    monkeypatch.setattr(core, "dhan_configured", lambda: False)
    q = charting.live("TRENDUP")
    assert q["source"] == "STORED CLOSE"
    assert q["ltp"] == pytest.approx(float(frames["TRENDUP"].close.iloc[-1]))
    assert q["change_pct"] is not None


def test_one_dhan_quote_serves_every_viewer(seeded_db, monkeypatch):
    calls = []
    monkeypatch.setattr(core, "dhan_configured", lambda: True)
    monkeypatch.setattr(core, "nse_market_is_open", lambda *a, **k: True)

    def snap(symbols):
        calls.append(symbols)
        return {"TRENDUP": {"ltp": 123.4, "open": 120.0, "high": 125.0, "low": 119.0,
                            "prev_close": 121.0, "volume": 5e5, "ts": "2026-09-25T10:00:00"}}

    monkeypatch.setattr(core, "dhan_quote_snapshot", snap)
    a, b = charting.live("TRENDUP"), charting.live("TRENDUP")
    assert len(calls) == 1 and a == b
    assert a["source"] == "LIVE" and a["change"] == pytest.approx(2.4)


def test_live_route_and_no_stream(client):
    r = client.get("/api/v1/stocks/TRENDUP/live")
    assert r.status_code == 200 and r.json()["ltp"] > 0
    assert client.get("/api/v1/stocks/TRENDUP/stream").status_code == 404


def test_candles_route(client):
    r = client.get("/api/v1/stocks/TRENDUP/candles", params={"tf": "1W"})
    assert r.status_code == 200 and r.json()["candles"]
    assert client.get("/api/v1/stocks/NOPE/candles").status_code == 404


def test_a_pre_open_quote_never_shows_zero_prices(seeded_db, monkeypatch):
    monkeypatch.setattr(core, "dhan_configured", lambda: True)
    monkeypatch.setattr(core, "nse_market_is_open", lambda *a, **k: False)
    monkeypatch.setattr(core, "dhan_quote_snapshot", lambda s: {"TRENDUP": {
        "ltp": 123.4, "open": 123.4, "high": 0.0, "low": 0.0, "prev_close": 121.0,
        "volume": 0.0, "ts": "2026-09-30T09:00:00"}})
    q = charting.live("TRENDUP")
    assert q["high"] is None and q["low"] is None and q["open"] == 123.4
