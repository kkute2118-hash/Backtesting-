"""Switching the live overlay on must scan, not crash.

Run directly:  python3 backend/tests/regression/test_live_overlay_scan.py

The incident: core.attach_live_bars() returns a pair — the frames with today's
forming candle merged in, and the bars it managed to fetch. The scanner bound
both to one name:

    data = core.attach_live_bars(data)          # data is now a tuple
    ...
    proxy = max(data.values(), key=len)         # AttributeError

So every scan with "use live prices" ticked died on the line after the fetch,
and the failure looked like the live data never arriving. The try/except around
the call did not help: the call itself succeeded, and the crash landed on the
next statement, outside it.

Also covered: an overlay that fetches nothing must say so rather than quietly
scanning yesterday's close. The live overlay is the reason the caller asked for
this scan; answering with stale prices answers a different question.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os
import tempfile
import types

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-live-overlay-")

import pandas as pd

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


from app.core.errors import ApiError  # noqa: E402
from app.engine import core  # noqa: E402
from app.services import scanner  # noqa: E402


def frames():
    return {f"S{i}.NS": pd.DataFrame({"close": [1.0] * 300}) for i in range(1, 6)}


STATE = {"bars": {f"S{i}.NS".replace(".NS", ""): {"close": 2.0} for i in range(1, 6)},
         "raises": False}

core.load_scan_dataset = lambda t, **k: frames()
core.dhan_configured = lambda: True
core.regime_from_index = lambda d: ("BULL", 60)


def fake_attach(data, symbols=None):
    if STATE["raises"]:
        raise RuntimeError("quote feed unreachable")
    # The real contract: (frames, bars).
    return dict(data), dict(STATE["bars"])


core.attach_live_bars = fake_attach


class Handle:
    def __init__(self):
        self.notes = []

    def progress(self, frac, label=""):
        self.notes.append((frac, label))


# ------------------------------------------ 1. the incident: it must not crash
h = Handle()
try:
    data, regime, score = scanner._load(h, [f"S{i}.NS" for i in range(1, 6)], True)
    ok, err = True, ""
except Exception as exc:
    data, regime, score = None, None, None
    ok, err = False, f"{type(exc).__name__}: {exc}"
check("a scan with the live overlay on completes", ok, err)
check("it returns frames, not the (frames, bars) pair",
      isinstance(data, dict), type(data).__name__)
check("every symbol survived the overlay", data is not None and len(data) == 5,
      str(len(data) if data else None))
check("the regime was read from the merged frames", regime == "BULL", str(regime))
check("the run reports how many stocks got a live price",
      any("Live prices for 5" in label for _f, label in h.notes),
      str([label for _f, label in h.notes]))

# ------------------------------- 2. an overlay that fetches nothing must say so
STATE["bars"] = {}
try:
    scanner._load(Handle(), ["S1.NS"], True)
    check("an empty overlay is reported, not silently ignored", False,
          "it scanned stale prices instead of raising")
except ApiError as exc:
    check("an empty overlay is reported, not silently ignored",
          "no live prices" in str(exc).lower(), str(exc))
except Exception as exc:
    check("an empty overlay raises ApiError, not a crash", False, f"{type(exc).__name__}: {exc}")
STATE["bars"] = {f"S{i}" : {"close": 2.0} for i in range(1, 6)}

# ---------------------------------- 3. a feed failure is still a clean ApiError
STATE["raises"] = True
try:
    scanner._load(Handle(), ["S1.NS"], True)
    check("a feed failure raises", False, "it returned instead")
except ApiError as exc:
    check("a feed failure is a clean ApiError", "live intraday prices" in str(exc).lower(), str(exc))
except Exception as exc:
    check("a feed failure is a clean ApiError", False, f"{type(exc).__name__}: {exc}")
STATE["raises"] = False

# -------------------------------- 4. the overlay off path is completely untouched
touched = {"called": False}


def must_not_call(*a, **k):
    touched["called"] = True
    raise AssertionError("the live feed must not be touched when the overlay is off")


core.attach_live_bars = must_not_call
d2, r2, _s2 = scanner._load(Handle(), ["S1.NS"], False)
check("with the overlay off the feed is never called", not touched["called"])
check("and the scan still loads its frames", isinstance(d2, dict) and len(d2) == 5)
core.attach_live_bars = fake_attach

# ------------------------- 5. the engine contract this all rests on
# Parse it, rather than matching text: the docstring contains the word
# "returned", which a startswith("return") filter happily mistakes for a
# statement.
import ast  # noqa: E402
import inspect  # noqa: E402
from app.engine import core as real_core  # noqa: E402

fn = next(n for n in ast.parse(inspect.getsource(real_core)).body
          if isinstance(n, ast.FunctionDef) and n.name == "attach_live_bars")
returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return)]
check("attach_live_bars returns a pair on every path",
      bool(returns) and all(isinstance(v, ast.Tuple) and len(v.elts) == 2 for v in returns),
      f"{len(returns)} return statements, "
      f"{sum(1 for v in returns if isinstance(v, ast.Tuple) and len(v.elts) == 2)} are pairs")

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
