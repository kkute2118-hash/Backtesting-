"""NSE Top 2000: never more than NSE_TOP_N shares stored for it, and market
breadth measured on the Nifty 500 whatever else the store holds."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.engine import core

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import daily_job  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA_DB", str(tmp_path / "top2000.sqlite3"))
    monkeypatch.setattr(core, "_S6_BREADTH", {"at": 0.0, "series": None})
    return tmp_path


def _put(symbols, days=80, value=lambda s: 1.0, breakout=()):
    con = core._db()
    end = date(2026, 9, 25)
    rows = []
    for sym in symbols:
        for k in range(days):
            dt = (end - timedelta(days=days - 1 - k)).isoformat()
            px = 100.0 + (50 if (sym in breakout and k == days - 1) else 0)
            rows.append((sym, dt, px, px, px, px, 1000.0 * value(sym)))
    con.executemany("INSERT OR REPLACE INTO candles(symbol, dt, open, high, low, close, volume) "
                    "VALUES(?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _stored():
    con = core._db()
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles")}
    finally:
        con.close()


def test_the_build_keeps_only_the_most_liquid(store, monkeypatch):
    candidates = [f"S{i:02d}" for i in range(12)]
    monkeypatch.setattr(core, "NSE_TOP_N", 5)
    monkeypatch.setattr(core, "dhan_configured", lambda: True)
    monkeypatch.setattr(core, "dhan_equity_symbols", lambda: candidates)
    monkeypatch.setattr(core, "market_today", lambda: date(2026, 9, 26))
    monkeypatch.setattr(core, "breadth_members", lambda: [])
    fetched = []

    def download(tickers, start, end, **_):            # liquidity = the number in the name
        fetched.extend(tickers)
        _put([t.replace(".NS", "") for t in tickers], value=lambda s: int(s[1:]) + 1)

    monkeypatch.setattr(core, "download_prices", download)
    _put(["^NSEI"])                                     # an index is never pruned
    top = daily_job._build_top2000(date(2026, 9, 25), {})
    assert len(fetched) == 12                           # every candidate ranked once
    assert top == [f"S{i:02d}.NS" for i in range(7, 12)]
    dropped = daily_job._prune_outside(top)
    assert len(dropped) == 7
    assert _stored() == {f"S{i:02d}" for i in range(7, 12)} | {"^NSEI"}
    # and a download never asks for more than the top N again
    assert len(core.resolve_universe(core.FULL_NSE_UNIVERSE, purpose="download")) == 5


def test_prune_keeps_the_breadth_universe(store, monkeypatch):
    _put(["AAA", "BBB", "CCC"])
    monkeypatch.setattr(core, "breadth_members", lambda: ["BBB"])
    assert sorted(daily_job._prune_outside(["AAA.NS"])) == ["CCC"]
    assert _stored() == {"AAA", "BBB"}


def test_breadth_ignores_shares_outside_the_nifty_500(store, monkeypatch):
    _put(["IN1", "IN2", "OUT1", "OUT2"], days=70, breakout=("OUT1", "OUT2"))
    monkeypatch.setattr(core, "breadth_members", lambda: ["IN1", "IN2"])
    assert core.market_breakout_breadth(force=True).iloc[-1] == 0.0
    monkeypatch.setattr(core, "breadth_members", lambda: [])          # no list stored yet
    assert core.market_breakout_breadth(force=True).iloc[-1] == pytest.approx(0.5)


def test_daily_top_up_follows_the_built_top_2000(store, monkeypatch):
    monkeypatch.setattr(daily_job, "TOP2000_BUILT_AT", 3)
    _put(["A", "B"], days=2)
    assert daily_job._sync_universes(["Nifty 500"]) == ["Nifty 500"]
    _put(["C"], days=2)
    assert daily_job._sync_universes(["Nifty 500"]) == ["Nifty 500", core.FULL_NSE_UNIVERSE]


def test_the_web_app_offers_all_six_strategies(client):
    ids = [s["id"] for s in client.get("/api/v1/config").json()["strategies"]]
    assert ids == [1, 2, 3, 4, 5, 6]


def test_overview_carries_market_breadth(seeded_db, client):
    b = client.get("/api/v1/market/overview").json()["market_breadth"]
    assert b["threshold"] == core.S6_MIN_BREADTH
    assert b["gated_strategies"] == ["S1", "S2", "S3", "S6"]
    assert b["ready"] is True and b["history"]


def test_new_index_members_get_their_history(store, monkeypatch):
    _put(["OLD"], days=300)
    _put(["NEWMEMBER"], days=7)
    asked = []
    monkeypatch.setattr(core, "download_prices", lambda tickers, start, end, **_: asked.extend(tickers))
    got = daily_job._backfill_short_history(["OLD.NS", "NEWMEMBER.NS", "NEVERSEEN.NS"], date(2026, 9, 29))
    assert got == ["NEVERSEEN.NS", "NEWMEMBER.NS"] and asked == got
