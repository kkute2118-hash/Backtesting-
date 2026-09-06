"""A feature at time T must not change when the future is deleted.

Run directly:  python3 backend/tests/regression/test_point_in_time.py

This is the test that should have existed from the beginning. The rule it
enforces is the whole of the research contract:

    A signal at time T may only use information available at or before T.

It is checked the only way that cannot be argued with: compute a feature on the
full history, compute it again on the history TRUNCATED at T, and require the
value at T to be identical. A feature that peeks changes when the future is
removed.

What it caught. features_fast() — whose own docstring called it "the core
anti-lookahead safeguard" — built weekly and monthly features by grouping the
frame into finished periods and mapping each period's completed high, low and
close onto every day inside it. A Tuesday bar read Friday's close; a bar on the
3rd of the month read the month's eventual high. Every strategy reads wrsi14,
and S1, S2 and S4 read the monthly fields, so essentially the entire two-year
backtest was built on information that did not exist yet.

The fix advances EMA and Wilder RSI ONE exact step from the last completed
period instead of recomputing over a finished one — exact, because the engine
defines both with adjust=False.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-pit-")

import numpy as np
import pandas as pd
from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# A deterministic frame with real intra-period shape: each month rises then
# falls, so a month's eventual high and close differ sharply from any given day.
n = 900
idx = pd.bdate_range("2022-01-03", periods=n)
t = np.arange(n)
wave = 100 + 25 * np.sin(t / 10.5) + t * 0.05
FRAME = pd.DataFrame(
    {"open": wave, "high": wave * 1.02, "low": wave * 0.98,
     "close": wave, "volume": np.full(n, 500_000.0)},
    index=idx,
)

ASOF_COLUMNS = [
    "mclose", "mopen", "mhigh", "mlow", "mrsi14", "mema10", "mema15", "mema20",
    "mmom", "mmax20", "mprevclose", "mprevhigh", "mprevlow",
    "m_cross_count20", "m_cross_10_20",
    "wrsi14", "wema20", "wema50", "wclose",
]

# Cut points deliberately mid-period, where a whole-period resample leaks most.
CUTS = [619, 640, 661, 682, 703, 724, 745, 766, 787, 808]


def leaks(feature_fn, columns, label):
    full = feature_fn("full", FRAME)
    bad, tested, first = 0, 0, None
    for i in CUTS:
        T = FRAME.index[i]
        if T not in full.index:
            continue
        trunc = feature_fn(f"cut{i}", FRAME.iloc[: i + 1])
        if T not in trunc.index:
            continue
        for c in columns:
            a, b = full.loc[T, c], trunc.loc[T, c]
            tested += 1
            if pd.isna(a) and pd.isna(b):
                continue
            if not np.isclose(float(a), float(b), rtol=1e-9, atol=1e-9):
                bad += 1
                if first is None:
                    first = f"{c} at {T.date()}: {a} with the future, {b} without"
    return bad, tested, first


# ------------------------------------------------- 1. the engine as it stands
bad, tested, first = leaks(core.features_fast, ASOF_COLUMNS, "features_fast")
check(f"features_fast is truncation-invariant ({tested} comparisons)", bad == 0, first or "")

# ---------------------------------- 2. the test genuinely detects the old bug
#
# Reproduce exactly what the code used to do — group into finished periods and
# map each period's completed values onto every day inside it — and confirm the
# test rejects it. A test for look-ahead that cannot fail on real look-ahead is
# worse than no test.
def leaking_features(symbol, df):
    x = df.sort_index().copy()
    for freq, cols in (("W-FRI", {"wclose": "close"}), ("M", {"mclose": "close", "mhigh": "high"})):
        key = x.index.to_period(freq)
        finished = x.groupby(key).agg(close=("close", "last"), high=("high", "max"))
        for out, src in cols.items():
            x[out] = finished[src].reindex(key).to_numpy()
    return x


bad_old, tested_old, first_old = leaks(leaking_features, ["wclose", "mclose", "mhigh"], "old")
check(f"the test rejects the original implementation ({tested_old} comparisons)", bad_old > 0)
check("  and reports where it leaked", first_old is not None, "no example captured")
if first_old:
    print(f"        old code leaked: {first_old}")

# --------------------------------- 3. the snapshot cache cannot serve old data
#
# features_fast() returns a persisted snapshot when one matches, so a corrected
# engine would still hand back features computed by the broken one until the
# store is retired. ENGINE_VERSION keys that store; it must move when the
# meaning of a feature changes.
check("ENGINE_VERSION records the point-in-time fix",
      "PIT" in core.ENGINE_VERSION.upper(), core.ENGINE_VERSION)

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
