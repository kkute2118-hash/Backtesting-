"""Every universe picker must reach the full ~2000-name NSE list.

Run directly:  python3 test_universe.py
No network: index_universe and dhan_map are stubbed.
"""
import os, sys, re, tempfile

os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ.setdefault("DHAN_ACCESS_TOKEN", "x")

import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------- 1. the choice list
check("full-NSE option exists", core.FULL_NSE_UNIVERSE in core.UNIVERSE_CHOICES,
      str(core.UNIVERSE_CHOICES))
check("it is offered first", core.UNIVERSE_CHOICES[0] == core.FULL_NSE_UNIVERSE)
check("the four index lists are still offered",
      all(n in core.UNIVERSE_CHOICES for n in core.INDEX_URLS), str(core.UNIVERSE_CHOICES))

# ------------------------------------------------------------- 2. resolution
core.dhan_map = lambda: {f"SYM{i}": str(i) for i in range(2000)} | {"TINYSM": "9"}
core.index_universe = lambda name: [f"IDX{i}.NS" for i in range(500)]

full = core.resolve_universe(core.FULL_NSE_UNIVERSE)
check("full NSE resolves to ~2000 names", len(full) >= 1900, str(len(full)))
check("SME scrips are excluded", "TINYSM.NS" not in full)
check("index name still resolves to its CSV",
      len(core.resolve_universe("Nifty 500")) == 500)
check("union de-duplicates across names",
      len(core.resolve_universes([core.FULL_NSE_UNIVERSE, core.FULL_NSE_UNIVERSE])) == len(full))

# Without Dhan credentials the full list is impossible; the error must say so.
_configured = core.dhan_configured
core.dhan_configured = lambda: False
try:
    core.resolve_universe(core.FULL_NSE_UNIVERSE)
    check("missing Dhan credentials raise a clear error", False, "no exception")
except RuntimeError as exc:
    check("missing Dhan credentials raise a clear error", "Dhan credentials" in str(exc), str(exc)[:120])
core.dhan_configured = _configured

# ------------------------------------------- 3. no picker is left hardcoded
app = open("app.py").read()
check("no hardcoded four-item universe list remains",
      '"Nifty Midcap 150"]' not in app,
      re.findall(r'.{0,60}"Nifty Midcap 150"\]', app)[:2])
check("app.py never calls index_universe directly",
      not re.search(r'(?<!resolve_)\bindex_universe\(', app))
check("every picker uses UNIVERSE_CHOICES",
      app.count("UNIVERSE_CHOICES") >= 10, str(app.count("UNIVERSE_CHOICES")))
check("SEPA tab no longer hardcodes nse_liquid_universe()",
      "sepa_tickers = resolve_universe(" in app)

job = open("daily_job.py").read()
check("daily_job resolves through core.resolve_universes",
      "core.resolve_universes(" in job and "core.index_universe(" not in job)

# ------------------------- 4. adding the option must not change any default
check("selectboxes are pinned to Nifty 500",
      app.count('index=UNIVERSE_CHOICES.index("Nifty 500")') == 3,
      str(app.count('index=UNIVERSE_CHOICES.index("Nifty 500")')))
check("scanner default stays the index universes, not all 2000",
      "[u for u in UNIVERSE_CHOICES if u != FULL_NSE_UNIVERSE]" in app)
check("multiselect defaults still say Nifty 500",
      app.count('default=["Nifty 500"]') + app.count('["Nifty 500"],\n        key="radar_universes"') >= 3)

# ---------------------- 5. the real cap: cache coverage must be reported
check("scanner warns when the cache covers fewer stocks than selected",
      "have no local candles" in app)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All universe checks passed.")
