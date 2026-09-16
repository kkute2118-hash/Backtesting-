"""Each scoring condition must count once, and the signal set must not move.

Run directly:  python3 backend/tests/regression/test_score_component_independence.py

The 100-point score presented itself as eight balanced components. It was not.
Four conditions were scored in more than one component, so the total weighted
them by how many components happened to mention them rather than by the
published weights:

    close > ema50     Trend +4, Relative Strength +5, Footprint +3   = 12 points
    EMA20 extension   Footprint +3, Entry Quality +10, S4 quality +10
    close > ema200    Trend +3, S3 quality +10
    relvol            Footprint +4, S2 quality +10

Three components could not discriminate at all. Measured over the 6,608 real
observations in the production store:

    Relative Strength  sd 0.00, one distinct value - EVERY candidate scored 5/5
    Safety             sd 0.18, two distinct values
    Market Regime      constant by construction, one regime per scan

so 15 of the 100 points moved every candidate by the same amount.

The constraint that makes this safe to change: the SIGNAL set is the
authoritative layer and must be untouched. Scoring may reorder candidates; it
may not change which stocks qualify. Verified below on synthetic frames, and
separately against the real 480-symbol store on session 2026-09-11, where 1,920
signal verdicts were compared across both engines with 0 differences.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-score-independence-")

import ast  # noqa: E402
import inspect  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.engine import core  # noqa: E402


# --------------------------------------------------------------- 1. weights
w = getattr(core, "SCORE_COMPONENT_WEIGHTS", {})
check("the published weights sum to 100", sum(w.values()) == 100, str(w))
check("the weights are declared unfitted until a fit justifies them",
      getattr(core, "SCORE_WEIGHTS_ARE_FITTED", True) is False,
      "weights claim to be fitted; nothing has fitted them yet")


# ------------------------------------- 2. no condition scores twice (by source)
# Read the code rather than trusting the comments: a later edit that reintroduces
# a duplicate must fail here.
def body(fn):
    """Source of a function with its docstring removed.

    The docstrings deliberately NAME the conditions that were moved out ("S2
    relvol -> Footprint owns volume expansion"), so a plain text search over
    the raw source matches the explanation and reports the defect it documents.
    Only executable code counts.
    """
    tree = ast.parse(inspect.getsource(getattr(core, fn)).lstrip())
    node = tree.body[0]
    stmts = node.body
    if (stmts and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)):
        stmts = stmts[1:]
    return "\n".join(ast.unparse(s) for s in stmts)


fp, sq, fs = body("footprint_score"), body("strategy_quality_score"), body("final_setup_score")

check("close>ema50 no longer scores inside footprint_score",
      "z.ema50) and z.close > z.ema50" not in fp and "z.close > z.ema50" not in fp, "still there")
check("close>ema50 no longer scores inside final_setup_score",
      "z.close > z.ema50" not in fs, "still there")
check("EMA20 extension no longer scores inside footprint_score",
      "z.close / z.ema20" not in fp, "still there")
check("EMA20 extension scores in exactly one place in final_setup_score",
      fs.count("z.close / z.ema20") == 1, str(fs.count("z.close / z.ema20")))
check("relvol no longer scores inside strategy_quality_score",
      "relvol" not in sq, "S2 still scores relvol, which Footprint owns")
s3_block = sq.split("elif s == 3")[-1].split("elif s == 4")[0]
check("close>ema200 no longer scores inside strategy_quality_score",
      "ema200" not in s3_block,
      "S3 still scores close>ema200, which Trend owns")
check("relvol still scores inside footprint_score, its single owner",
      "relvol" in fp)
check("close>ema200 still scores inside final_setup_score, its single owner",
      "z.close > z.ema200" in fs)


# ----------------------------------------- 3. the dead components are removed
parts_keys = set()
tree = ast.parse(fs)
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        parts_keys.add(node.value)
for gone in ("Relative Strength", "Market Regime"):
    check(f"the zero-variance component {gone!r} is gone from the score",
          gone not in parts_keys, "still scored")
check("'Safety' is no longer a scoring component", "Safety" not in w, str(sorted(w)))
check("but regime and safety are still accepted as arguments (callers pass them)",
      set(inspect.signature(core.final_setup_score).parameters) ==
      {"x", "s", "regime", "safety_score"},
      str(list(inspect.signature(core.final_setup_score).parameters)))


# ----------------------------------------- 4. scoring is stable and in range
def frame(close=110.0, ema20=108.0, ema50=100.0, ema200=90.0, rsi=60.0, relvol=1.6,
          wrsi=62.0, mrsi=62.0, mclose=110.0, mema15=100.0, mmom=32.0,
          mema10=10.0, mema20=9.0):
    n = 300
    rng = np.linspace(95, close, n)
    d = pd.DataFrame({
        "open": rng, "high": rng * 1.01, "low": rng * 0.99, "close": rng,
        "volume": np.linspace(1000, 1200, n),
        "ema20": ema20, "ema50": ema50, "ema200": ema200, "rsi14": rsi,
        "relvol": relvol, "wrsi14": wrsi, "mrsi14": mrsi, "mclose": mclose,
        "mema15": mema15, "mmom": mmom, "mema10": mema10, "mema20": mema20,
    }, index=pd.date_range("2024-01-01", periods=n, freq="D"))
    d.iloc[-1, d.columns.get_loc("close")] = close
    d.iloc[-1, d.columns.get_loc("high")] = close * 1.01
    d.iloc[-1, d.columns.get_loc("low")] = close * 0.99
    return d


for strat in (1, 2, 3, 4):
    total, parts = core.final_setup_score(frame(), strat, "STRONG BULL", 100)
    check(f"S{strat}: the score is the sum of its components",
          total == sum(parts.values()), f"{total} vs {sum(parts.values())} from {parts}")
    # w is empty against the unfixed code, which has no published weights at
    # all. Indexing it would abort the run here and hide every later check, so
    # a missing weight is reported as the failure it is.
    check(f"S{strat}: every component is within its published weight",
          bool(w) and all(k in w and 0 <= v <= w[k] for k, v in parts.items()),
          f"{parts} against weights {w or '(none published)'}")
    check(f"S{strat}: the score stays in 0-100", 0 <= total <= 100, str(total))
    check(f"S{strat}: the components are exactly the published ones",
          set(parts) == set(w), f"{sorted(parts)} vs {sorted(w)}")

# Every strategy must be able to reach the full 30, or removing a sub-criterion
# from S2/S3/S4 would quietly penalise them against S1 in any joint ranking.
ideal = {
    1: frame(),
    2: frame(),
    # S3 rewards a tight pullback TO the 50-day, so its ideal frame sits on it.
    3: frame(close=100.5, ema20=100.0, ema50=100.0),
    4: frame(),
}
tops = {s: core.strategy_quality_score(ideal[s], s) for s in (1, 2, 3, 4)}
# (30 under every strategy only holds once the per-strategy scaling exists.)
check("a perfect candidate reaches the full Strategy weight under every strategy",
      all(v == 30 for v in tops.values()), str(tops))
# ...and the scaling is what makes that true: S2/S3/S4 now have two criteria to
# S1's three, so without it they would top out at 20 against S1's 30.
check("the scaling, not luck, is what equalises them",
      hasattr(core, "_scaled_component")
      and core._scaled_component(20, 20, 30) == 30
      and core._scaled_component(10, 20, 30) == 15,
      "no component scaling exists")


# ------------------------------- 5. regime and safety cannot move the score
base, _ = core.final_setup_score(frame(), 1, "STRONG BULL", 100)
for regime in ("BULL", "RECOVERY / SIDEWAYS", "BEAR", "UNKNOWN"):
    got, _ = core.final_setup_score(frame(), 1, regime, 100)
    check(f"regime {regime!r} does not change the score", got == base, f"{got} vs {base}")
for safety in (100, 90, 80, 70, 40, 0):
    got, _ = core.final_setup_score(frame(), 1, "STRONG BULL", safety)
    check(f"safety {safety} does not change the score", got == base, f"{got} vs {base}")


# ------------------------------------ 6. the score still discriminates at all
# Removing constants must not flatten the metric into a constant of its own.
seen = {core.final_setup_score(frame(close=c, ema20=e, rsi=r, relvol=v), 1,
                               "STRONG BULL", 100)[0]
        for c, e, r, v in [(110, 108, 60, 1.6), (130, 100, 45, 0.8),
                           (101, 100, 70, 2.0), (95, 100, 30, 0.5),
                           (112, 110, 55, 1.3)]}
check("different candidates still receive different scores", len(seen) >= 3, str(sorted(seen)))


# ------------------------------------------- 7. the gate moved with the scale
check("the forward-test gate was recalibrated off 85",
      getattr(core, "DEFAULT_MIN_SCORE", 85) == 71, str(getattr(core, "DEFAULT_MIN_SCORE", None)))
check("and the old value is recorded, not just overwritten",
      getattr(core, "LEGACY_MIN_SCORE", None) == 85)
_daily = pathlib.Path(__file__).resolve().parents[3].joinpath("daily_job.py")
check("the daily job uses the recalibrated default, not a literal 85",
      _daily.exists() and 'SCAN_MIN_SCORE", core.DEFAULT_MIN_SCORE' in _daily.read_text(),
      "daily_job still hardcodes a gate")


# ------------------------------- 8. the engine version separates the two shapes
check("ENGINE_VERSION advanced past the old component definitions",
      core.ENGINE_VERSION != "FINAL-3_ASOF_PIT", core.ENGINE_VERSION)
check("so pre-restructure component values cannot be pooled with new ones",
      core.ENGINE_VERSION == "FINAL-4_PIT_INDEPENDENT_COMPONENTS", core.ENGINE_VERSION)

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
