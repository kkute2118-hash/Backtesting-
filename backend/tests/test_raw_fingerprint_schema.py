"""Saving backtest fingerprints into a table created by an older version.

The production backup's raw_signal_fingerprints table predates the score_*
columns, so run_raw_signal_backtest() finished the whole replay and then died
on "table raw_signal_fingerprints has no column named score_trend".
"""

from __future__ import annotations

import pandas as pd

from app.engine import core


def _old_schema_table():
    con = core._db()
    try:
        con.execute("DROP TABLE IF EXISTS raw_signal_fingerprints")
        # The shape the backup on the db-backup branch actually has: no score_* columns.
        con.execute("""CREATE TABLE raw_signal_fingerprints(
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created_at TEXT,
            ticker TEXT, strategy TEXT, signal_date TEXT, return_pct REAL)""")
        con.commit()
    finally:
        con.close()


def test_persist_adds_columns_the_old_table_lacks():
    _old_schema_table()
    result = pd.DataFrame([{
        "created_at": "2026-09-27T10:00:00", "ticker": "ABC", "strategy": "S4",
        "signal_date": "2026-09-01", "return_pct": 4.2,
        "score_trend": 7.5, "score_htf": 3, "safety_flags": "none",
    }])
    core._persist_raw_fingerprints(result, "2026-01-01", "2026-09-27", 1)

    con = core._db()
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(raw_signal_fingerprints)")}
        row = con.execute("SELECT ticker, score_trend, score_htf, safety_flags "
                          "FROM raw_signal_fingerprints ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    assert {"score_trend", "score_htf", "safety_flags"} <= cols
    assert row == ("ABC", 7.5, 3, "none")


def test_new_columns_get_a_sensible_type():
    frame = pd.DataFrame({"i": [1], "f": [1.5], "b": [True], "t": ["x"]})
    assert [core._sqlite_type_for(frame[c]) for c in frame] == ["INTEGER", "REAL", "INTEGER", "TEXT"]
