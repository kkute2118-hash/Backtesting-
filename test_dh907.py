"""Synthetic-data checks for Dhan DH-907 ("no data present") handling.

Run directly:  python3 test_dh907.py
Nothing here touches the network: requests.post is monkeypatched.
"""
import os, sys, tempfile, json

os.environ.setdefault("DHAN_CLIENT_ID", "test")
os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")
_tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATA_DB"] = _tmpdb

import pandas as pd
import core

# Route the engine at a throwaway database and remove the request throttle so
# the test runs instantly.
core.DATA_DB = _tmpdb
core.DHAN_MIN_INTERVAL = 0.0

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._body = body
        self.headers = {}

    @property
    def text(self):
        return json.dumps(self._body) if isinstance(self._body, dict) else str(self._body)

    def json(self):
        return self._body


DH907 = {"errorType": "Data_Error", "errorCode": "DH-907",
         "errorMessage": "System is unable to fetch data due to incorrect parameters or no data present"}

CALLS = []


def install_post(responder):
    CALLS.clear()

    def fake_post(url, headers=None, json=None, timeout=None):
        CALLS.append(dict(url=url, payload=json))
        return responder(json)

    core.requests.post = fake_post


def candles(dates):
    ts = [int(pd.Timestamp(d).timestamp()) for d in dates]
    n = len(dates)
    return {"timestamp": ts, "open": [10.0] * n, "high": [11.0] * n,
            "low": [9.0] * n, "close": [10.5] * n, "volume": [1000.0] * n}


# dhan_map() would hit the network; pin a fake instrument master.
core.dhan_map = lambda: {"NEWLIST": "99999", "OLDNAME": "11111"}

# ---------------------------------------------------------------- 1. _dhan_post
install_post(lambda payload: FakeResponse(400, DH907))
try:
    core._dhan_post("/charts/historical", {}, label="historical")
    check("DH-907 raises DhanNoDataError", False, "no exception")
except core.DhanNoDataError:
    check("DH-907 raises DhanNoDataError", True)
except Exception as exc:
    check("DH-907 raises DhanNoDataError", False, type(exc).__name__)
check("DH-907 is not retried", len(CALLS) == 1, f"{len(CALLS)} calls")

install_post(lambda payload: FakeResponse(400, {"errorCode": "DH-905", "errorMessage": "bad token"}))
try:
    core._dhan_post("/charts/historical", {}, label="historical")
    check("other 400 still raises RuntimeError", False, "no exception")
except core.DhanNoDataError:
    check("other 400 still raises RuntimeError", False, "wrongly typed as no-data")
except RuntimeError:
    check("other 400 still raises RuntimeError", True)

# ------------------------------------------------- 2. head gap on a new listing
# Seed a recently listed stock with bars starting 2025-01-02 only.
con = core._db()
try:
    core._save(con, "NEWLIST", pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100.0]},
        index=pd.to_datetime(["2025-01-02"])))
finally:
    con.close()

core._DHAN_LAST_NO_DATA = []
install_post(lambda payload: FakeResponse(400, DH907))
try:
    saved = core.update_dhan_symbol("NEWLIST", "2021-06-01", "2025-01-02")
    check("head-gap DH-907 does not raise", True)
    check("head-gap DH-907 saves 0 rows", saved == 0, str(saved))
except Exception as exc:
    check("head-gap DH-907 does not raise", False, f"{type(exc).__name__}: {exc}")

floor = core.dhan_history_floor_table()
check("history floor recorded", len(floor) == 1 and floor.iloc[0]["symbol"] == "NEWLIST", str(floor.to_dict()))
check("floor stores real first bar", not floor.empty and floor.iloc[0]["earliest_available"] == "2025-01-02")
check("floor stores probed range start", not floor.empty and floor.iloc[0]["probed_from"] == "2021-06-01")
check("no-data note recorded", len(core._DHAN_LAST_NO_DATA) == 1, str(core._DHAN_LAST_NO_DATA))
check("note is not a build error", "NEWLIST" not in " ".join(core._DHAN_LAST_DATA_ERRORS))

# Second identical sync must not re-send the futile request.
install_post(lambda payload: FakeResponse(400, DH907))
core.update_dhan_symbol("NEWLIST", "2021-06-01", "2025-01-02")
check("proven-empty head gap is not re-requested", len(CALLS) == 0, f"{len(CALLS)} calls")

# A narrower request (start after the probed start) is also covered.
install_post(lambda payload: FakeResponse(400, DH907))
core.update_dhan_symbol("NEWLIST", "2023-01-01", "2025-01-02")
check("narrower head gap is not re-requested", len(CALLS) == 0, f"{len(CALLS)} calls")

# Widening the range further back MUST re-probe rather than trust the old answer.
install_post(lambda payload: FakeResponse(400, DH907))
core.update_dhan_symbol("NEWLIST", "2019-01-01", "2025-01-02")
check("widened head gap is re-probed", len(CALLS) == 1, f"{len(CALLS)} calls")

# ------------------------------------------------------------- 3. tail DH-907
core._DHAN_LAST_NO_DATA = []
install_post(lambda payload: FakeResponse(400, DH907))
try:
    saved = core.update_dhan_symbol("NEWLIST", "2019-01-01", "2025-03-01")
    check("tail DH-907 does not raise", True)
except Exception as exc:
    check("tail DH-907 does not raise", False, f"{type(exc).__name__}: {exc}")
tail_notes = [n for n in core._DHAN_LAST_NO_DATA if "tail range" in n]
check("tail DH-907 noted separately", len(tail_notes) == 1, str(core._DHAN_LAST_NO_DATA))

# ------------------------------------------- 4. a normal fetch still works
con = core._db()
try:
    con.execute("DELETE FROM candles WHERE symbol='OLDNAME'")
    con.execute("DELETE FROM dhan_history_floor")
    con.commit()
finally:
    con.close()
install_post(lambda payload: FakeResponse(200, candles(["2024-01-01", "2024-01-02", "2024-01-03"])))
saved = core.update_dhan_symbol("OLDNAME", "2024-01-01", "2024-01-03")
check("successful download still saves rows", saved == 3, str(saved))

# --------------------------------------- 5. download_prices keeps DH-907 quiet
core._DHAN_LAST_DATA_ERRORS = []
core._DHAN_LAST_NO_DATA = []
install_post(lambda payload: FakeResponse(400, DH907))
out = core.download_prices(["NEWLIST"], "2019-01-01", "2025-03-01", max_workers=1)
check("download_prices records no build error for DH-907",
      core._DHAN_LAST_DATA_ERRORS == [], str(core._DHAN_LAST_DATA_ERRORS))
check("download_prices still returns cached candles", "NEWLIST" in out, str(list(out)))

# ------------------------------------- 6. diagnostics explain the real reason
core._DHAN_LAST_DATA_ERRORS = []
diag = core.compute_and_store_sync_diagnostics(["NEWLIST"])
reason = diag.iloc[0]["reason"] if not diag.empty else ""
check("diagnostics cite the listing date, not an API error",
      "Dhan history begins" in reason and "API error" not in reason, reason)

os.unlink(_tmpdb)
print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
    sys.exit(1)
print("All DH-907 checks passed.")
