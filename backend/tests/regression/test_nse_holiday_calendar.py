"""A closed exchange is not a data outage.

Run directly:  python3 backend/tests/regression/test_nse_holiday_calendar.py

The incident: Monday 2026-09-14 was Ganesh Chaturthi. The NSE did not trade,
Dhan published no candle, and for three days every run said the same thing —

    sync   0/501 stocks advanced; newest stored session 2026-09-11
    fresh  stored candles end 2026-09-11, expected 2026-09-15
    guard  session 2026-09-11 has already been scanned

— while the app showed a red "Stale data — top up before scanning" banner. The
store was completely current. Nothing was broken; the calendar only knew about
weekends, so a holiday and a dead download produced byte-identical output, and
the line that should raise the alarm had been raising it every day anyway.

Two distinct false alarms are covered here:

  1. The holiday itself. 2026-09-14 must not count as a session.
  2. Dhan's publication lag. Daily candles land the NEXT morning, so between
     15:30 IST and ~09:00 IST tomorrow the store is SUPPOSED to be one session
     behind. Measuring against the newest *completed* session instead of the
     newest *published* one flagged every weekday evening as stale.

And the safety property that makes the hardcoded table tolerable: it must never
narrow a Dhan request range. A wrong holiday entry then costs one empty
response instead of silently losing a session's candles forever.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-nse-holiday-")

import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.engine import core  # noqa: E402

UTC = timezone.utc
FRI, SAT, MON, TUE, WED = (date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 14),
                           date(2026, 9, 15), date(2026, 9, 16))

# ------------------------------------------------- 1. the holiday is a holiday
check("Ganesh Chaturthi 2026-09-14 is not a session", not core.is_nse_session(MON))
check("the following Tuesday is", core.is_nse_session(TUE))
check("the preceding Friday is", core.is_nse_session(FRI))
check("Saturday is not", not core.is_nse_session(SAT))
check("the holiday is named, not just refused",
      core.nse_session_note(MON) == "NSE holiday: Ganesh Chaturthi", str(core.nse_session_note(MON)))
check("a trading day has no note", core.nse_session_note(TUE) is None, str(core.nse_session_note(TUE)))
check("a weekend says weekend", core.nse_session_note(SAT) == "weekend")

check("the session before Tuesday skips the holiday",
      core.previous_nse_session(TUE) == FRI, str(core.previous_nse_session(TUE)))
check("the newest session as of the holiday itself is Friday",
      core.last_expected_trading_session(MON) == FRI, str(core.last_expected_trading_session(MON)))

# 19:00 IST on the holiday: the old code said "Monday closed, you are behind".
check("19:00 IST on the holiday reports Friday as the last completed session",
      core.latest_completed_nse_session(datetime(2026, 9, 14, 13, 30, tzinfo=UTC)) == FRI,
      str(core.latest_completed_nse_session(datetime(2026, 9, 14, 13, 30, tzinfo=UTC))))
check("the market is never open on the holiday",
      not core.nse_market_is_open(datetime(2026, 9, 14, 5, 0, tzinfo=UTC)))
check("but it is open at the same hour the next day",
      core.nse_market_is_open(datetime(2026, 9, 15, 5, 0, tzinfo=UTC)))

check("sessions_between skips the holiday", core.sessions_between(FRI, TUE) == 1,
      str(core.sessions_between(FRI, TUE)))
check("and counts a plain run of trading days",
      core.sessions_between(TUE, date(2026, 9, 18)) == 3,
      str(core.sessions_between(TUE, date(2026, 9, 18))))

# ------------------------------------- 2. Dhan's publication lag is not lateness
# 19:06 IST on Tuesday 15 Sep — the exact moment of the run in the incident.
tue_evening = datetime(2026, 9, 15, 13, 36, tzinfo=UTC)
check("Tuesday evening: the newest completed session is Tuesday",
      core.latest_completed_nse_session(tue_evening) == TUE)
check("Tuesday evening: the newest PUBLISHED session is still Friday",
      core.last_published_session(tue_evening) == FRI,
      str(core.last_published_session(tue_evening)))
check("Wednesday 09:14 IST: Tuesday's candle is now expected",
      core.last_published_session(datetime(2026, 9, 16, 3, 44, tzinfo=UTC)) == TUE,
      str(core.last_published_session(datetime(2026, 9, 16, 3, 44, tzinfo=UTC))))
# 09:14 IST on Tuesday, the catch-up run: the only thing published is Friday,
# because Monday never happened.
check("Tuesday 09:14 IST: published is Friday, so a store ending Friday is current",
      core.last_published_session(datetime(2026, 9, 15, 3, 44, tzinfo=UTC)) == FRI,
      str(core.last_published_session(datetime(2026, 9, 15, 3, 44, tzinfo=UTC))))

# ------------------------------------------- 3. freshness reports three states
core._db()  # create the schema in the temp store
con = core._db()
try:
    con.execute("DELETE FROM candles")
    rows = []
    # A believable universe: 40 symbols over the sessions leading up to Friday.
    day = date(2026, 8, 3)
    while day <= FRI:
        if day.weekday() < 5:
            for i in range(40):
                rows.append((f"T{i}", day.strftime("%Y-%m-%d"), 1.0, 1.0, 1.0, 1.0, 100))
        day += timedelta(days=1)
    con.executemany("INSERT OR REPLACE INTO candles(symbol,dt,open,high,low,close,volume) "
                    "VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
finally:
    con.close()
core.invalidate_session_calendar()

tickers = [f"T{i}" for i in range(40)]
fresh = core.data_freshness_status(tickers, now=tue_evening)
check("a store ending Friday is CURRENT on Tuesday evening, not stale",
      fresh["current"] is True, str(fresh))
check("and says so as 'awaiting publication', not as a clean bill of health",
      fresh["awaiting_publication"] is True, str(fresh))
check("zero sessions behind", fresh["days_behind"] == 0, str(fresh["days_behind"]))

# By Thursday morning Tuesday AND Wednesday are published and genuinely missing.
thu = datetime(2026, 9, 17, 4, 0, tzinfo=UTC)
stale = core.data_freshness_status(tickers, now=thu)
check("a real gap is still reported as stale", stale["current"] is False, str(stale))
check("counted in sessions, and the holiday is not one of them",
      stale["days_behind"] == 2, str(stale["days_behind"]))
check("a real gap is not dressed up as publication lag",
      stale["awaiting_publication"] is False, str(stale))

# ------------------------------------ 4. the store overrides the table, always
# Pretend the exchange traded on 14 Sep after all: with candles present, the
# table must lose. This is what makes a wrong hardcoded entry survivable.
con = core._db()
try:
    con.executemany("INSERT OR REPLACE INTO candles(symbol,dt,open,high,low,close,volume) "
                    "VALUES (?,?,?,?,?,?,?)",
                    [(f"T{i}", MON.strftime("%Y-%m-%d"), 1.0, 1.0, 1.0, 1.0, 100) for i in range(40)])
    con.commit()
finally:
    con.close()
core.invalidate_session_calendar()
check("a day WITH candles is a session even though the table calls it a holiday",
      core.is_nse_session(MON), "the hardcoded table overrode observed data")

# ...and the reverse: a weekday inside the stored range with no data at all is
# a non-session even though no table mentions it. This is what keeps the
# calendar correct in 2027 and beyond, when the table has run out.
blank = date(2026, 9, 9)   # a Wednesday we now empty out
con = core._db()
try:
    con.execute("DELETE FROM candles WHERE dt=?", (blank.strftime("%Y-%m-%d"),))
    con.commit()
finally:
    con.close()
core.invalidate_session_calendar()
check("a weekday with no candles anywhere is a non-session, table or no table",
      not core.is_nse_session(blank), str(core.nse_session_note(blank)))
check("and it is explained rather than left blank",
      core.nse_session_note(blank) is not None)

# ---------------------------- 5. the table must never narrow a request window
# Every caller of last_expected_nse_session() is a Dhan request bound. If the
# holiday table reached those, one wrong entry would stop the job ever asking
# for a real session's candles — the failure this whole change exists to avoid.
check("request bounds stay holiday-blind (the holiday is still a valid end date)",
      core.last_expected_nse_session(MON) == MON,
      str(core.last_expected_nse_session(MON)))
check("request bounds still skip weekends", core.last_expected_nse_session(SAT) == FRI)

import ast  # noqa: E402
import inspect  # noqa: E402

tree = ast.parse(inspect.getsource(core))
bound_fns = {"sync_latest_sessions", "update_dhan_symbol"}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in bound_fns:
        called = {n.func.id for n in ast.walk(node)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        check(f"{node.name}() does not bound its request with the holiday calendar",
              "last_expected_trading_session" not in called, str(sorted(called)))

# ---------------------------------- 6. an empty store falls back, not forward
# Fresh deployment, no candles: the calendar must still work off the table and
# must not classify every weekday as a non-session because nothing is stored.
# Emptying the table is the honest way to do this — repointing GTF_DATA_DIR
# mid-process does not move an already-resolved database path, so section 4's
# rows stayed visible and this section quietly tested nothing.
con = core._db()
try:
    con.execute("DELETE FROM candles")
    con.commit()
    remaining = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
finally:
    con.close()
core.invalidate_session_calendar()
check("the store really is empty for this section", remaining == 0, str(remaining))
check("with an empty store an ordinary weekday is still a session",
      core.is_nse_session(TUE), "an empty store must not blank the calendar")
check("with an empty store the holiday table still applies", not core.is_nse_session(MON))
check("a year the table does not cover falls back to weekday-only",
      core.is_nse_session(date(2031, 9, 15)) and not core.is_nse_session(date(2031, 9, 14)),
      "2031-09-15 is a Monday, 2031-09-14 a Sunday")

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
