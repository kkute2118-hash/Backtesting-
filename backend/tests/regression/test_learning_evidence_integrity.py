"""Learning evidence must be countable, de-duplicated, and free of pre-fix rows.

Run directly:  python3 backend/tests/regression/test_learning_evidence_integrity.py

Three defects, one table.

1. Re-running a backtest inserted every row again. `_learn_from_backtest()` did a
   bare INSERT into a table with no unique constraint, so the same trade could
   be recorded any number of times. That does not merely add noise: the
   confidence gates in current_candidate_edge() are `Samples >= 20` and
   `>= 100`, so duplication MANUFACTURES confidence. Two backtest runs turn an
   honest "INSUFFICIENT SAMPLE" into a MEDIUM-confidence edge built on the same
   ten trades counted twice.

2. There was no engine_version column. PR#47 fixed a look-ahead bug in
   features_fast() - weekly/monthly features were reading future period closes -
   so every row written before ENGINE_VERSION reached FINAL-3_ASOF_PIT describes
   an engine that could see the future. Pooled with clean rows, they were
   indistinguishable, and every fit silently measured a mixture.

3. Backtest and forward rows share the table and nothing separated them on read.
   In-sample replay can outnumber the reality check by orders of magnitude, so a
   fit on the pooled table reports how well the rules match the data they were
   built from.

The requirement that pins all three: old rows are MARKED, never deleted.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-learning-evidence-")

import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.engine import core  # noqa: E402


def guard(name, fn, default=None):
    """Run a probe that the UNFIXED code cannot satisfy.

    Against the old implementation several of these symbols do not exist at all.
    Letting the AttributeError escape would abort the run at the first one and
    hide every later defect, so a test meant to characterise the old behaviour
    has to survive it and keep going.
    """
    try:
        return fn()
    except Exception as exc:
        check(name, False, f"{type(exc).__name__}: {exc}")
        return default


core.maybe_backup_db = lambda *a, **k: None
core.ensure_learning_tables()


def wipe():
    con = core._db()
    try:
        con.execute("DELETE FROM learning_observations")
        con.commit()
    finally:
        con.close()


def rows():
    con = core._db()
    try:
        return int(con.execute("SELECT COUNT(*) FROM learning_observations").fetchone()[0])
    finally:
        con.close()


def bt_frame(n=5, tag="A"):
    return pd.DataFrame([{
        "Ticker": f"T{i}", "Strategy": "S1", "Date": f"2026-0{i%9+1}-0{i%9+1}",
        "Score": 88.0 + i, "Regime": "BULL", "HTF": 12.0, "Footprint": 11.0,
        "Strategy Score": 20.0, "Entry Quality": 7.0, "Relative Strength": 5.0,
        "Safety": 90.0, "Entry": 100.0 + i, "Exit": 103.0, "R": 0.4,
        "Outcome": "WIN", "Holding Bars": 3,
    } for i in range(n)])


# ------------------------------- 1. the incident: a rerun must not duplicate
wipe()
first = core._learn_from_backtest(bt_frame())
after_first = rows()
second = core._learn_from_backtest(bt_frame())
after_second = rows()

check("the first backtest run records its observations", after_first == 5, str(after_first))
check("re-running the SAME backtest adds no rows", after_second == 5,
      f"{after_first} -> {after_second}")
check("and the second run reports that it added nothing", second == 0, str(second))
guard("while still reporting what it attempted", lambda: check(
    "while still reporting what it attempted",
    (core._LAST_LEARNING_WRITE or {}).get("attempted") == 5
    and (core._LAST_LEARNING_WRITE or {}).get("duplicates_suppressed") == 5,
    str(core._LAST_LEARNING_WRITE)))

# a genuinely different trade is still recorded
core._learn_from_backtest(pd.DataFrame([{
    "Ticker": "NEWSYM", "Strategy": "S1", "Date": "2026-04-04", "Score": 91.0,
    "Regime": "BULL", "HTF": 10.0, "Footprint": 10.0, "Strategy Score": 20.0,
    "Entry Quality": 7.0, "Relative Strength": 5.0, "Safety": 90.0,
    "Entry": 50.0, "Exit": 55.0, "R": 1.0, "Outcome": "WIN", "Holding Bars": 2,
}]))
check("a genuinely new observation is still recorded", rows() == 6, str(rows()))

# ...and the inflated-confidence consequence is what actually mattered
con = core._db()
try:
    n_s1 = int(con.execute(
        "SELECT COUNT(*) FROM learning_observations WHERE strategy='S1'").fetchone()[0])
finally:
    con.close()
check("six trades recorded twice do not read as twelve samples", n_s1 == 6, str(n_s1))

# -------------------------- 2. pre-PR#47 rows are excluded but NOT destroyed
wipe()
core._learn_from_backtest(bt_frame(3))
con = core._db()
try:
    legacy_tag = getattr(core, "LEGACY_ENGINE_VERSION", "PRE_PIT_UNVERSIONED")
    try:
        con.execute(
            """INSERT INTO learning_observations(created_at,market,symbol,strategy,signal_time,
               score,result_r,outcome,source,engine_version)
               VALUES('2025-01-01','INDIA','OLDSYM','S1','2025-01-01',99.0,3.0,'WIN','backtest',?)""",
            (legacy_tag,))
    except Exception:
        # No engine_version column at all - that IS the defect. Write the row
        # without it so the exclusion checks below still have something to miss.
        con.execute(
            """INSERT INTO learning_observations(created_at,market,symbol,strategy,signal_time,
               score,result_r,outcome,source)
               VALUES('2025-01-01','INDIA','OLDSYM','S1','2025-01-01',99.0,3.0,'WIN','backtest')""")
    con.commit()
finally:
    con.close()

snap = core.learning_snapshot("INDIA")
check("a fit sees only current-engine rows", len(snap) == 3, str(len(snap)))
check("the pre-fix row is not in the fit",
      "OLDSYM" not in set(snap.symbol.astype(str)), str(sorted(set(snap.symbol.astype(str)))))
check("but it still exists in the table", rows() == 4, str(rows()))
guard("and asking for every version returns it", lambda: check(
    "and asking for every version returns it",
    "OLDSYM" in set(core.learning_snapshot("INDIA", engine_version=None,
                                           include_legacy=True).symbol.astype(str))))

ev = guard("evidence counts are available at all",
           lambda: core.learning_evidence_counts("INDIA"), {}) or {}
check("the excluded rows are reported, not silently vanished",
      ev.get("excluded_pre_pit") == 1, str(ev))
check("usable observations are counted", ev.get("usable_total") == 3, str(ev))
check("counted per strategy",
      (ev.get("per_strategy") or {}).get("S1", {}).get("total") == 3, str(ev.get("per_strategy")))
check("duplicate suppression is reported as active",
      ev.get("duplicate_suppression_active") is True, str(ev.get("warning")))

# ------------------------------- 3. backtest and forward evidence separable
core._record_learning_trade("INDIA", {
    "Ticker": "FWDSYM", "Strategy": "S1", "Entry Date": "2026-05-05", "Score": 90.0,
    "Regime": "BULL", "HTF": 10.0, "Footprint": 10.0, "Strategy Score": 20.0,
    "Entry Quality": 7.0, "Relative Strength": 5.0, "Safety": 90.0,
    "Entry": 10.0, "Exit": 12.0, "R": 2.0, "Outcome": "WIN",
}, source="forward")

fwd = guard("forward evidence can be read on its own",
            lambda: core.learning_snapshot("INDIA", source="forward"))
bts = guard("backtest evidence can be read on its own",
            lambda: core.learning_snapshot("INDIA", source="backtest"))
if fwd is not None:
    check("forward evidence can be read on its own",
          len(fwd) == 1 and fwd.iloc[0].symbol == "FWDSYM", f"{len(fwd)} rows")
if bts is not None:
    check("backtest evidence can be read on its own", len(bts) == 3, str(len(bts)))
check("and they are not pooled by default into one undifferentiated blob",
      len(core.learning_snapshot("INDIA")) == 4, str(len(core.learning_snapshot("INDIA"))))

ev = guard("evidence counts survive a mixed table",
           lambda: core.learning_evidence_counts("INDIA"), {}) or {}
_s1 = (ev.get("per_strategy") or {}).get("S1", {})
check("the split is reported per strategy",
      _s1.get("backtest") == 3 and _s1.get("forward") == 1, str(ev.get("per_strategy")))

# re-recording the same forward trade must not double it either
core._record_learning_trade("INDIA", {
    "Ticker": "FWDSYM", "Strategy": "S1", "Entry Date": "2026-05-05", "Score": 90.0,
    "Regime": "BULL", "HTF": 10.0, "Footprint": 10.0, "Strategy Score": 20.0,
    "Entry Quality": 7.0, "Relative Strength": 5.0, "Safety": 90.0,
    "Entry": 10.0, "Exit": 12.0, "R": 2.0, "Outcome": "WIN",
}, source="forward")
guard("re-recording the same forward trade does not double it", lambda: check(
    "re-recording the same forward trade does not double it",
    len(core.learning_snapshot("INDIA", source="forward")) == 1,
    str(len(core.learning_snapshot("INDIA", source="forward")))))

# ------------------------------------------- 4. the fits inherit the filter
# adaptive_edge_table/current_candidate_edge read through learning_snapshot, so
# a contaminated row must not be able to reach a confidence verdict.
wipe()
con = core._db()
try:
    # On the unfixed code there is no engine_version column, so the statement and
    # its bindings have to match whichever schema is actually present - the
    # point of the section is what the FIT does with these rows, and a binding
    # mismatch here would abort before reaching it.
    has_version = "engine_version" in {
        r[1] for r in con.execute("PRAGMA table_info(learning_observations)").fetchall()}
    if has_version:
        con.executemany(
            """INSERT INTO learning_observations(created_at,market,symbol,strategy,signal_time,
               score,result_r,outcome,source,engine_version)
               VALUES('2025-01-01','INDIA',?,'S1',?,92.0,5.0,'WIN','backtest',?)""",
            [(f"OLD{i}", f"2025-02-{i+1:02d}", legacy_tag) for i in range(60)])
    else:
        con.executemany(
            """INSERT INTO learning_observations(created_at,market,symbol,strategy,signal_time,
               score,result_r,outcome,source)
               VALUES('2025-01-01','INDIA',?,'S1',?,92.0,5.0,'WIN','backtest')""",
            [(f"OLD{i}", f"2025-02-{i+1:02d}") for i in range(60)])
    con.commit()
finally:
    con.close()
edge_r, conf = core.current_candidate_edge("INDIA", "S1", 92.0)
check("60 pre-fix rows cannot produce a confident edge",
      conf in ("NO LEARNING DATA", "INSUFFICIENT SAMPLE"), f"{conf} / {edge_r}")
check("and the edge they would have produced is not applied", edge_r == 0.0, str(edge_r))

# ---------------------------------------------- 5. the dead code is gone
check("the duplicate scorer setup_score() is removed", not hasattr(core, "setup_score"))
check("final_setup_score() - the live one - remains", hasattr(core, "final_setup_score"))
check("the never-called _feature_cache_key() is removed", not hasattr(core, "_feature_cache_key"))

# FEATURE_CACHE_VERSION must actually participate in the cache key now.
frame = pd.DataFrame({"open": [1.0]*300, "high": [1.0]*300, "low": [1.0]*300,
                      "close": [1.0]*300, "volume": [100]*300},
                     index=pd.date_range("2024-01-01", periods=300, freq="D"))
calls = {"n": 0}


def counting_features(df):
    calls["n"] += 1
    return df


real_features = core.features
core.features = counting_features
try:
    guard("the versioned cache wrapper exists",
          lambda: core._features_cached_versioned.clear())
    core.features_cached("X", frame)
    core.features_cached("X", frame)
    check("the same version + frame hits the cache", calls["n"] == 1, str(calls["n"]))
    saved_version = core.FEATURE_CACHE_VERSION
    core.FEATURE_CACHE_VERSION = saved_version + "_BUMPED"
    core.features_cached("X", frame)
    check("bumping FEATURE_CACHE_VERSION really does invalidate", calls["n"] == 2, str(calls["n"]))
    core.FEATURE_CACHE_VERSION = saved_version
finally:
    core.features = real_features

# --------------------------------- 6. one schema, not two divergent copies
core.ensure_engine_tables()
con = core._db()
try:
    cols = {r[1] for r in con.execute("PRAGMA table_info(learning_observations)").fetchall()}
finally:
    con.close()
check("the table keeps the signal_time schema the writers use", "signal_time" in cols)
check("the divergent signal_dt copy did not win", "signal_dt" not in cols, str(sorted(cols)))
check("engine_version is a real column", "engine_version" in cols)

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
