"""The Oracle 4h trend paper book: breakout -> market entry -> stop or exit."""

import json

import numpy as np
import pandas as pd
import pytest

from app.tasks import trend_paper as tp


@pytest.fixture(autouse=True)
def no_forex_book(monkeypatch):
    """No network in tests: the forex relay sees an unreachable book."""
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(tp.requests, "get", boom)


def _frames():
    # 400 days of a steady uptrend, then a flat 4h range, then a breakout
    idx15 = pd.date_range("2025-01-01", periods=400 * 96, freq="15min", tz="UTC")
    base = np.linspace(100, 200, len(idx15))
    flat = len(idx15) - 30 * 96
    base[flat:] = 200.0
    m15 = pd.DataFrame({"open": base, "high": base + 0.5, "low": base - 0.5, "close": base}, index=idx15)
    # breakout bar: a 4h block closing well above the range
    b = len(idx15) - 5 * 96
    m15.iloc[b:b + 16, :] = [[210, 211, 209, 210]] * 16
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return m15, m15.resample("4h").agg(agg), m15.resample("1D").agg(agg), b


def test_breakout_buys_at_the_next_open_then_stops():
    m15, h4, d1, b = _frames()
    ind = tp.indicators(d1, h4)
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    events = tp.advance(st, ind, m15.iloc[:b + 16], "BTCUSDT")
    assert st["status"] == "enter_next" and any("BREAKOUT" in e for e in events)
    # the next 15m bar: bought at its open, stop 1.5 ATR below, sized for 1% risk
    tp.advance(st, ind, m15.iloc[:b + 17], "BTCUSDT")
    assert st["status"] == "long" and st["entry"] == m15.iloc[b + 16].open
    assert abs((st["entry"] - st["stop"]) - tp.STOP_ATR * st["atr"]) < 1e-9
    assert st["size_x"] == min(round(0.01 / ((st["entry"] - st["stop"]) / st["entry"]), 3), tp.MAX_POSITION_X)
    # then falls through the stop: closed at a loss of a little over 1R
    m15.loc[m15.index[b + 17]] = [199, 199, 150, 151]
    tp.advance(st, ind, m15.iloc[:b + 18], "BTCUSDT")
    assert st["status"] == "flat"
    assert -1.2 < st["closed"][-1]["r"] < -1.0


def test_no_daily_trend_filter():
    # a breakout after a long fall still triggers: step 14 dropped the 200-day filter
    m15, h4, d1, b = _frames()
    m15[["open", "high", "low", "close"]] = m15[["open", "high", "low", "close"]].iloc[::-1].to_numpy()
    m15.iloc[b:b + 16, :] = [[260, 261, 259, 260]] * 16
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    tp.advance(st, tp.indicators(m15.resample("1D").agg(agg), m15.resample("4h").agg(agg)),
               m15.iloc[:b + 16], "BTCUSDT")
    assert st["status"] == "enter_next"


def test_order_from_old_rules_is_cancelled():
    m15, h4, d1, b = _frames()
    st = {"last15": str(m15.index[b - 2]), "status": "awaiting_retest", "level": 1.0, "atr": 1.0}
    ev = tp.advance(st, tp.indicators(d1, h4), m15.iloc[:b], "BTCUSDT")
    assert st["status"] == "flat" and "cancelled" in ev[0]


def test_breakout_alert_names_the_order():
    m15, h4, d1, b = _frames()
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    ev = [e for e in tp.advance(st, tp.indicators(d1, h4), m15.iloc[:b + 16], "BTCUSDT") if "BREAKOUT" in e][0]
    title, body, urgent = tp.alert_text("BTCUSDT", ev, st, 10_000.0)
    assert urgent and title.startswith("BTC: BUY NOW at market")
    assert "STOP-LOSS" in body and "Rs 100 (1%)" in body


def test_run_sends_alerts_and_never_fails_on_them(monkeypatch, tmp_path):
    m15, h4, d1, b = _frames()
    sent = []
    monkeypatch.setattr(tp, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(tp, "SYMBOLS", ("BTCUSDT",))
    monkeypatch.setattr(tp, "notify", lambda topic, title, body, high=False: sent.append(title) or True)
    monkeypatch.setattr(tp, "fetch", lambda sym: (d1, h4, m15.iloc[:b + 16], "test"))
    tp.run()                                    # first run: creates the topic and says hello
    assert sent[0] == "ATI trend alerts connected"
    assert (tmp_path / "trend.html").read_text().count("ati-trend-") == 1


def test_new_rules_restart_the_book_and_keep_the_topic(monkeypatch, tmp_path):
    m15, h4, d1, b = _frames()
    old = {"start": "2026-10-04T07:00+00:00", "ntfy_topic": "ati-trend-abc", "events": ["x"],
           "markets": {"EURUSD": {"status": "long", "closed": [{"r": -1.0}]}}}
    (tmp_path / "trend-state.json").write_text(json.dumps(old))
    sent = []
    monkeypatch.setattr(tp, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(tp, "SYMBOLS", ("BTCUSDT",))
    monkeypatch.setattr(tp, "notify", lambda topic, title, body, high=False: sent.append((topic, title)) or True)
    monkeypatch.setattr(tp, "fetch", lambda sym: (d1, h4, m15.iloc[:b + 16], "test"))
    tp.run()
    book = json.loads((tmp_path / "trend-state.json").read_text())
    assert book["rules"] == tp.RULES and book["ntfy_topic"] == "ati-trend-abc"
    assert list(book["markets"]) == ["BTCUSDT"]
    assert sent[0] == ("ati-trend-abc", "Trend book: new rules")
    assert len(list(tmp_path.glob("trend-state-before-*.json"))) == 1
    tp.run()                                    # same rules: kept, no second restart
    assert len(list(tmp_path.glob("trend-state-before-*.json"))) == 1
    btc = json.loads((tmp_path / "trend-latest.json").read_text())["markets"]["BTCUSDT"]
    assert btc["buy_above"] == h4.high.iloc[-tp.N_IN:].max() and btc["price"] == m15.close.iloc[b + 15]


FX_STATE = {"pending": [{"id": "GBPUSD|x", "symbol": "GBPUSD", "direction": 1, "entry": 1.25, "stop": 1.248,
                         "tp1": 1.256, "tp2": 1.26, "rr1": 3.0, "score": 70,
                         "expires": "2026-10-06T16:00:00+00:00"}],
            "trades": {"EURUSD|t": {"symbol": "EURUSD", "direction": -1, "entry": 1.1195, "stop": 1.1203,
                                    "tp1": 1.1171, "tp2": 1.1162, "entry_time": "2026-10-05 14:00:00+00:00",
                                    "status": "closed", "outcome": "stop", "r": -1.04}}}


def test_forex_relay_sends_each_event_once(monkeypatch):
    sent = []
    monkeypatch.setattr(tp.requests, "get", lambda *a, **k: type("R", (), {"json": lambda self: FX_STATE})())
    monkeypatch.setattr(tp, "notify", lambda topic, title, body, high=False: sent.append((title, high)) or True)
    book = {}
    tp.relay_fx(book, "t")
    assert sent[0][0] == "Forex alerts connected"
    assert ("GBPUSD: BUY LIMIT 1.25", True) in sent
    assert ("EURUSD: forex trade closed -1.04R", False) in sent
    n = len(sent)
    tp.relay_fx(book, "t")                      # nothing new: nothing sent
    assert len(sent) == n


def test_forex_relay_survives_an_unreachable_book():
    book = {}
    tp.relay_fx(book, "t")                      # the autouse fixture makes the fetch fail
    assert "fx_seen" not in book


def test_live_prices_endpoint(monkeypatch):
    from app.api.v1.endpoints import crypto_routes as cr

    def price(sym):
        if sym == "SOLUSDT":
            raise RuntimeError("all sources down")
        return 100.0, "test"
    monkeypatch.setattr(tp, "live_price", price)
    cr._live_cache.clear()
    out = cr.get_live_prices()
    assert out["BTCUSDT"]["price"] == 100.0 and "error" in out["SOLUSDT"]
    assert set(out) == set(tp.SYMBOLS)
