"""Results calendar: parsing NSE board meetings, storing them, and the flag."""

from __future__ import annotations

import sys
from pathlib import Path

from app.engine import core

# daily_job.py lives at the repository root, one level above backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# The shape NSE's /api/corporate-board-meetings returns: a list of rows.
SAMPLE = [
    {"bm_symbol": "WELCORP", "bm_date": "06-Oct-2026", "bm_purpose": "Financial Results",
     "sm_name": "Welspun Corp Limited"},
    {"bm_symbol": "MCX", "bm_date": "30-Oct-2026", "bm_purpose": "Financial Results/Dividend"},
    {"bm_symbol": "ABDL", "bm_date": "02-Oct-2026", "bm_purpose": "Fund Raising"},
    {"bm_symbol": "BROKEN", "bm_date": "sometime", "bm_purpose": "Financial Results"},
]


def test_parse_keeps_results_meetings_only():
    rows = core.parse_board_meetings(SAMPLE)
    assert [(r["symbol"], r["event_date"]) for r in rows] == [
        ("WELCORP", "2026-10-06"), ("MCX", "2026-10-30")]


def test_parse_accepts_a_wrapped_payload_and_other_key_names():
    rows = core.parse_board_meetings({"data": [
        {"symbol": "tcs", "meetingDate": "2026-10-09", "purpose": "Quarterly Results"}]})
    assert rows == [{"symbol": "TCS", "event_date": "2026-10-09", "purpose": "Quarterly Results"}]


def test_upcoming_results_window():
    core.store_corporate_events(core.parse_board_meetings(SAMPLE))
    soon = core.upcoming_results(["WELCORP", "MCX", "ABDL"], on_date="2026-10-01", days=7)
    assert soon == {"WELCORP": "2026-10-06"}          # MCX is 29 days out, ABDL not results
    assert core.corporate_events_freshness() is not None


def test_daily_job_survives_an_unreachable_nse(monkeypatch):
    import daily_job
    def boom(*a, **k):
        raise ConnectionError("blocked")
    monkeypatch.setattr(core, "fetch_nse_board_meetings", boom)
    assert daily_job.step_events() is None
