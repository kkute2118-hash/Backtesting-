"""Front-test scorecard: crypto long/short split, forex from fx-paper, verdicts."""

import json

import pytest

from app.services import front_test as F
from app.tasks import trend_paper


@pytest.fixture
def books(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_paper, "REPORT_DIR", tmp_path)
    (tmp_path / "trend-state.json").write_text(json.dumps({"start": "2026-10-14T18:00+00:00", "markets": {
        "BTCUSDT": {"status": "short", "closed": [
            {"symbol": "BTCUSDT", "side": "long", "entry_time": "a", "exit_time": "2026-10-20", "r": 2.0},
            {"symbol": "BTCUSDT", "side": "short", "entry_time": "b", "exit_time": "2026-10-22", "r": -1.0}]},
        "XAUUSDT": {"status": "long", "closed": []}}}))
    fx = {"updated": "x", "pending": [{}], "trades": {
        "a": {"symbol": "EURUSD", "direction": -1, "status": "closed", "entry_time": "2026-10-05", "r": -1.038},
        "b": {"symbol": "AUDUSD", "direction": -1, "status": "closed", "entry_time": "2026-10-08", "r": -1.232},
        "c": {"symbol": "USDJPY", "direction": 1, "status": "open", "entry_time": "2026-10-15", "r": 0}}}
    monkeypatch.setattr(F, "_fx_cache", (1e18, fx))
    monkeypatch.setattr(F, "_nse_rows", lambda: [])


def test_scorecard_rows(books):
    out = F.scorecard()
    rows = {r["id"]: r for r in out["rows"]}
    assert out["errors"] == {}
    assert rows["trend_long"]["closed"] == 1 and rows["trend_long"]["total_r"] == 2.0
    assert rows["trend_long"]["open"] == 1 and rows["trend_short"]["open"] == 1
    assert rows["trend_short"]["avg_r"] == -1.0 and rows["trend_short"]["pnl_rs"] < 0
    fx = rows["fx_b"]
    assert (fx["closed"], fx["open"], fx["pending"], fx["since"]) == (2, 1, 1, "2026-10-05")
    assert fx["total_r"] == -2.27 and fx["pnl_rs"] == -227
    assert fx["verdict"].startswith("Too early")
    assert [t["symbol"] for t in out["recent_trades"]][:2] == ["BTCUSDT", "BTCUSDT"]


def test_verdicts():
    assert F.verdict(5, 1.0, 0.3).startswith("Too early")
    assert F.verdict(25, -0.1, 0.3) == "Losing: review"
    assert F.verdict(25, 0.1, 0.3) == "Below backtest"
    assert F.verdict(25, 0.3, 0.3) == "On track"


def test_nse_rows(tmp_path, monkeypatch):
    from app.engine import core
    monkeypatch.setattr(core, "DATA_DB", str(tmp_path / "t.db"))
    con = core._db()
    con.executemany("INSERT INTO forward_tests(symbol,strategy,status,result_r,signal_date) VALUES (?,?,?,?,?)",
                    [("A", "S6", "TARGET", 3.0, "2026-09-01"), ("B", "S6", "STOP", -1.0, "2026-09-05"),
                     ("C", "S6", "ACTIVE", None, "2026-10-01"), ("D", "S5", "ACTIVE", None, "2026-10-02")])
    con.commit()
    con.close()
    rows = {r["strategy"]: r for r in F._nse_rows()}
    assert (rows["S6"]["closed"], rows["S6"]["open"], rows["S6"]["avg_r"]) == (2, 1, 1.0)
    assert rows["S6"]["since"] == "2026-09-01" and rows["S5"]["closed"] == 0
