"""Watchlists — groups of symbols the user tracks, with live quotes attached."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.core.errors import ApiError, NotFound
from app.db import app_store
from app.engine import core
from app.services.serialization import clean_value


def _now() -> str:
    return app_store._now()


def list_all(with_quotes: bool = False) -> list[dict[str, Any]]:
    con = app_store.connect()
    try:
        lists = con.execute(
            "SELECT * FROM app_watchlists ORDER BY name COLLATE NOCASE").fetchall()
        items = con.execute(
            "SELECT * FROM app_watchlist_items ORDER BY symbol").fetchall()
    finally:
        con.close()

    by_list: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        by_list.setdefault(item["watchlist_id"], []).append(dict(item))

    symbols = sorted({i["symbol"] for group in by_list.values() for i in group})
    quotes = _quotes(symbols) if (with_quotes and symbols) else {}

    out = []
    for row in lists:
        entries = by_list.get(row["id"], [])
        for entry in entries:
            entry.update(quotes.get(entry["symbol"], {}))
        out.append({**dict(row), "items": entries, "count": len(entries)})
    return out


def get(watchlist_id: int, with_quotes: bool = True) -> dict[str, Any]:
    con = app_store.connect()
    try:
        row = con.execute("SELECT * FROM app_watchlists WHERE id=?", (watchlist_id,)).fetchone()
        if row is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")
        items = con.execute(
            "SELECT * FROM app_watchlist_items WHERE watchlist_id=? ORDER BY symbol",
            (watchlist_id,)).fetchall()
    finally:
        con.close()
    entries = [dict(i) for i in items]
    if with_quotes and entries:
        quotes = _quotes([e["symbol"] for e in entries])
        for entry in entries:
            entry.update(quotes.get(entry["symbol"], {}))
    return {**dict(row), "items": entries, "count": len(entries)}


def create(name: str, description: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ApiError("Give the watchlist a name.")
    con = app_store.connect()
    try:
        exists = con.execute("SELECT 1 FROM app_watchlists WHERE name=?", (name,)).fetchone()
        if exists:
            raise ApiError(f"A watchlist called '{name}' already exists.")
        cur = con.execute(
            "INSERT INTO app_watchlists(name,description,created_at,updated_at) VALUES(?,?,?,?)",
            (name, description, _now(), _now()))
        con.commit()
        new_id = int(cur.lastrowid)
    finally:
        con.close()
    return get(new_id, with_quotes=False)


def rename(watchlist_id: int, name: str | None, description: str | None) -> dict[str, Any]:
    con = app_store.connect()
    try:
        row = con.execute("SELECT * FROM app_watchlists WHERE id=?", (watchlist_id,)).fetchone()
        if row is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")
        con.execute(
            "UPDATE app_watchlists SET name=?, description=?, updated_at=? WHERE id=?",
            ((name or row["name"]).strip(),
             description if description is not None else row["description"],
             _now(), watchlist_id))
        con.commit()
    finally:
        con.close()
    return get(watchlist_id, with_quotes=False)


def delete(watchlist_id: int) -> None:
    con = app_store.connect()
    try:
        if con.execute("SELECT 1 FROM app_watchlists WHERE id=?", (watchlist_id,)).fetchone() is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")
        con.execute("DELETE FROM app_watchlist_items WHERE watchlist_id=?", (watchlist_id,))
        con.execute("DELETE FROM app_watchlists WHERE id=?", (watchlist_id,))
        con.commit()
    finally:
        con.close()


def add_symbols(watchlist_id: int, symbols: list[str], note: str | None = None) -> dict[str, Any]:
    cleaned = [str(s).upper().replace(".NS", "").strip() for s in symbols if str(s).strip()]
    if not cleaned:
        raise ApiError("Provide at least one symbol.")
    con = app_store.connect()
    try:
        if con.execute("SELECT 1 FROM app_watchlists WHERE id=?", (watchlist_id,)).fetchone() is None:
            raise NotFound(f"Watchlist {watchlist_id} does not exist.")
        for symbol in cleaned:
            con.execute(
                """INSERT OR IGNORE INTO app_watchlist_items(watchlist_id,symbol,note,added_at)
                   VALUES(?,?,?,?)""", (watchlist_id, symbol, note, _now()))
        con.execute("UPDATE app_watchlists SET updated_at=? WHERE id=?", (_now(), watchlist_id))
        con.commit()
    finally:
        con.close()
    return get(watchlist_id)


def remove_symbol(watchlist_id: int, symbol: str) -> dict[str, Any]:
    clean = str(symbol).upper().replace(".NS", "").strip()
    con = app_store.connect()
    try:
        con.execute("DELETE FROM app_watchlist_items WHERE watchlist_id=? AND symbol=?",
                    (watchlist_id, clean))
        con.execute("UPDATE app_watchlists SET updated_at=? WHERE id=?", (_now(), watchlist_id))
        con.commit()
    finally:
        con.close()
    return get(watchlist_id)


def _quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Last close + daily move + the newest scanner verdict, in two queries.

    Doing this per symbol would open the candle store once per row; the
    watchlist page would then take seconds to render a twenty-name list.
    """
    if not symbols:
        return {}
    placeholders = ",".join("?" * len(symbols))
    con = core._db()
    try:
        candles = pd.read_sql_query(
            f"""SELECT c.symbol, c.dt, c.close, c.volume FROM candles c
                  JOIN (SELECT symbol, MAX(dt) AS dt FROM candles
                         WHERE symbol IN ({placeholders}) GROUP BY symbol) latest
                    ON c.symbol = latest.symbol AND c.dt = latest.dt""",
            con, params=symbols)
        history = pd.read_sql_query(
            f"""SELECT symbol, dt, close FROM candles
                 WHERE symbol IN ({placeholders}) AND dt >= ?
              ORDER BY symbol, dt""",
            con, params=[*symbols, (date.today() - timedelta(days=15)).isoformat()])
        signals = pd.read_sql_query(
            f"""SELECT symbol, strategy, score, signal_date, safety_status
                  FROM scanner_signals WHERE symbol IN ({placeholders})
              ORDER BY signal_date DESC""",
            con, params=symbols)
    finally:
        con.close()

    previous: dict[str, float] = {}
    if not history.empty:
        for symbol, group in history.groupby("symbol"):
            closes = group.close.tolist()
            if len(closes) >= 2:
                previous[str(symbol)] = float(closes[-2])

    latest_signal: dict[str, dict[str, Any]] = {}
    for row in signals.itertuples():
        latest_signal.setdefault(str(row.symbol), {
            "signal_strategy": row.strategy,
            "signal_score": clean_value(row.score),
            "signal_date": row.signal_date,
            "signal_safety": row.safety_status,
        })

    live: dict[str, dict[str, Any]] = {}
    if core.dhan_configured() and core.nse_market_is_open():
        try:
            live = core.live_price_map(symbols)
        except Exception:
            live = {}

    out: dict[str, dict[str, Any]] = {}
    for row in candles.itertuples():
        symbol = str(row.symbol)
        price = float(row.close)
        source = "STORED CLOSE"
        if symbol in live:
            price = float(live[symbol]["price"])
            source = str(live[symbol]["source"])
        prev = previous.get(symbol)
        out[symbol] = {
            "price": round(price, 2),
            "price_source": source,
            "last_session": row.dt,
            "change_pct": clean_value(None if not prev else round((price / prev - 1) * 100, 2)),
            "volume": clean_value(row.volume),
            **latest_signal.get(symbol, {}),
        }
    for symbol in symbols:
        out.setdefault(symbol, {"price": None, "price_source": "NO DATA",
                                "last_session": None, "change_pct": None, "volume": None})
    return out
