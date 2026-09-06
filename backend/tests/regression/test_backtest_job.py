"""The backtest has to run somewhere it can finish.

Run directly:  python3 backend/tests/regression/test_backtest_job.py

Measured on the free web instance while a Nifty 500 / 1 Year replay was running:

    07:09  backtest starts   CPU 0.07 / 0.15    memory 324 MB / 512 MB
    07:12                    CPU 0.15 — pinned  memory 379 MB
    07:17                    CPU 0.15 — pinned  memory 535 MB
    07:25                    CPU 0.15 — pinned  memory 530 MB

Sixteen minutes in it was at 99.7% of its memory cap with the CPU saturated, and
it never returned. The engine is not at fault and neither is the request: that
hardware cannot do this work. So the same replay runs as a workflow job on a
runner instead, and writes to the same tables the app reads, which is why the
Backtest page shows the result without knowing where it ran.

This checks the wiring, not the maths — the engine's own tests cover the replay.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
import os, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-backtest-job-")

import pandas as pd
from app.engine import core
import daily_job

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


calls = {"backtest": None, "persisted": None, "learned": 0, "backed_up": 0, "token": 0}

BT = pd.DataFrame({
    "Ticker": ["AAA", "BBB", "CCC", "DDD"],
    "Strategy": ["S1", "S1", "S3", "S3"],
    "Score": [92, 88, 95, 86],
    "R": [1.5, -1.0, 2.0, -1.0],
    "Outcome": ["WIN", "LOSS", "WIN", "LOSS"],
    "Return %": [7.5, -5.0, 10.0, -5.0],
    "MFE %": [9.0, 1.0, 12.0, 0.5],
    "MAE %": [-2.0, -5.0, -1.5, -5.0],
})

core._github_configured = lambda: True
daily_job.step_restore = lambda: False
daily_job.backup_or_fail = lambda: calls.__setitem__("backed_up", calls["backed_up"] + 1) or True
core.resolve_universes = lambda universes: [f"SYM{i}" for i in range(500)]
core.local_backtest_status = lambda t, s, e: pd.DataFrame({"Ready": [True] * 480 + [False] * 20})
core._learn_from_backtest = lambda bt: calls.__setitem__("learned", len(bt)) or len(bt)
core._persist_backtest = lambda *args: calls.__setitem__("persisted", args)
core._dhan_generate_fresh_token = lambda: calls.__setitem__("token", calls["token"] + 1)


def fake_run_local_backtest(tickers, start, end, threshold=85):
    calls["backtest"] = {"tickers": len(tickers), "start": start, "end": end,
                         "threshold": threshold}
    return BT


core.run_local_backtest = fake_run_local_backtest

# ------------------------------------------------------------ 1. a normal run
os.environ["SCAN_UNIVERSE"] = "Nifty 500"
os.environ["BACKTEST_PERIOD"] = "1 Year"
os.environ["BACKTEST_THRESHOLD"] = "90"

summary = daily_job.run_backtest()

check("it replays the whole resolved universe", calls["backtest"]["tickers"] == 500,
      str(calls["backtest"]))
check("it passes the requested score gate through", calls["backtest"]["threshold"] == 90,
      str(calls["backtest"]["threshold"]))

expected_start, expected_end = core._bt_period("1 Year")
check("it uses the engine's own window for the period",
      (calls["backtest"]["start"], calls["backtest"]["end"]) == (expected_start, expected_end),
      f"{calls['backtest']['start']} → {calls['backtest']['end']}")
check("the window really is about a year",
      360 <= (expected_end - expected_start).days <= 370,
      str((expected_end - expected_start).days))

check("the result is persisted where the app reads it", calls["persisted"] is not None)
check("persisted with the period and threshold it ran",
      calls["persisted"][1] == "1 Year" and calls["persisted"][4] == 90,
      str(calls["persisted"][1:5]))
check("learning is fed from the same trades", calls["learned"] == len(BT))
check("and the run is saved before the machine goes away", calls["backed_up"] == 1)

# It reads local candles only — needing a Dhan token would tie a research run to
# a credential it has no use for, and to Dhan's token rate limit.
check("it never asks Dhan for a token", calls["token"] == 0)

check("the summary reports what happened",
      summary["trades"] == 4 and summary["win_pct"] == 50.0 and summary["symbols"] == 500,
      str(summary))

# -------------------------------------------------- 2. a period it cannot honour
os.environ["BACKTEST_PERIOD"] = "18 Months"
try:
    daily_job.run_backtest()
    check("an unknown period is rejected by name", False, "it ran anyway")
except RuntimeError as exc:
    check("an unknown period is rejected by name", "18 Months" in str(exc), str(exc))
    check("and the error lists the ones that work", "6 Months" in str(exc) and "3 Years" in str(exc))

# ------------------------------------------- 3. no history is a clear message
os.environ["BACKTEST_PERIOD"] = "1 Year"


def no_data(*a, **k):
    raise RuntimeError("NO_LOCAL_DATA")


core.run_local_backtest = no_data
try:
    daily_job.run_backtest()
    check("an empty candle store is explained, not raised raw", False, "it ran anyway")
except RuntimeError as exc:
    check("an empty candle store is explained, not raised raw",
          "history build" in str(exc) and "NO_LOCAL_DATA" != str(exc), str(exc))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
