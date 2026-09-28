"""Candles and live prices for the interactive chart.

One place decides where each timeframe comes from, so the chart never asks
for more than it shows:

  1D / 1W       the stored daily candles (1W built from them). No Dhan
                 call; the same bars the scanner and backtests read.
  15m / 1H       Dhan's intraday candles, for timing an entry the daily
                 scan found; fetched per window on demand and never written
                 to the database.

Only these four, on purpose: the strategies trade daily bars, and every
extra timeframe is more Dhan requests and memory on a small server.

Every response is one page of bars ending before `before` (or now), with the
cursor for the next older page, so the chart loads the recent past first and
more only when the user scrolls back. Pages are cached in memory: a window
that is entirely in the past for a day, the one touching today for 30 s.

Times are epoch seconds of the India wall clock (IST read as UTC). The chart
library draws UTC, so this is what makes its axis read 09:15, not 03:45.

The live quote is cached for LIVE_TTL_SECONDS across every viewer, so ten
open charts on one stock cost one Dhan request every five seconds, not ten.
The chart polls it; there is no held-open stream per viewer.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ApiError, NotFound
from app.engine import core
from app.services.stocks import _history, _normalise

IST_OFFSET = 19_800                     # seconds east of UTC
DAILY = ("1D", "1W")
INTRADAY = {                            # tf: (Dhan interval, days per page, max days back)
    "15m": ("15", 30, 180),
    "1H": ("60", 90, 365),
}
TIMEFRAMES = ("15m", "1H", "1D", "1W")
DAILY_PAGE_BARS = {"1D": 400, "1W": 260}
PAST_TTL, TODAY_TTL, LIVE_TTL_SECONDS = 86_400.0, 60.0, 5.0
CACHE_MAX = 128

_cache: dict[tuple, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: tuple, ttl: float, build):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = build()
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:                 # drop the oldest quarter
            for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: CACHE_MAX // 4]:
                _cache.pop(k, None)
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def intraday_available() -> bool:
    return bool(core.dhan_configured())


def available_timeframes() -> list[str]:
    return list(TIMEFRAMES) if intraday_available() else list(DAILY)


# ------------------------------------------------------------------ helpers
def _wall_epoch(index: pd.DatetimeIndex) -> list[int]:
    """India wall-clock times as epoch seconds (naive timestamps read as UTC)."""
    return [int(ts.value // 1_000_000_000) for ts in pd.DatetimeIndex(index)]


def _bars(df: pd.DataFrame) -> list[dict[str, Any]]:
    times = _wall_epoch(df.index)
    out = []
    for t, row in zip(times, df.itertuples()):
        if not all(np.isfinite(v) for v in (row.open, row.high, row.low, row.close)):
            continue
        vol = float(row.volume) if np.isfinite(row.volume) else 0.0
        out.append({"time": t, "open": round(float(row.open), 2), "high": round(float(row.high), 2),
                    "low": round(float(row.low), 2), "close": round(float(row.close), 2),
                    "volume": vol})
    return out


def _ohlc(frame: pd.DataFrame, grouper) -> pd.DataFrame:
    g = frame.groupby(grouper)
    out = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                        "close": g.close.last(), "volume": g.volume.sum()})
    out.index = g.apply(lambda x: x.index[0])          # labelled by the first bar in it
    return out.dropna(subset=["close"])


def _parse_before(before: str | int | None) -> pd.Timestamp | None:
    if before in (None, ""):
        return None
    try:
        if str(before).lstrip("-").isdigit():
            return pd.Timestamp(int(before), unit="s")      # wall-clock epoch from a previous page
        return pd.Timestamp(before)
    except (ValueError, TypeError) as exc:
        raise ApiError(f"'before' must be a date or an epoch time, not {before!r}.") from exc


# -------------------------------------------------------------------- daily
def _daily_page(sym: str, tf: str, before: pd.Timestamp | None) -> dict[str, Any]:
    df = _history(sym, lookback_days=40 * 366)            # raises NotFound for an unknown symbol
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    if tf == "1W":
        df = _ohlc(df, df.index.to_period("W-FRI"))
    if before is not None:
        df = df[df.index < before]
    n = DAILY_PAGE_BARS[tf]
    page = df.tail(n)
    has_more = len(df) > len(page)
    return {"candles": _bars(page), "has_more": bool(has_more),
            "next_before": _wall_epoch(page.index[:1])[0] if has_more and len(page) else None,
            "source": "stored daily candles"}


# ----------------------------------------------------------------- intraday
def dhan_intraday(sym: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Dhan v2 /charts/intraday for one window (at most 90 days), indexed by
    India wall-clock time."""
    sid = core.dhan_map().get(sym)
    if not sid:
        raise NotFound(f"{sym} is not in Dhan's instrument list, so it has no intraday data.")
    r = core._dhan_post("/charts/intraday", {
        "securityId": str(sid), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY",
        "interval": interval, "oi": False,
        "fromDate": start.strftime("%Y-%m-%d %H:%M:%S"), "toDate": end.strftime("%Y-%m-%d %H:%M:%S"),
    }, timeout=45, label="intraday")
    j = r.json()
    ts = j.get("timestamp") or []
    if not ts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    idx = (pd.to_datetime(ts, unit="s", utc=True).tz_convert(core.DHAN_MARKET_TZ).tz_localize(None))
    df = pd.DataFrame({k: j.get(k, []) for k in ("open", "high", "low", "close", "volume")}, index=idx)
    return df.apply(pd.to_numeric, errors="coerce").dropna(subset=["close"]).sort_index()


def _intraday_page(sym: str, tf: str, before: pd.Timestamp | None) -> dict[str, Any]:
    if not intraday_available():
        raise ApiError("Intraday charts need the Dhan data feed, which is not configured on this "
                       "server. Daily and weekly charts still work.",
                       status_code=503, code="not_configured")
    _history(sym, lookback_days=30)                     # unknown symbol -> 404 before any Dhan call
    interval, days, max_back = INTRADAY[tf]
    now = core.market_now().replace(tzinfo=None)
    end = min(before.to_pydatetime(), now) if before is not None else now
    # Windows start at midnight, so one page ends exactly where the next begins.
    start = datetime.combine((end - timedelta(days=days)).date(), datetime.min.time())
    floor = datetime.combine((now - timedelta(days=max_back)).date(), datetime.min.time())
    if end <= floor:
        return {"candles": [], "has_more": False, "next_before": None,
                "source": f"Dhan intraday ({interval} min)"}
    start = max(start, floor)
    touches_today = end.date() >= now.date()
    key = ("intraday", sym, interval, start.date().isoformat(), end.strftime("%Y-%m-%d %H:%M")
           if touches_today else end.date().isoformat())
    try:
        raw = _cached(key, TODAY_TTL if touches_today else PAST_TTL,
                      lambda: dhan_intraday(sym, interval, start, end))
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(f"Dhan did not return intraday candles for {sym} ({type(exc).__name__}). "
                       "Try again, or use the daily chart.", status_code=502,
                       code="upstream_error", detail=str(exc)[:300]) from exc
    df = raw[raw.index >= pd.Timestamp(start)]
    if before is not None:
        df = df[df.index < before]
    return {"candles": _bars(df), "has_more": start > floor,
            "next_before": int(pd.Timestamp(start).value // 1_000_000_000) if start > floor else None,
            "source": f"Dhan intraday ({interval} min)"}


def candles(symbol: str, tf: str = "1D", before: str | int | None = None) -> dict[str, Any]:
    """One page of candles for the chart, newest last."""
    sym = _normalise(symbol)
    if not sym or not all(c.isalnum() or c in "&-_" for c in sym):
        raise NotFound(f"'{symbol}' is not a valid NSE symbol.")
    if tf not in TIMEFRAMES:
        raise ApiError(f"Unsupported timeframe '{tf}'. Use one of: {', '.join(TIMEFRAMES)}.")
    cursor = _parse_before(before)
    page = _daily_page(sym, tf, cursor) if tf in DAILY else _intraday_page(sym, tf, cursor)
    return {"symbol": sym, "tf": tf, **page, "timeframes": available_timeframes(),
            "market_open": bool(core.nse_market_is_open())}


# --------------------------------------------------------------------- live
def live(symbol: str) -> dict[str, Any]:
    """The current quote, shared by every viewer for LIVE_TTL_SECONDS.

    Falls back to the last stored candle, and says so, when the market is
    closed or Dhan does not answer, so the chart header is never empty."""
    sym = _normalise(symbol)
    df = _history(sym, lookback_days=30)
    last, prev = df.iloc[-1], (df.iloc[-2] if len(df) > 1 else None)
    stored = {"symbol": sym, "ltp": float(last.close), "open": float(last.open),
              "high": float(last.high), "low": float(last.low), "volume": float(last.volume),
              "prev_close": float(prev.close) if prev is not None else None,
              "session": str(df.index[-1].date()), "source": "STORED CLOSE", "ts": None}
    market_open = bool(core.nse_market_is_open())
    quote = None
    if core.dhan_configured():
        def fetch():
            try:
                return core.dhan_quote_snapshot([sym]).get(sym)
            except Exception:
                return None
        quote = _cached(("live", sym), LIVE_TTL_SECONDS, fetch)
    if quote:
        q = {"symbol": sym, "ltp": float(quote["ltp"]),
             "open": _num(quote.get("open")), "high": _num(quote.get("high")),
             "low": _num(quote.get("low")), "volume": _num(quote.get("volume")),
             "prev_close": _num(quote.get("prev_close")) or stored["prev_close"],
             "session": str(core.market_today()), "source": "LIVE", "ts": quote.get("ts")}
        # Before today's first trade the quote repeats yesterday; keep the stored bar then.
        if not market_open and stored["session"] == q["session"]:
            q["source"] = "LAST TRADE"
        out = q
    else:
        out = stored
    pc = out.get("prev_close")
    out["change"] = round(out["ltp"] - pc, 2) if pc else None
    out["change_pct"] = round((out["ltp"] / pc - 1) * 100, 2) if pc else None
    out["market_open"] = market_open
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
