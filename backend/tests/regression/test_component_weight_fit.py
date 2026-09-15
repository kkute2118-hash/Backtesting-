"""Weights must come from a fit that reports its own uncertainty — or not at all.

Run directly:  python3 backend/tests/regression/test_component_weight_fit.py

The weighting method being replaced was adaptive_component_weights(): split each
component at its median, compare mean R of the two halves, and nudge the weight
by np.clip(1.0 + edge*0.25, 0.70, 1.35). No significance test, no collinearity
handling, and a median split discards the ordering inside each half. Its
"Samples" column reported the size of the whole strategy group rather than of
the split the number was computed from, so a nudge derived from five
observations advertised several thousand.

A replacement that always answers "insufficient sample" would be no better than
one that always answers with a number, so the checks below run it BOTH ways:
against a planted, genuine effect it must find it and call it significant;
against pure noise at the same sample size it must decline to weight anything.
That is the only way to know the refusal means something.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-component-fit-")

import numpy as np  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.engine import core  # noqa: E402

core.maybe_backup_db = lambda *a, **k: None
core.ensure_learning_tables()
RNG = np.random.default_rng(7)


def wipe():
    con = core._db()
    try:
        con.execute("DELETE FROM learning_observations")
        con.commit()
    finally:
        con.close()


def plant(n, strategy="S1", effect_on=None, effect=0.0, version=None, source="backtest"):
    """Write n observations. `effect` is the true R per unit of `effect_on`."""
    version = version or core.ENGINE_VERSION
    rows = []
    for i in range(n):
        comps = {
            "strategy_score": float(RNG.integers(18, 34)),
            "htf": float(RNG.integers(6, 23)),
            "footprint": float(RNG.integers(6, 23)),
            "entry_quality": float(RNG.integers(0, 12)),
            "trend": float(RNG.integers(0, 13)),
        }
        r = float(RNG.normal(-0.12, 1.4))
        if effect_on:
            r += effect * (comps[effect_on] - 15.0)
        rows.append((
            f"2026-01-01T00:00:{i%60:02d}", "INDIA", f"SYM{i}", strategy,
            f"2025-{(i%12)+1:02d}-{(i%27)+1:02d}", 70.0 + i % 20, "BULL",
            comps["htf"], comps["footprint"], comps["strategy_score"],
            comps["entry_quality"], r, "WIN" if r > 0 else "LOSS", source,
            version, comps["trend"]))
    con = core._db()
    try:
        con.executemany(
            """INSERT OR REPLACE INTO learning_observations(
               created_at,market,symbol,strategy,signal_time,score,regime,htf,footprint,
               strategy_score,entry_quality,result_r,outcome,source,engine_version,trend)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        con.commit()
    finally:
        con.close()


# ---------------------------------------- 1. it refuses below the sample bar
wipe()
plant(40)
rep = core.fit_component_weights()
s1 = rep["strategies"].get("S1", {})
check("a thin sample is refused, not fitted", s1.get("fitted") is False, str(s1)[:160])
check("the refusal names the sample size and the bar",
      "40" in (s1.get("reason") or "") and str(rep["min_samples"]) in (s1.get("reason") or ""),
      str(s1.get("reason")))
check("and no weight is claimed to be fitted", rep["weights_are_fitted"] is False)
check("the published weights are reported unchanged",
      rep["current_weights"] == dict(core.SCORE_COMPONENT_WEIGHTS))

# --------------------------- 2. a REAL effect at a real sample size is found
wipe()
plant(1200, effect_on="footprint", effect=0.06)
rep = core.fit_component_weights()
s1 = rep["strategies"]["S1"]
check("a sample above the bar is fitted", s1.get("fitted") is True, str(s1.get("reason")))
by = {c["component"]: c for c in s1["components"]}
fp = by.get("Footprint", {})
check("the planted effect is detected", fp.get("significant") is True,
      f"p={fp.get('p_value')} coef={fp.get('coef_r_per_sd')}")
check("with the right sign", (fp.get("coef_r_per_sd") or 0) > 0, str(fp.get("coef_r_per_sd")))
check("its confidence interval excludes zero",
      fp.get("ci95", [0, 0])[0] > 0, str(fp.get("ci95")))
check("the verdict names the component that qualified",
      "Footprint" in (s1.get("verdict") or ""), str(s1.get("verdict")))
check("components that did NOT clear the bar are listed as neutral",
      len(s1["neutral_components"]) >= 1, str(s1["neutral_components"]))
check("every component reports n, p, CI and VIF",
      all({"n", "p_value", "ci95", "vif"} <= set(c) for c in s1["components"]))
check("the logistic fit is reported alongside the linear one",
      "logit_p_value" in fp, str(sorted(fp)))
check("collinearity is reported, not assumed away",
      bool(s1["collinearity"].get("vif")) and bool(s1["collinearity"].get("correlation")))
check("independent components show low VIF",
      all(v < 5 for v in s1["collinearity"]["vif"].values()),
      str(s1["collinearity"]["vif"]))

# ------------------- 3. the SAME sample size with no effect finds nothing
wipe()
plant(1200, effect_on=None, effect=0.0)
rep = core.fit_component_weights()
s1 = rep["strategies"]["S1"]
check("pure noise at the same sample size is still fitted (it ran)", s1["fitted"] is True)
sig = [c["component"] for c in s1["components"] if c["significant"]]
check("but nothing is declared significant", not sig, f"claimed: {sig}")
check("and the verdict says so in words",
      "No component clears" in (s1.get("verdict") or ""), str(s1.get("verdict")))
check("so the weights remain unfitted", rep["weights_are_fitted"] is False, str(rep.get("reason")))
check("every component is listed as neutral",
      len(s1["neutral_components"]) == len(s1["components"]), str(s1["neutral_components"]))

# the live overlay must not move a score off an unfitted result
parts = {"HTF Demand": 20, "Footprint": 20, "Strategy": 30, "Entry Quality": 10, "Trend": 12}
check("the scan overlay returns the base score when nothing qualified",
      core.adaptive_candidate_score(80.0, "INDIA", "S1", parts) == 80.0,
      str(core.adaptive_candidate_score(80.0, "INDIA", "S1", parts)))

# ...but it DOES move when a real effect exists
wipe()
plant(1200, effect_on="footprint", effect=0.06)
moved = core.adaptive_candidate_score(80.0, "INDIA", "S1", parts)
check("and it does move when a component genuinely qualified", moved != 80.0, str(moved))
check("the move stays bounded to 0-100", 0 <= moved <= 100, str(moved))

# ------------------------- 4. pre-version rows cannot reach the fit
wipe()
plant(1200, effect_on="footprint", effect=0.30, version=core.LEGACY_ENGINE_VERSION)
rep = core.fit_component_weights()
check("a huge effect in pre-fix rows is invisible to the fit",
      rep["strategies"] == {} or all(not e.get("fitted") for e in rep["strategies"].values()),
      str(rep["strategies"])[:200])
check("and the reason names the engine version",
      core.ENGINE_VERSION in (rep.get("reason") or ""), str(rep.get("reason")))

# ------------------------- 5. backtest and forward evidence fit separately
wipe()
plant(1200, effect_on="footprint", effect=0.06, source="backtest")
plant(300, effect_on=None, source="forward")
both = core.fit_component_weights()
bt = core.fit_component_weights(source="backtest")
fw = core.fit_component_weights(source="forward")
check("the pooled fit sees everything", both["strategies"]["S1"]["n"] == 1500,
      str(both["strategies"]["S1"]["n"]))
check("the backtest-only fit sees only replay", bt["strategies"]["S1"]["n"] == 1200,
      str(bt["strategies"]["S1"]["n"]))
check("the forward-only fit sees only the reality check",
      fw["strategies"]["S1"]["n"] == 300, str(fw["strategies"]["S1"]["n"]))
check("and the forward sample is refused at 300 against a 200 bar only if it clears it",
      fw["strategies"]["S1"]["fitted"] is True, str(fw["strategies"]["S1"].get("reason")))
check("the source is recorded in the report", bt["source"] == "backtest" and fw["source"] == "forward")

# ---------------------------------- 6. a constant component is named, not weighted
wipe()
plant(1200)
con = core._db()
try:
    con.execute("UPDATE learning_observations SET trend=7")
    con.commit()
finally:
    con.close()
rep = core.fit_component_weights()
s1 = rep["strategies"]["S1"]
check("a component that never varies is named as constant",
      "Trend" in (s1.get("constant_components") or []), str(s1.get("constant_components")))
check("and is not given a coefficient",
      "Trend" not in {c["component"] for c in s1["components"]},
      str([c["component"] for c in s1["components"]]))

# --------------- 7. one absent component must not empty the whole fit
# A build older than a column writes NULL for it. Requiring every component to
# be present then drops every row and reports "0 rows with a complete component
# breakdown" — which reads as no data at all, rather than as one column needing
# a backfill. This happened for real with `trend`.
wipe()
plant(1200, effect_on="footprint", effect=0.06)
con = core._db()
try:
    con.execute("UPDATE learning_observations SET trend=NULL")
    con.commit()
finally:
    con.close()
rep = core.fit_component_weights()
s1 = rep["strategies"]["S1"]
check("the fit still runs when one component was never recorded",
      s1.get("fitted") is True, str(s1.get("reason")))
check("the absent component is named", "Trend" in (s1.get("missing_components") or []),
      str(s1.get("missing_components")))
check("and the remaining components are still fitted",
      {"Footprint", "HTF Demand"} <= {c["component"] for c in s1["components"]},
      str([c["component"] for c in s1["components"]]))
check("the planted effect survives the missing column",
      any(c["component"] == "Footprint" and c["significant"] for c in s1["components"]),
      str([(c["component"], c["p_value"]) for c in s1["components"]]))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
