"""Point-in-time tests for the liquidity detector.

The one failure mode that matters is a setup that could only be found by
looking at bars after it. Truncating the data at the setup's own entry bar
must leave that setup, unchanged, in the output.
"""
import numpy as np, pandas as pd, sqlite3, pytest
import liq
from build_events import load

DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")


@pytest.fixture(scope="module")
def syms():
    con = sqlite3.connect(DB)
    s = [r[0] for r in con.execute(
        "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=400 "
        "ORDER BY symbol LIMIT 12")]
    con.close()
    return s


def test_setups_survive_truncation_at_their_own_entry_bar(syms):
    """No setup may depend on a bar at or after its entry."""
    checked = 0
    for s in syms:
        df = load(DB, s)
        full = liq.find_setups(df)
        for r in full[-4:]:
            j = r["bar"]
            if j < 320:
                continue
            trunc = liq.find_setups(df.iloc[:j + 1])
            m = [t for t in trunc if t["bar"] == j and t["kind"] == r["kind"]]
            assert m, f"{s} {r['kind']} at {r['date']} vanishes when truncated"
            for key in ("entry_plan", "level", "stop_struct", "target_liq",
                        "level_touches", "level_res", "conf_body_mult"):
                a, b = r[key], m[0][key]
                if isinstance(a, float) and np.isnan(a):
                    assert np.isnan(b), f"{s} {key}"
                else:
                    assert a == b, f"{s} {key}: {a} vs {b}"
            checked += 1
    assert checked >= 15, f"only {checked} setups checked"


def test_a_pivot_is_never_used_before_it_is_confirmed(syms):
    df = load(DB, syms[0])
    L = df["low"].to_numpy(); H = df["high"].to_numpy()
    lo, hi = liq.pivots(L, H, 10)
    for p, known in lo + hi:
        assert known == p + 10


def test_entry_bar_cannot_pay_but_can_stop():
    n = 40
    O = np.full(n, 100.0); H = np.full(n, 101.0)
    L = np.full(n, 99.0); C = np.full(n, 100.0)
    H[5] = 130.0                       # entry bar spikes to the target
    p, b, how = liq.walk(O, H, L, C, 5, 100.0, 95.0, 120.0)
    assert how != "target"
    L[5] = 90.0                        # and the same bar can still stop us
    p, b, how = liq.walk(O, H, L, C, 5, 100.0, 95.0, 120.0)
    assert how == "stop" and b == 0


def test_equal_lows_deepen_the_level_only_as_each_touch_confirms():
    """Touches must count backwards, never forwards."""
    n = 200
    L = np.full(n, 100.0); H = np.full(n, 110.0)
    for p in (40, 80):
        L[p] = 90.0
    lows, _ = liq.build_pools(L, H, 10, 0.010)
    at90 = sorted((q for q in lows if abs(q["px"] - 90.0) < 1e-9),
                  key=lambda q: q["known"])
    assert [q["known"] for q in at90] == [50, 90]
    assert [q["touches"] for q in at90] == [1, 2]   # not [2, 2]


def test_a_future_touch_cannot_reprice_or_delay_a_level():
    """The 22000-vs-28499 bug: a later touch must not alter an earlier level."""
    n = 200
    L = np.full(n, 100.0); H = np.full(n, 110.0)
    L[40] = 90.0
    L[120] = 89.5                       # same cluster, 0.6% away, far in the future
    early = [q for q in liq.build_pools(L, H, 10, 0.010)[0] if q["known"] == 50]
    assert len(early) == 1
    assert early[0]["px"] == 90.0 and early[0]["touches"] == 1
