"""Session dates must come from market time, not from the host's clock.

Run directly:  python3 backend/tests/regression/test_market_clock_timezone.py

The incident: the daily job ran, succeeded, and moved nothing, every single day.
Its own log said why, on Monday 2026-09-07 at 13:37 UTC — 19:07 IST, nearly four
hours after the 15:30 IST close:

    guard    no new completed session to process (latest is 2026-09-04)
    sync     0/501 stocks advanced; newest stored session 2026-09-04
    fresh    stored candles end 2026-09-04, expected 2026-09-04

It believed Friday was the last session, so it asked Dhan for a range it already
held, got nothing back, and reported the store as current.

Every session rule is written against IST wall-clock, but they read
datetime.now() — the HOST clock. That is right only on a machine set to IST.
GitHub Actions runners and the web host both run UTC, and IST is UTC+05:30, so
13:30 UTC read as 13:30 "IST", which is before the 15:30 close:
latest_completed_nse_session() rolled back a day to Sunday, and the weekend rule
then walked Sunday back to Friday. Both cron times sit in the broken window:

    11:20 UTC = 16:50 IST (after close) -> read as before close -> Friday
    13:30 UTC = 19:00 IST (after close) -> read as before close -> Friday

Nothing downstream could notice. The job was not failing; it was being told the
market had not traded.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, tempfile, time
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-market-clock-")

from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def old_latest_completed(now):
    """The implementation that shipped, reconstructed exactly.

    A test for a clock bug that cannot fail on the buggy clock is worth nothing,
    so the last section below asserts this really is rejected.
    """
    close_today = now.replace(hour=15, minute=30, second=0, microsecond=0)
    d = now.date()
    if now < close_today:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


UTC = timezone.utc
MON, TUE, FRI = date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 4)

# --------------------------------------------- 1. the reported run, exactly
for utc_hour, utc_min in ((11, 20), (13, 30)):          # the two cron times
    moment = datetime(2026, 9, 7, utc_hour, utc_min, tzinfo=UTC)
    ist = moment.astimezone(core.MARKET_TZ)
    check(f"{utc_hour:02d}:{utc_min:02d} UTC ({ist:%H:%M} IST, after close) -> Monday",
          core.latest_completed_nse_session(moment) == MON,
          f"got {core.latest_completed_nse_session(moment)}, wanted {MON}")

# ------------------------------------------- 2. before the close is still before
# The rule must not simply shift everything forward; a run genuinely before
# 15:30 IST must still report the previous session.
pre = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)            # 09:30 IST, market open
check("09:30 IST on Monday -> previous session (Friday)",
      core.latest_completed_nse_session(pre) == FRI,
      str(core.latest_completed_nse_session(pre)))
check("15:29 IST -> still Friday",
      core.latest_completed_nse_session(datetime(2026, 9, 7, 9, 59, tzinfo=UTC)) == FRI)
check("15:31 IST -> Monday",
      core.latest_completed_nse_session(datetime(2026, 9, 7, 10, 1, tzinfo=UTC)) == MON)

# --------------------------------------------------- 3. weekend still holds
check("Saturday evening -> Friday",
      core.latest_completed_nse_session(datetime(2026, 9, 5, 18, 0, tzinfo=UTC)) == FRI)
check("Sunday evening -> Friday",
      core.latest_completed_nse_session(datetime(2026, 9, 6, 18, 0, tzinfo=UTC)) == FRI)

# ------------------------------------------------ 4. naive in, naive out
# Callers and older tests pass naive datetimes meaning IST wall-clock. That
# contract must survive, or fixing the clock would quietly break them.
check("naive 19:00 Monday is read as IST",
      core.latest_completed_nse_session(datetime(2026, 9, 7, 19, 0)) == MON)
check("naive 11:00 Monday is read as IST (before close)",
      core.latest_completed_nse_session(datetime(2026, 9, 7, 11, 0)) == FRI)
check("market_now() passes a naive value through unchanged",
      core.market_now(datetime(2026, 9, 7, 19, 0)) == datetime(2026, 9, 7, 19, 0))
check("market_now() converts an aware value into IST",
      core.market_now(datetime(2026, 9, 7, 13, 30, tzinfo=UTC)) == datetime(2026, 9, 7, 19, 0))

# -------------------------------------------- 5. market hours under UTC input
check("13:30 UTC (19:00 IST) is NOT open", not core.nse_market_is_open(datetime(2026, 9, 7, 13, 30, tzinfo=UTC)))
check("05:00 UTC (10:30 IST) IS open", core.nse_market_is_open(datetime(2026, 9, 7, 5, 0, tzinfo=UTC)))
check("03:00 UTC (08:30 IST) is NOT open", not core.nse_market_is_open(datetime(2026, 9, 7, 3, 0, tzinfo=UTC)))
check("Saturday 05:00 UTC is NOT open", not core.nse_market_is_open(datetime(2026, 9, 5, 5, 0, tzinfo=UTC)))
check("current_session_date during the session is that day",
      core.current_session_date(datetime(2026, 9, 7, 5, 0, tzinfo=UTC)) == MON)

# ------------------------------- 6. the answer must not depend on the host TZ
# The real condition: the same instant, read on a UTC host and on an IST host,
# must produce the same session. This is what the deployment actually varies.
saved_tz = os.environ.get("TZ")


def with_host_tz(name, fn):
    os.environ["TZ"] = name
    time.tzset()
    try:
        return fn()
    finally:
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()


readings = {tz: with_host_tz(tz, lambda: (core.market_now(), core.market_today(),
                                          core.latest_completed_nse_session()))
            for tz in ("UTC", "Asia/Kolkata", "America/New_York", "Pacific/Auckland")}

sessions_seen = {tz: r[2] for tz, r in readings.items()}
check("the same instant gives the same session on every host timezone",
      len(set(sessions_seen.values())) == 1, str(sessions_seen))

clocks = [r[0] for r in readings.values()]
check("market_now() agrees across host timezones",
      max(clocks) - min(clocks) < timedelta(seconds=30),
      str({tz: str(r[0]) for tz, r in readings.items()}))

# market_now() must actually be IST, not merely consistent: compare it with the
# current instant converted independently.
expected_ist = datetime.now(UTC).astimezone(core.MARKET_TZ).replace(tzinfo=None)
check("market_now() really is IST",
      abs(core.market_now() - expected_ist) < timedelta(seconds=30),
      f"{core.market_now()} vs {expected_ist}")
check("IST is UTC+05:30", core.MARKET_UTC_OFFSET == timedelta(hours=5, minutes=30))

# ----------------------------- 7. the old implementation must be rejected
# Reconstruct the shipped behaviour on the host clock of a UTC runner and show
# it produces the wrong session for the very moment in the incident log.
broken = old_latest_completed(datetime(2026, 9, 7, 13, 30))   # naive UTC, as it ran
check("the old host-clock reading really did return Friday",
      broken == FRI, f"got {broken}")
check("this test rejects the old implementation",
      broken != core.latest_completed_nse_session(datetime(2026, 9, 7, 13, 30, tzinfo=UTC)))

# -------------- 8. the signal date crosses midnight UTC, not midnight IST
# Between 18:30 and 24:00 UTC it is already tomorrow in India. Forward
# candidates dedupe on (symbol, strategy, signal_date), so a writer on the host
# clock and one on market time would disagree there and record a setup twice.
late = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)               # 01:30 IST on Tuesday
check("market time is already the next day after 18:30 UTC",
      core.market_now(late).date() == TUE, str(core.market_now(late).date()))
check("the host clock would still say Monday there",
      late.replace(tzinfo=None).date() == MON)

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
