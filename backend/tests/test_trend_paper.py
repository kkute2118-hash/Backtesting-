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
    monkeypatch.setattr(tp.requests, "post", boom)
    monkeypatch.delenv("GH_BACKUP_TOKEN", raising=False)
    monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)


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


def test_test_alert_once_and_delivery_log(monkeypatch, tmp_path):
    m15, h4, d1, b = _frames()
    book = {"start": "2026-10-05T05:51+00:00", "rules": tp.RULES, "ntfy_topic": "ati-trend-abcd1234",
            "markets": {}, "events": []}
    (tmp_path / "trend-state.json").write_text(json.dumps(book))
    posts = []

    def post(url, data=None, timeout=None, headers=None):
        posts.append((url, headers["Title"]))
        return type("R", (), {"ok": True, "status_code": 200})()
    monkeypatch.setattr(tp.requests, "post", post)
    monkeypatch.setattr(tp, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(tp, "SYMBOLS", ("BTCUSDT",))
    monkeypatch.setattr(tp, "fetch", lambda sym: (d1, h4, m15.iloc[:b], "test"))
    tp.run()
    assert posts == [("https://ntfy.sh/ati-trend-abcd1234", "ATI test alert: phone alerts work")]
    tp.run()                                    # sent once per TEST_ALERT value
    assert len(posts) == 1
    latest = json.loads((tmp_path / "trend-latest.json").read_text())
    assert latest["alerts"]["topic_ends_with"] == "1234"
    assert latest["alerts"]["log"][0]["ok"] and "abcd" not in json.dumps(latest)


class _Resp:
    def __init__(self, code=200, data=None):
        self.status_code, self._data, self.text = code, data or {}, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(self.status_code)


def test_keep_fx_running_starts_the_workflow_once_and_reports(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_BACKUP_TOKEN", "t0ken")
    monkeypatch.setattr(tp.requests, "get", lambda url, **k: calls.append(("get", k["params"]["status"])) or _Resp(data={"total_count": 0}))
    monkeypatch.setattr(tp.requests, "post", lambda url, **k: calls.append(("post", k["json"])) or _Resp(204))
    book = {}
    mon = pd.Timestamp("2026-10-12 06:00", tz="UTC")
    tp.keep_fx_running(book, mon)
    assert book["fx_dispatch"]["status"] == "started"
    assert ("post", {"ref": "main", "inputs": {"loop": "true"}}) in calls
    n = len(calls)
    tp.keep_fx_running(book, mon + pd.Timedelta(minutes=10))     # within 30 minutes: no new check
    assert len(calls) == n
    tp.keep_fx_running(book, pd.Timestamp("2026-10-11 06:00", tz="UTC"))   # Sunday: nothing
    tp.keep_fx_running(book, pd.Timestamp("2026-10-12 20:00", tz="UTC"))   # after hours: nothing
    assert len(calls) == n


def test_keep_fx_running_leaves_a_running_job_and_reports_refusals(monkeypatch):
    monkeypatch.setenv("GH_BACKUP_TOKEN", "t0ken")
    monkeypatch.setattr(tp.requests, "get", lambda url, **k: _Resp(data={"total_count": 1}))
    book = {}
    tp.keep_fx_running(book, pd.Timestamp("2026-10-12 06:00", tz="UTC"))
    assert book["fx_dispatch"]["status"] == "running"
    monkeypatch.setattr(tp.requests, "get", lambda url, **k: _Resp(data={"total_count": 0}))
    monkeypatch.setattr(tp.requests, "post", lambda url, **k: _Resp(403))
    book = {}
    tp.keep_fx_running(book, pd.Timestamp("2026-10-12 06:00", tz="UTC"))
    assert book["fx_dispatch"]["status"].startswith("refused 403")
    assert "t0ken" not in json.dumps(book)


def _falling():
    """A long decline (below the 100-day average), then a 4h breakdown."""
    m15, h4, d1, b = _frames()
    m15[["open", "high", "low", "close"]] = m15[["open", "high", "low", "close"]].iloc[::-1].to_numpy()
    m15.iloc[b:b + 16, :] = [[90, 91, 89, 90]] * 16
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    return m15, m15.resample("4h").agg(agg), m15.resample("1D").agg(agg), b


def test_short_breakdown_in_a_downtrend_then_stop():
    m15, h4, d1, b = _falling()
    ind = tp.indicators(d1, h4)
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    ev = tp.advance(st, ind, m15.iloc[:b + 16], "BTCUSDT")
    assert st["status"] == "enter_short_next" and any("BREAKDOWN" in e for e in ev)
    title, body, urgent = tp.alert_text("BTCUSDT", [e for e in ev if "BREAKDOWN" in e][0], st, 10_000.0)
    assert urgent and title.startswith("BTC: SELL SHORT NOW") and "above)" in body
    tp.advance(st, ind, m15.iloc[:b + 17], "BTCUSDT")
    assert st["status"] == "short" and st["stop"] > st["entry"]
    m15.loc[m15.index[b + 17]] = [89, 120, 88, 119]          # rallies through the stop
    tp.advance(st, ind, m15.iloc[:b + 18], "BTCUSDT")
    t = st["closed"][-1]
    assert st["status"] == "flat" and t["side"] == "short" and -1.2 < t["r"] < -1.0


def test_no_short_on_gold_or_above_the_average():
    m15, h4, d1, b = _falling()
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    tp.advance(st, tp.indicators(d1, h4), m15.iloc[:b + 16], "XAUUSDT")
    assert st["status"] == "flat"                              # gold: long only
    ind = tp.indicators(d1, h4)
    ind["down"] = False                                        # above the 100-day average
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    tp.advance(st, ind, m15.iloc[:b + 16], "BTCUSDT")
    assert st["status"] == "flat"


def test_short_profit_is_positive_r():
    st = {"status": "short", "entry": 100.0, "stop": 103.0, "entry_time": "x", "held15": 0, "size_x": 1.0}
    ev = []
    tp._close(st, 94.0, pd.Timestamp("2026-10-14", tz="UTC"), "trend exit", ev, "ETHUSDT")
    assert st["closed"][-1]["r"] > 1.9 and "COVERED" in ev[0]
