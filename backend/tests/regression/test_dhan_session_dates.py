"""A candle must carry the date of the session it belongs to.

Run directly:  python3 backend/tests/regression/test_dhan_session_dates.py

The incident: after the first full history build, the app's newest bar was
2026-09-03 when the last NSE session was Friday 2026-09-04, and the daily job
refused to scan every time — the freshness guard compares the newest stored date
against the real expected session, so a store that is permanently one day behind
can never be current.

The store said the rest out loud. Across five years and 1,355 session dates it
held 272 SUNDAYS and four Fridays, on an exchange that trades Monday to Friday:

    {'Thu': 267, 'Sun': 272, 'Mon': 272, 'Tue': 268, 'Wed': 270, 'Fri': 4}

Every bar was dated one day early. NSE trades in IST and Dhan stamps a daily bar
at the start of its session day in IST, which is 18:30 UTC of the day before;
reading those epochs as UTC moved every candle back a day. Nothing downstream
could notice, because the series stays in order — only its labels were wrong.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-session-dates-")

import pandas as pd
from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def epoch_ist_midnight(day):
    """What Dhan sends for that session: 00:00 IST on the session date."""
    return int(pd.Timestamp(f"{day} 00:00", tz=core.DHAN_MARKET_TZ).timestamp())


# --------------------------------------------- 1. the reported day, exactly
sessions = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
parsed = core._dhan_session_index([epoch_ist_midnight(d) for d in sessions])
got = [str(ts.date()) for ts in parsed]
check("each bar keeps its own session date", got == sessions, f"{got} != {sessions}")
check("Friday 2026-09-04 is not filed as Thursday", got[-1] == "2026-09-04", got[-1])

# ------------------------------------------------- 2. no weekend ever appears
weekdays = {ts.strftime("%a") for ts in parsed}
check("no weekend dates are produced", not (weekdays & {"Sat", "Sun"}), str(sorted(weekdays)))

# --------------------- 3. a midnight-UTC stamp must not be moved the other way
#
# IST is the safe reading in both directions: 00:00 UTC becomes 05:30 IST on the
# same date, so a plain UTC timestamp keeps its date. There is no input for
# which the old parse was right and this one is wrong.
utc_midnight = [int(pd.Timestamp(f"{d} 00:00", tz="UTC").timestamp()) for d in sessions]
got_utc = [str(ts.date()) for ts in core._dhan_session_index(utc_midnight)]
check("a midnight-UTC stamp keeps its date too", got_utc == sessions, f"{got_utc} != {sessions}")

# ------------------------------------ 4. the old parse really did shift the day
old = [str(ts.date()) for ts in
       pd.to_datetime([epoch_ist_midnight(d) for d in sessions], unit="s", errors="coerce")]
check("the old UTC parse is the one that lost a day",
      old[-1] == "2026-09-03" and old != sessions, str(old))

# ------------------------------------------------- 5. bars stay in order
check("the index is still sorted", list(parsed) == sorted(parsed))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
