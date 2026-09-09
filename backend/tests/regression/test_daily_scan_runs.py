"""The daily job must actually scan, and must survive a provider hiccup.

Run directly:  python3 backend/tests/regression/test_daily_scan_runs.py

Two incidents, one day apart, that both ended with no forward test recorded.

1. The scan never ran. run_daily() refused unless the store's newest session
   equalled the newest session the calendar expected. Dhan does not reliably
   publish a session's daily candle the same evening — on 8 Sep the 17:01 and
   19:06 IST runs both found nothing, and the store still ended 8 Sep at 19:07
   IST the following day — so the store sits a session behind "expected" for
   most of a day and that test skipped the scan every single time:

       sync   0/501 stocks advanced; newest stored session 2026-09-08
       fresh  stored candles end 2026-09-08, expected 2026-09-09
       guard  candles are not current ... SKIPPING the scan

   A stored daily candle IS a completed session, whatever the calendar says.
   The job now scans the newest session it actually holds, and dates the
   signals by that session so a scan that lands the next morning still files
   under the close it was computed from.

2. A transient 500 killed the run. Dhan's token endpoint failed on 8 Sep at
   19:06 IST and the job died on the spot — no sync, no scan, no backup —
   while a usable token sat in the cache:

       Exception: Failed to generate token via PIN/TOTP: {'status': 500, ...}
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile
import types
from datetime import date

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-daily-scan-")

import pandas as pd

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ------------------------------------------------------------------ harness
ROOT = pathlib.Path(__file__).resolve().parents[2].parent
sys.path.insert(0, str(ROOT))

from app.engine import core  # noqa: E402

CALLS = []
METRICS = {}
STATE = {
    "stored": date(2026, 9, 8),      # what the store holds
    "expected": date(2026, 9, 9),    # what the calendar wants — Dhan is late
    "token_raises": False,
    "cached_token": ("tok", "2026-09-09T08:00:00"),
    "added_signal_date": None,
    "persist_signal_date": None,
}


def install_stubs(daily_job):
    core._metric_get = lambda k, d=None: METRICS.get(k, d)
    core._metric_set = lambda k, v: METRICS.__setitem__(k, v)
    core._github_configured = lambda: True
    core._dhan_pin_totp_configured = lambda: True
    core._dhan_manual_token_configured = lambda: False
    core._read_cached_dhan_token = lambda: STATE["cached_token"]
    core.resolve_universes = lambda u: [f"S{i}.NS" for i in range(1, 6)]
    core.UNIVERSE_CHOICES = ["Nifty 500"]
    core.latest_completed_nse_session = lambda *a, **k: STATE["expected"]
    core.last_expected_nse_session = lambda *a, **k: STATE["expected"]
    core.market_today = lambda *a, **k: STATE["expected"]
    core.sync_latest_sessions = lambda t, **k: (CALLS.append("sync") or
        {"advanced": 0, "symbols": 5, "latest": str(STATE["stored"]), "errors": []})
    core.data_freshness_status = lambda t, **k: {
        "latest": STATE["stored"], "expected": STATE["expected"],
        "current": STATE["stored"] == STATE["expected"], "days_behind": 1}
    core.refresh_forward_positions = lambda: (CALLS.append("resolve") or (12, 0))
    core.load_scan_dataset = lambda t, **k: {f"S{i}.NS": pd.DataFrame({"close": [1] * 300})
                                             for i in range(1, 6)}
    core.regime_from_index = lambda d: ("BULL", 60)

    def scan(data, strat, regime, stats=None, **k):
        CALLS.append("scan")
        if stats is not None:
            stats.update({"usable": 5, "signals": {1: 2, 2: 0, 3: 1, 4: 0}})
        return pd.DataFrame({"Score": [92.0, 88.0], "Ticker": ["HAL", "ASTERDM"],
                             "Strategy": ["S1", "S3"]})
    core.scan_dataset = scan

    def persist(result, min_score, signal_date=None):
        CALLS.append("persist")
        STATE["persist_signal_date"] = signal_date
    core.persist_scanner_signals = persist

    def add(df, signal_date=None):
        CALLS.append("add")
        STATE["added_signal_date"] = signal_date
        return len(df)
    core.add_forward_candidates = add

    def gen():
        if STATE["token_raises"]:
            raise Exception("Failed to generate token via PIN/TOTP: "
                            "{'status': 500, 'error': 'Internal Server Error'}")
        CALLS.append("gen_token")
        return "tok"
    core._dhan_generate_fresh_token = gen
    core._dhan_ensure_fresh_token = lambda: "tok"

    daily_job.step_restore = lambda: CALLS.append("restore")
    daily_job.backup_or_fail = lambda: CALLS.append("backup")


import daily_job  # noqa: E402
install_stubs(daily_job)


def run():
    CALLS.clear()
    STATE["added_signal_date"] = None
    STATE["persist_signal_date"] = None
    return daily_job.run_daily(), list(CALLS)


# ------------------- 1. the incident: provider late, scan must still happen
METRICS.clear()
summary, calls = run()
check("a store one session behind 'expected' is still scanned",
      "scan" in calls and "add" in calls, str(calls))
check("the run reports the session it scanned",
      summary.get("session") == "2026-09-08", str(summary))
check("candidates were recorded", summary.get("added") == 2, str(summary))

# ------------------- 2. signals are dated by the session, not the run date
check("forward candidates are dated by the session scanned",
      STATE["added_signal_date"] == date(2026, 9, 8), str(STATE["added_signal_date"]))
check("persisted signals are dated by the session scanned",
      STATE["persist_signal_date"] == date(2026, 9, 8), str(STATE["persist_signal_date"]))
check("that is NOT the run date", STATE["added_signal_date"] != STATE["expected"])

# ------------------- 3. re-running the same session is a no-op
summary2, calls2 = run()
check("the second run of the same session does not rescan",
      "scan" not in calls2 and "add" not in calls2, str(calls2))
check("it still resolves and backs up",
      "resolve" in calls2 and "backup" in calls2, str(calls2))

os.environ["FORCE_RESCAN"] = "1"
_s, calls3 = run()
check("FORCE_RESCAN scans it again", "scan" in calls3, str(calls3))
os.environ.pop("FORCE_RESCAN")

# ------------------- 4. a new session is picked up
STATE["stored"] = date(2026, 9, 9)
summary4, calls4 = run()
check("a newly stored session is scanned", "scan" in calls4, str(calls4))
check("dated by the new session", STATE["added_signal_date"] == date(2026, 9, 9))

# ------------------- 5. an empty store is refused, not scanned
METRICS.clear()
STATE["stored"] = None
_s5, calls5 = run()
check("an empty store is not scanned", "scan" not in calls5, str(calls5))
check("and still backs up", "backup" in calls5, str(calls5))
STATE["stored"] = date(2026, 9, 9)

# ------------------- 6. a provider 500 must not lose the run
METRICS.clear()
STATE["token_raises"] = True
summary6, calls6 = run()
check("a token 500 no longer kills the run",
      "scan" in calls6 and "add" in calls6 and "backup" in calls6, str(calls6))
check("it fell back to the cached token", "gen_token" not in calls6, str(calls6))

# ...but with no cached token there is nothing to fall back to, so it must fail
STATE["cached_token"] = (None, None)
try:
    run()
    check("no token and no cache must fail loudly", False, "it returned instead of raising")
except Exception:
    check("no token and no cache still fails loudly", True)
STATE["cached_token"] = ("tok", "2026-09-09T08:00:00")
STATE["token_raises"] = False

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
