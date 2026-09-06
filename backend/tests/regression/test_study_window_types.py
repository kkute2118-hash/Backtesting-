"""A study that captures nothing must say so, not report success.

Run directly:  python3 backend/tests/regression/test_study_window_types.py

Two of the four research studies had never produced a single row. Asked for two
years of Nifty 500 they answered:

    done  {"study": "raw_signals", "signals": 0, "elapsed_seconds": 106.4}

Success, in 106 seconds, over a universe where the gated backtest found 2,357
trades from the same candles.

Two defects, and it took both to hide it. run_raw_signal_backtest() and
run_sl_calibration_study() never normalised their window, so `start` and `end`
arrived as datetime.date while bar timestamps are pd.Timestamp, and pandas
refuses that comparison:

    TypeError: Cannot compare Timestamp with datetime.date

That fires on the FIRST signal of every ticker — and the per-ticker guard was
`except Exception: continue`, which turned "every symbol crashed" into "no
signals found". _professional_bt() normalises on its second line, which is why
the gated backtest worked and its ungated twin did not.

Both are fixed here: the window is normalised, and an empty result with failures
raises instead of returning quietly.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, tempfile
from datetime import date, timedelta

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-study-window-")

import numpy as np
import pandas as pd
from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


BARS = 400
INDEX = pd.bdate_range("2024-01-01", periods=BARS)
FRAME = pd.DataFrame(
    {"open": np.linspace(100, 200, BARS), "high": np.linspace(101, 202, BARS),
     "low": np.linspace(99, 198, BARS), "close": np.linspace(100, 200, BARS),
     "volume": np.full(BARS, 1_000_000.0)},
    index=INDEX,
)
DATA = {"AAA": FRAME, "BBB": FRAME}

# One signal per ticker, in the middle of the window, with everything the row
# helpers would have computed replaced by constants — the maths is not what broke.
SIGNAL_ROW = 300
core.features_fast = lambda ticker, df: df
core.strategy_signal = lambda f, s: pd.Series(
    [i == SIGNAL_ROW and s == 1 for i in range(len(f))], index=f.index)
core._safety_fast_series = lambda df: (pd.Series(1e7, index=df.index),
                                       pd.Series(False, index=df.index))
core._regime_from_row = lambda f, i: ("BULL", 60)
core._safety_from_row = lambda a, b, i: (80, [], [])
core._row_score = lambda f, i, s, regime, safe: (88, {})
core.compute_signal_fingerprint = lambda *a, **k: {}
core.atr_series = getattr(core, "atr_series", lambda df, n=14: pd.Series(2.0, index=df.index))
core._persist_raw_fingerprints = lambda *a, **k: None
core._persist_sl_calibration = lambda *a, **k: None

# The exact call the job makes: _bt_period() returns datetime.date, not Timestamp.
start, end = date(2024, 1, 1), date(2026, 1, 1)
check("the window really is a plain date (this is what broke it)",
      isinstance(start, date) and not isinstance(start, pd.Timestamp))

raw = core.run_raw_signal_backtest(DATA, [1], start, end)
check("the raw-signal study captures signals with date bounds",
      raw is not None and len(raw) == 2, f"{0 if raw is None else len(raw)} rows")

try:
    sl = core.run_sl_calibration_study(DATA, [1], start, end)
    check("the calibration study captures rows with date bounds",
          sl is not None and len(sl) > 0, f"{0 if sl is None else len(sl)} rows")
    check("it walks every stop scheme over each signal",
          sl is not None and len(sl) >= 2, f"{0 if sl is None else len(sl)} rows")
except Exception as exc:
    check("the calibration study captures rows with date bounds", False,
          f"{type(exc).__name__}: {exc}")
    check("it walks every stop scheme over each signal", False, "did not run")

# ------------- and the part that let it lie: silence when everything fails
def explode(f, i):
    raise ValueError("synthetic per-ticker failure")


core._regime_from_row = explode
for name, fn in (("raw-signal study", core.run_raw_signal_backtest),
                 ("calibration study", core.run_sl_calibration_study)):
    try:
        result = fn(DATA, [1], start, end)
        check(f"the {name} refuses to call a total failure an empty result", False,
              f"returned {0 if result is None else len(result)} rows")
    except RuntimeError as exc:
        check(f"the {name} refuses to call a total failure an empty result", True)
        check(f"  and names the first real failure ({name})",
              "synthetic per-ticker failure" in str(exc) and "failed=2" in str(exc), str(exc))
        check(f"  and accounts for every symbol ({name})",
              "symbols=2" in str(exc) and "scanned=0" in str(exc), str(exc))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
