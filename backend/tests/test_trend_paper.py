"""The Oracle 4h trend paper book: breakout -> resting limit -> fill -> stop."""

import numpy as np
import pandas as pd

from app.tasks import trend_paper as tp


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
    # the next 15m bar: bought at its open, stop 2 ATR below
    tp.advance(st, ind, m15.iloc[:b + 17], "BTCUSDT")
    assert st["status"] == "long" and st["entry"] == m15.iloc[b + 16].open
    assert st["stop"] < st["entry"] and 0 < st["size_x"] <= tp.MAX_POSITION_X
    # then falls through the stop: closed at a loss of a little over 1R
    m15.loc[m15.index[b + 17]] = [199, 199, 150, 151]
    tp.advance(st, ind, m15.iloc[:b + 18], "BTCUSDT")
    assert st["status"] == "flat"
    assert -1.2 < st["closed"][-1]["r"] < -1.0


def test_old_resting_limit_is_cancelled():
    m15, h4, d1, b = _frames()
    st = {"last15": str(m15.index[b - 2]), "status": "pending", "level": 1.0, "atr": 1.0,
          "expires": str(m15.index[-1])}
    ev = tp.advance(st, tp.indicators(d1, h4), m15.iloc[:b], "BTCUSDT")
    assert st["status"] == "flat" and "cancelled" in ev[0]


def test_breakout_alert_names_the_order(monkeypatch, tmp_path):
    m15, h4, d1, b = _frames()
    st = {"last15": str(m15.index[b - 1]), "status": "flat"}
    ev = [e for e in tp.advance(st, tp.indicators(d1, h4), m15.iloc[:b + 16], "BTCUSDT") if "BREAKOUT" in e][0]
    title, body, urgent = tp.alert_text("BTCUSDT", ev, st, 10_000.0)
    assert urgent and title.startswith("BTC: BUY NOW at market")
    assert "STOP" in body and "leverage" in body


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
