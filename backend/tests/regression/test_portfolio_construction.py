"""Pick a SET, size it honestly, and never double an exposure.

Run directly:  python3 backend/tests/regression/test_portfolio_construction.py

The scan returns ~225 qualified signals and three independent studies agree
that nothing measurable at signal time separates the winners. So the useful
question is not "which candidate is best" but "which set, at what size".

Measured on 2,371 point-in-time trades, expectancy is flat in position count
while the spread collapses — sd of the monthly return goes 1.536 at one
position to 0.531 at twenty. Breadth is the improvement the evidence supports;
concentration is risk bought with nothing.

Three things this has to get right, each of which quietly ruins an account:

1. Equal-risk sizing alone is leverage in disguise. On a 7% stop, risking 1% of
   capital implies a position worth ~14% of it, so twenty of them is ~2.9x
   geared. The notional cap must bind, and the summary must report the risk
   that RESULTS (about 0.34%) rather than the risk that was REQUESTED (1%).

2. The same stock qualifying under two strategies is one exposure, not two.
   Sizing it twice doubles the risk with nothing on screen to show it.

3. Ordering must not imply a forecast. Selection is by liquidity — a cost
   measure — because the score does not predict outcome and inside a single
   strategy it ranks slightly backwards.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-portfolio-")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.engine import core  # noqa: E402

RNG = np.random.default_rng(3)


def frames(tickers, n=90, driver=None):
    """Price frames. `driver` injects a shared factor to create correlation."""
    out = {}
    base = RNG.normal(0, 0.01, n) if driver is None else driver
    for i, t in enumerate(tickers):
        noise = RNG.normal(0, 0.012, n)
        r = base * (driver is not None) + noise
        close = 100 * np.exp(np.cumsum(r))
        out[t] = pd.DataFrame(
            {"open": close, "high": close * 1.01, "low": close * 0.99,
             "close": close, "volume": np.full(n, 1_000_000.0 * (i + 1))},
            index=pd.date_range("2026-01-01", periods=n, freq="D"))
    return out


def candidates(tickers, entry=100.0, stop_pct=0.93, strategy="S1"):
    return pd.DataFrame([{"Ticker": t, "Strategy": strategy, "Score": 75,
                          "Entry": entry, "SL 7%": round(entry * stop_pct, 2)}
                         for t in tickers])


TICKERS = [f"SYM{i:02d}" for i in range(40)]
DATA = frames(TICKERS)

# ------------------------- 1. equal-risk sizing alone would be leverage
pf = core.build_portfolio(candidates(TICKERS), data=DATA, capital=1_000_000,
                          risk_pct=1.0, max_positions=20)
s = pf["summary"]
check("twenty slots are filled", s["selected"] == 20, str(s["selected"]))
check("the notional cap binds, not the risk budget",
      s["binding_constraint"] == "notional", str(s["binding_constraint"]))
check("exposure stays within capital — no accidental leverage",
      s["exposure_pct_of_capital"] <= 100.5, f"{s['exposure_pct_of_capital']}%")
check("the ACTUAL risk per position is reported, not the requested one",
      0.2 < s["risk_pct_actual_per_position"] < 0.5,
      f"requested {s['risk_pct_requested']}%, actual {s['risk_pct_actual_per_position']}%")
check("and it is materially below what was asked for",
      s["risk_pct_actual_per_position"] < s["risk_pct_requested"] / 2,
      "the gap between requested and actual risk is the whole point")
check("the discrepancy is explained in words, not left to be discovered",
      "binds" in (s.get("note") or ""), str(s.get("note")))
check("no leverage warning is raised when there is no leverage", "warning" not in s, str(s.get("warning")))

# raising risk_pct must NOT change the size while the notional cap binds
pf2 = core.build_portfolio(candidates(TICKERS), data=DATA, capital=1_000_000,
                           risk_pct=5.0, max_positions=20)
check("raising risk_pct alone does not change position size",
      pf2["summary"]["total_exposure"] == s["total_exposure"],
      f"{pf2['summary']['total_exposure']} vs {s['total_exposure']}")

# ...but a wide enough stop makes the RISK budget bind instead
wide = candidates(TICKERS, stop_pct=0.50)          # a 50% stop
pf3 = core.build_portfolio(wide, data=DATA, capital=1_000_000, risk_pct=0.25,
                           max_positions=20)
check("a wide stop makes the risk budget bind instead",
      pf3["summary"]["binding_constraint"] == "risk", str(pf3["summary"]["binding_constraint"]))

# ------------------------- 2. one symbol is one exposure
dup = pd.concat([candidates(TICKERS[:5], strategy="S1"),
                 candidates(TICKERS[:5], strategy="S3")], ignore_index=True)
pf4 = core.build_portfolio(dup, data=DATA, capital=1_000_000, max_positions=20)
held = list(pf4["positions"]["Ticker"])
check("a stock qualifying under two strategies is held once",
      len(held) == len(set(held)) == 5, str(held))
check("and the duplicate is reported rather than dropped silently",
      any("another strategy" in x["reason"] for x in pf4["skipped"]),
      str(pf4["skipped"]))

# ------------------------- 3. correlated names are not both taken
shared = RNG.normal(0, 0.02, 90)
corr_data = frames([f"TWIN{i}" for i in range(6)], driver=shared)
corr_data.update(DATA)
pf5 = core.build_portfolio(candidates([f"TWIN{i}" for i in range(6)]),
                           data=corr_data, capital=1_000_000, max_positions=6,
                           max_correlation=0.60)
check("near-duplicate names are not all taken",
      pf5["summary"]["selected"] < 6, f"took all {pf5['summary']['selected']}")
check("and the rejection names the correlation and the holding it clashes with",
      any(x["reason"].startswith("correlation") and " with " in x["reason"]
          for x in pf5["skipped"]), str(pf5["skipped"][:3]))
# a loose threshold must let them through, or the screen is just a position cap
pf6 = core.build_portfolio(candidates([f"TWIN{i}" for i in range(6)]),
                           data=corr_data, capital=1_000_000, max_positions=6,
                           max_correlation=0.999)
check("a loose threshold lets them through — the screen is really correlation",
      pf6["summary"]["selected"] == 6, str(pf6["summary"]["selected"]))

# ------------------------- 4. selection order is liquidity, not Score
# Ranked against MEASURED liquidity rather than against ticker index: volume
# scales with the index but close is a random walk, so close*volume can reorder
# neighbouring names. Asserting the index order would be testing the fixture.
mixed = candidates(TICKERS[:25])
liq = {t: core._portfolio_liquidity(DATA, t) for t in TICKERS[:25]}
ranked = sorted(liq, key=liq.get, reverse=True)
most_liquid, least_liquid = ranked[0], ranked[-1]
# The LEAST liquid name is given the best Score; if Score drove selection it
# would take a slot, and if liquidity drives it, it cannot.
mixed.loc[mixed.Ticker == least_liquid, "Score"] = 100
mixed.loc[mixed.Ticker == most_liquid, "Score"] = 40
pf7 = core.build_portfolio(mixed, data=DATA, capital=1_000_000, max_positions=3)
taken = list(pf7["positions"]["Ticker"])
check("the three most liquid names are taken", set(taken) == set(ranked[:3]),
      f"took {taken}, most liquid are {ranked[:3]}")
check("a high Score does not buy a slot", least_liquid not in taken,
      f"{least_liquid} (Score 100, least liquid) took a slot: {taken}")
check("and the report says ordering is by liquidity, not by score",
      "liquidity" in pf7["summary"]["selection_order"], pf7["summary"]["selection_order"])

# ------------------------- 5. refusals are explicit
bad = candidates(TICKERS[:3])
bad["SL 7%"] = bad["Entry"] * 1.05          # stop ABOVE entry
pf8 = core.build_portfolio(bad, data=DATA, capital=1_000_000)
check("a stop above the entry is refused", pf8["summary"]["selected"] == 0, str(pf8["summary"]))
check("and says why", any("stop is not below" in x["reason"] for x in pf8["skipped"]),
      str(pf8["skipped"]))

pricey = candidates(TICKERS[:2], entry=500_000.0)
pf9 = core.build_portfolio(pricey, data=DATA, capital=1_000_000, max_positions=20)
check("a share costing more than the slot is reported, not sized at zero",
      pf9["summary"]["selected"] == 0
      and any("one share costs more" in x["reason"] for x in pf9["skipped"]),
      str(pf9["skipped"]))

check("an empty scan returns an empty portfolio, not an error",
      core.build_portfolio(pd.DataFrame())["summary"]["selected"] == 0)
check("candidates without a stop column are refused with a reason",
      "SL 7%" in (core.build_portfolio(
          pd.DataFrame([{"Ticker": "A", "Entry": 10}]))["summary"]["reason"]))

# ------------------------- 6. missing price data degrades, never silently
pf10 = core.build_portfolio(candidates(TICKERS[:10]), data=None, capital=1_000_000,
                            max_positions=5)
check("with no price frames it still sizes a portfolio", pf10["summary"]["selected"] == 5,
      str(pf10["summary"]["selected"]))
check("and reports that nothing was correlation-screened",
      pf10["summary"]["correlation_screened"] == 0,
      str(pf10["summary"]["correlation_screened"]))

# ------------------------- 7. breadth is the documented default
check("the default slot count matches the measured variance reduction",
      core.PORTFOLIO_DEFAULT_SLOTS == 20, str(core.PORTFOLIO_DEFAULT_SLOTS))
check("the correlation default is one that can actually bind on this universe",
      core.PORTFOLIO_MAX_CORRELATION == 0.60, str(core.PORTFOLIO_MAX_CORRELATION))
totals = {}
for slots in (1, 5, 20):
    p = core.build_portfolio(candidates(TICKERS), data=DATA, capital=1_000_000,
                             max_positions=slots)
    totals[slots] = p["summary"]["selected"]
check("more slots really do produce more positions", totals == {1: 1, 5: 5, 20: 20}, str(totals))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
