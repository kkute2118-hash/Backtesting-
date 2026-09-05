"""Every universe picker must reach the full ~2000-name NSE list.

Run directly:  python3 backend/tests/regression/test_universe.py
No network: index_universe and dhan_map are stubbed.

The UI half of this test was rewritten during the web migration: there is no
longer a Streamlit file full of copy-pasted pickers to grep, because every
picker in the web app renders whatever GET /universes returns. The invariant is
the same one - no caller may reach past the single UNIVERSE_CHOICES list - it is
just asserted at the source now.
"""
# Run from the repository root:  python -m pytest backend/tests
# or directly:                    python backend/tests/regression/<name>.py
#
# These predate the web migration and are kept script-shaped on purpose: each
# one reproduces a specific incident, and rewriting them into pytest idiom would
# risk losing the exact conditions that caught it. test_regression_scripts.py
# runs them all under pytest.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, re, sys, tempfile

os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ.setdefault("DHAN_ACCESS_TOKEN", "x")

from app.engine import core

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

# ------------------------------------ 3. no caller is left with a hardcoded list
ROOT = pathlib.Path(__file__).resolve().parents[3]

job = (ROOT / "daily_job.py").read_text()
check("daily_job resolves through core.resolve_universes",
      "core.resolve_universes(" in job and "core.index_universe(" not in job)

# Resolving through the engine is not enough on its own: _universes() validates
# SCAN_UNIVERSE before it ever reaches resolve_universes(), and that allowlist
# used to be a hand-copied set of the four index names. It silently dropped the
# full-NSE option that this file's own docstring tells you to use, and the check
# above passed the whole time. Exercise the function, not the source.
sys.path.insert(0, str(ROOT))
import daily_job  # noqa: E402

_saved_scan_universe = os.environ.get("SCAN_UNIVERSE")
try:
    os.environ["SCAN_UNIVERSE"] = core.FULL_NSE_UNIVERSE
    check("SCAN_UNIVERSE accepts the full-NSE option",
          daily_job._universes() == [core.FULL_NSE_UNIVERSE], str(daily_job._universes()))

    os.environ["SCAN_UNIVERSE"] = "Nifty 500|Nifty Midcap 150"
    check("SCAN_UNIVERSE accepts several names joined with |",
          daily_job._universes() == ["Nifty 500", "Nifty Midcap 150"], str(daily_job._universes()))

    os.environ["SCAN_UNIVERSE"] = "Nifty 5000"
    check("an unknown name falls back to Nifty 500",
          daily_job._universes() == ["Nifty 500"], str(daily_job._universes()))

    for _name in core.UNIVERSE_CHOICES:
        os.environ["SCAN_UNIVERSE"] = _name
        check(f"SCAN_UNIVERSE accepts {_name!r}",
              daily_job._universes() == [_name], str(daily_job._universes()))
finally:
    if _saved_scan_universe is None:
        os.environ.pop("SCAN_UNIVERSE", None)
    else:
        os.environ["SCAN_UNIVERSE"] = _saved_scan_universe

# The bootstrap job is the only way to build history on a host that cannot do
# it itself, so the workflow and the CLI have to stay in step.
check("daily_job exposes a bootstrap job", '"bootstrap"' in job and "def run_bootstrap" in job)
_workflow = (ROOT / ".github" / "workflows" / "build-history.yml")
check("the build-history workflow exists", _workflow.exists())
if _workflow.exists():
    _wf = _workflow.read_text()
    check("it runs the bootstrap job", "daily_job.py bootstrap" in _wf)
    check("its universe dropdown offers every engine universe",
          all(n in _wf for n in core.UNIVERSE_CHOICES))

# The UI no longer has ten copy-pasted pickers to audit: every picker in the web
# app renders whatever GET /universes returns, and that endpoint is built from
# UNIVERSE_CHOICES. Assert the single source of truth instead of the widgets.
from app.services import universe as universe_service  # noqa: E402

offered = [u["name"] for u in universe_service.choices()]
check("the API offers every universe the engine knows",
      offered == list(core.UNIVERSE_CHOICES), str(offered))
check("the full-NSE option is flagged as needing Dhan",
      next(u["requires_dhan"] for u in universe_service.choices()
           if u["name"] == core.FULL_NSE_UNIVERSE))
check("the index universes are not flagged as needing Dhan",
      not any(u["requires_dhan"] for u in universe_service.choices()
              if u["name"] != core.FULL_NSE_UNIVERSE))

api = (ROOT / "backend" / "app" / "api" / "v1" / "endpoints").rglob("*.py")
sources = "\n".join(p.read_text() for p in api)
check("no endpoint calls index_universe directly",
      not re.search(r"(?<!resolve_)\bindex_universe\(", sources))

# ------------------------- 4. adding the option must not change any default
frontend = (ROOT / "frontend" / "src").rglob("*.ts*")
ui = "\n".join(p.read_text() for p in frontend)
check("the scanner's default universe is still Nifty 500",
      'universes: ["Nifty 500"]' in ui, "DEFAULT_SCAN")
check("no shipped preset defaults to the full NSE list except the sweep",
      sum(1 for preset in __import__("app.db.app_store", fromlist=["x"]).BUILTIN_PRESETS
          if core.FULL_NSE_UNIVERSE in preset["config"]["universes"]) == 1)

# ---------------------- 5. the real cap: cache coverage must be reported
check("the scan reports how many stocks it could actually load",
      '"loaded": loaded' in (ROOT / "backend" / "app" / "services" / "scanner.py").read_text())
check("the results page shows loaded-vs-universe to the user",
      "stocks with enough history" in ui)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All universe checks passed.")
