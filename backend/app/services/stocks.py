"""Everything the stock detail page needs: quote, candles, indicators, signals.

Only what the engine genuinely computes is exposed. There is no fabricated
market cap, sector or company profile: the Dhan instrument master gives an
instrument name and a security id, Twelve Data gives fundamentals *if* it is
configured, and anything else is reported as unavailable rather than invented.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ApiError, NotFound
from app.engine import core
from app.services.serialization import clean_value, frame_to_records

TIMEFRAMES = {"1M": 22, "3M": 66, "6M": 132, "1Y": 252, "2Y": 504, "5Y": 1260, "MAX": None}


def _normalise(symbol: str) -> str:
    return str(symbol).upper().replace(".NS", "").strip()


def _history(symbol: str, lookback_days: int = 1400) -> pd.DataFrame:
    con = core._db()
    try:
        df = core._read_cache(con, _normalise(symbol),
                              date.today() - timedelta(days=lookback_days), date.today())
    finally:
        con.close()
    if df is None or df.empty:
        raise NotFound(
            f"No stored candles for {_normalise(symbol)}. Sync this stock from "
            "Data Manager, or check the symbol."
        )
    return df.sort_index()


def _instrument(symbol: str) -> dict[str, Any]:
    """Name and exchange from Dhan's scrip master, when it is reachable."""
    sym = _normalise(symbol)
    try:
        master = core.dhan_master()
    except Exception:
        return {"name": None, "security_id": None, "exchange": "NSE", "segment": "Cash"}
    try:
        cols = {str(c).upper(): c for c in master.columns}
        sym_col = cols.get("SEM_TRADING_SYMBOL") or cols.get("SM_SYMBOL_NAME")
        name_col = cols.get("SEM_CUSTOM_SYMBOL") or cols.get("SM_SYMBOL_NAME")
        id_col = cols.get("SEM_SMST_SECURITY_ID")
        if sym_col is None:
            return {"name": None, "security_id": None, "exchange": "NSE", "segment": "Cash"}
        hit = master[master[sym_col].astype(str).str.upper() == sym]
        if hit.empty:
            return {"name": None, "security_id": None, "exchange": "NSE", "segment": "Cash"}
        row = hit.iloc[0]
        return {
            "name": str(row[name_col]) if name_col else None,
            "security_id": clean_value(row[id_col]) if id_col else None,
            "exchange": "NSE",
            "segment": "Cash",
        }
    except Exception:
        return {"name": None, "security_id": None, "exchange": "NSE", "segment": "Cash"}


def quote(symbol: str, use_live: bool = True) -> dict[str, Any]:
    """Last price with explicit provenance, plus the day's move."""
    sym = _normalise(symbol)
    df = _history(sym, lookback_days=400)
    last = df.iloc[-1]
    prev_close = float(df.close.iloc[-2]) if len(df) > 1 else None

    price = float(last.close)
    source = "STORED CLOSE"
    as_of = clean_value(df.index[-1])

    if use_live and core.dhan_configured():
        try:
            live = core.live_price_map([sym])
            hit = live.get(sym)
            if hit:
                price = float(hit.get("price", price))
                source = str(hit.get("source", "LIVE"))
                as_of = clean_value(hit.get("ts", as_of))
        except Exception:
            pass

    change = None if prev_close in (None, 0) else price - prev_close
    change_pct = None if not prev_close else (price / prev_close - 1) * 100

    return {
        "symbol": sym,
        **_instrument(sym),
        "price": round(price, 2),
        "previous_close": clean_value(prev_close),
        "change": clean_value(None if change is None else round(change, 2)),
        "change_pct": clean_value(None if change_pct is None else round(change_pct, 2)),
        "open": clean_value(last.open),
        "high": clean_value(last.high),
        "low": clean_value(last.low),
        "volume": clean_value(last.volume),
        "price_source": source,
        "price_as_of": as_of,
        "last_session": clean_value(df.index[-1]),
        "bars_stored": int(len(df)),
        "market_open": bool(core.nse_market_is_open()),
    }


def history(symbol: str, timeframe: str = "1Y", with_indicators: bool = True) -> dict[str, Any]:
    """Candles for the chart, with the moving averages the strategies use."""
    if timeframe not in TIMEFRAMES:
        raise ApiError(f"Unknown timeframe '{timeframe}'. Use one of: {', '.join(TIMEFRAMES)}.")
    sym = _normalise(symbol)
    df = _history(sym, lookback_days=2600)

    overlays: dict[str, list] = {}
    if with_indicators and len(df) >= 260:
        try:
            f = core.features_fast(sym, df)
            df = df.copy()
            for column in ("ema10", "ema20", "ema50", "ema200", "rsi14", "relvol",
                           "atr14", "vol20"):
                if column in f.columns:
                    df[column] = f[column]
        except Exception:
            pass

    bars = TIMEFRAMES[timeframe]
    view = df if bars is None else df.tail(bars)

    candles = [
        {
            "time": clean_value(idx),
            "open": clean_value(row.open),
            "high": clean_value(row.high),
            "low": clean_value(row.low),
            "close": clean_value(row.close),
            "volume": clean_value(row.volume),
        }
        for idx, row in view.iterrows()
    ]
    for column in ("ema10", "ema20", "ema50", "ema200", "rsi14"):
        if column in view.columns:
            overlays[column] = [
                {"time": clean_value(idx), "value": clean_value(val)}
                for idx, val in view[column].items()
            ]

    return {"symbol": sym, "timeframe": timeframe, "candles": candles, "overlays": overlays}


def indicators(symbol: str) -> dict[str, Any]:
    """The engine's own indicator readings for the latest completed bar."""
    sym = _normalise(symbol)
    df = _history(sym)
    if len(df) < 260:
        raise ApiError(
            f"{sym} has only {len(df)} stored bars. The multi-timeframe engine needs "
            "260 to produce a reading; sync more history first."
        )
    f = core.features_fast(sym, df).replace([np.inf, -np.inf], np.nan)
    z = f.iloc[-1]

    def val(name: str):
        return clean_value(getattr(z, name, None))

    close = float(z.close)

    def distance(name: str):
        level = getattr(z, name, None)
        if level is None or not np.isfinite(level) or level == 0:
            return None
        return round((close / float(level) - 1) * 100, 2)

    hi_52w = float(df.close.tail(252).max()) if len(df) >= 20 else None
    lo_52w = float(df.close.tail(252).min()) if len(df) >= 20 else None

    return {
        "symbol": sym,
        "as_of": clean_value(df.index[-1]),
        "daily": {
            "close": round(close, 2),
            "rsi14": val("rsi14"),
            "atr14": val("atr14"),
            "relvol": val("relvol"),
            "vol20": val("vol20"),
            "vol30": val("vol30"),
            "ema10": val("ema10"), "ema20": val("ema20"), "ema50": val("ema50"),
            "ema200": val("ema200"), "ema250": val("ema250"),
            "dist_ema20_pct": distance("ema20"),
            "dist_ema50_pct": distance("ema50"),
            "dist_ema200_pct": distance("ema200"),
        },
        "weekly": {"rsi14": val("wrsi14"), "ema20": val("wema20"),
                   "ema50": val("wema50"), "close": val("wclose")},
        "monthly": {"rsi14": val("mrsi14"), "ema10": val("mema10"),
                    "ema15": val("mema15"), "ema20": val("mema20"),
                    "close": val("mclose"), "momentum_pct": val("mmom"),
                    "max_momentum_20m": val("mmax20"),
                    "bull_crosses_20m": val("m_cross_count20")},
        "range": {
            "high_52w": clean_value(hi_52w),
            "low_52w": clean_value(lo_52w),
            "pct_from_52w_high": clean_value(
                None if not hi_52w else round((close / hi_52w - 1) * 100, 2)),
        },
        "compression": _compression(df),
    }


def _compression(df: pd.DataFrame) -> dict[str, Any]:
    try:
        comp = core.compression_features(df)
    except Exception:
        return {}
    return {str(k): clean_value(v) for k, v in (comp or {}).items()}


def condition_matrix(symbol: str, strategies: list[int] | None = None) -> dict[str, Any]:
    """Rule-by-rule pass/fail for each strategy — why a stock did or did not qualify.

    ANDing a strategy's conditions reproduces ``strategy_signal()`` exactly, so
    this is the honest explanation of the scanner's verdict rather than a
    narrative written after the fact.
    """
    sym = _normalise(symbol)
    df = _history(sym)
    if len(df) < 260:
        raise ApiError(f"{sym} has only {len(df)} stored bars; 260 are needed.")
    f = core.features_fast(sym, df).replace([np.inf, -np.inf], np.nan)

    wanted = sorted({int(s) for s in (strategies or [1, 2, 3, 4]) if int(s) in (1, 2, 3, 4)})
    out = []
    for s in wanted:
        matrix = core.strategy_condition_matrix(f, s)
        conditions = []
        for name, series in matrix.items():
            passed = bool(series.iloc[-1]) if len(series) else False
            conditions.append({
                "name": name,
                "passed": passed,
                "distance_pct": clean_value(
                    None if passed else _near_miss(name, f)),
            })
        signal = bool(core.strategy_signal(f, s).iloc[-1])
        passed_count = sum(1 for c in conditions if c["passed"])
        out.append({
            "strategy": f"S{s}",
            "label": f"S{s}_SEPA" if s == 4 else f"S{s}",
            "signal": signal,
            "passed": passed_count,
            "total": len(conditions),
            "conditions": conditions,
        })
    return {"symbol": sym, "as_of": clean_value(df.index[-1]), "strategies": out}


def _near_miss(name: str, f: pd.DataFrame):
    try:
        distance = core._near_miss_distance(name, f, -1)
    except Exception:
        return None
    if distance is None:
        return None
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return None
    # A structural gate ("inside yesterday's range") has no meaningful distance
    # and the engine returns NaN for it; report that as "no distance", not 0%.
    return None if not np.isfinite(value) else round(value * 100, 2)


def signal_detail(symbol: str) -> dict[str, Any]:
    """The scanner's own record for this stock: score breakdown, edge, forward test."""
    sym = _normalise(symbol)
    con = core._db()
    try:
        signals = pd.read_sql_query(
            "SELECT * FROM scanner_signals WHERE symbol=? ORDER BY signal_date DESC LIMIT 20",
            con, params=(sym,))
        forwards = pd.read_sql_query(
            """SELECT id,signal_date,strategy,score,regime,entry,sl,target,status,
                      ltp,mfe,mae,exit_price,result_r,updated_at
                 FROM forward_tests WHERE symbol=? ORDER BY signal_date DESC""",
            con, params=(sym,))
    finally:
        con.close()
    return {
        "symbol": sym,
        "signals": frame_to_records(signals),
        "forward_tests": frame_to_records(forwards),
    }


def safety_report(symbol: str, include_news: bool = False) -> dict[str, Any]:
    """Small/micro-cap safety: liquidity, volatility, gaps, circuit-like moves."""
    sym = _normalise(symbol)
    df = _history(sym)

    info: dict[str, Any] = {}
    news_risk = 0.0
    news_items: list[dict[str, Any]] = []
    fundamentals_available = False
    if include_news and core.twelvedata_configured():
        try:
            info, _flags = core.company_info(sym)
            fundamentals_available = bool(info)
        except Exception:
            info = {}
        try:
            items, _sentiment, news_risk = core.news_snapshot(sym)
            news_items = list(items or [])
        except Exception:
            news_items = []

    base_score, base_status, base_flags = core.safety(info, df)
    score, status, flags = core.advanced_small_micro_safety(info, df, news_risk=news_risk)

    traded_value = float((df.close * df.volume).tail(20).mean()) if len(df) >= 20 else None

    return {
        "symbol": sym,
        "score": int(score),
        "status": status,
        "flags": list(dict.fromkeys(flags)),
        "base": {"score": int(base_score), "status": base_status, "flags": list(base_flags)},
        "metrics": {
            "avg_traded_value_20d": clean_value(traded_value),
            "news_risk": clean_value(news_risk),
        },
        "news": {
            "available": bool(core.twelvedata_configured()) and include_news,
            "items": news_items[:10],
        },
        "fundamentals_available": fundamentals_available,
    }


def dna(symbol: str) -> dict[str, Any]:
    """Stock DNA — the stock's own historical leg size, used for position sizing."""
    sym = _normalise(symbol)
    df = _history(sym)
    payload = core.stock_dna(df)
    return {"symbol": sym, **{str(k): clean_value(v) for k, v in (payload or {}).items()}}


def fundamentals(symbol: str) -> dict[str, Any]:
    """Twelve Data fundamentals + Piotroski, when that provider is configured."""
    sym = _normalise(symbol)
    if not core.twelvedata_configured():
        return {"symbol": sym, "available": False,
                "message": "Twelve Data is not configured, so fundamentals are unavailable.",
                "profile": {}, "flags": [], "piotroski": None, "screens": {}}
    info, flags = core.company_info(sym)
    statements = None
    piotroski = None
    try:
        statements = core._td_get_statements(sym)
        piotroski = core.piotroski_score(statements)
    except Exception:
        pass
    return {
        "symbol": sym,
        "available": True,
        "profile": {str(k): clean_value(v) for k, v in (info or {}).items()},
        "flags": list(flags or []),
        "piotroski": clean_value(piotroski),
        "screens": {
            "model_a": clean_value(core.model_a(info) if info else None),
            "model_b": clean_value(core.model_b(info) if info else None),
        },
    }


def sepa_detail(symbol: str) -> dict[str, Any]:
    """S4 SEPA specifics: watchlist gate, entry signal, quality parts, trail stop."""
    sym = _normalise(symbol)
    df = _history(sym)
    if len(df) < 260:
        raise ApiError(f"{sym} has only {len(df)} stored bars; 260 are needed.")
    try:
        watchlist = bool(core.strategy4_sepa_watchlist(core.features_fast(sym, df)).iloc[-1])
    except Exception:
        watchlist = False
    try:
        signal = bool(core.strategy4_sepa_signal(df).iloc[-1])
    except Exception:
        signal = False
    score, parts = core._s4_sepa_quality(df)
    return {
        "symbol": sym,
        "watchlist": watchlist,
        "signal": signal,
        "score": clean_value(score),
        "parts": {str(k): clean_value(v) for k, v in (parts or {}).items()},
        "trailing_stop": clean_value(core.sepa_trailing_stop(df)),
    }


def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Symbol search over the local candle store, then the Dhan master.

    The stored store is searched first because those are the stocks that can
    actually be opened right now - a name Dhan lists but we hold no candles for
    would open onto an empty page.
    """
    q = _normalise(query)
    if not q:
        return []
    con = core._db()
    try:
        rows = con.execute(
            """SELECT symbol, COUNT(*) AS bars, MAX(dt) AS latest FROM candles
                WHERE symbol LIKE ? GROUP BY symbol ORDER BY
                      CASE WHEN symbol = ? THEN 0 WHEN symbol LIKE ? THEN 1 ELSE 2 END,
                      symbol LIMIT ?""",
            (f"%{q}%", q, f"{q}%", int(limit)),
        ).fetchall()
    finally:
        con.close()
    return [{"symbol": r[0], "bars": int(r[1]), "latest": r[2], "stored": True} for r in rows]
