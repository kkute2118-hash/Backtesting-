"""A real candle store must survive the round trip to GitHub and back.

Run directly:  python3 backend/tests/regression/test_github_backup_size.py

The incident (Actions run 34012631615): the first successful history build
downloaded three years for all 500 Nifty stocks, then could not save any of it:

    backup  FAILED — 422 Unprocessable — GitHub rejected the request:
    {"message":"Sorry, the file is too large to be processed. ..."}

Two limits meet here, and the code met neither. The contents API refuses to
*write* a file past a few tens of megabytes, and it refuses to *read* one past
1 MB in the JSON form — above that it answers 200 with an empty ``content``
field, which the old restore happily base64-decoded into a zero-byte database
and reported as success. Both were invisible until a database big enough to
matter existed, which is to say until the app first had real data.

So the backup is gzipped now, and the restore asks for raw bytes. This checks
the pair against a stub GitHub: what the upload sends must be exactly what the
download turns back into, and it must be compressed on the way.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import gzip, os, sqlite3, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-backup-size-")
os.environ["GITHUB_TOKEN"] = "fake-token-for-the-stub"
os.environ["GITHUB_REPO"] = "owner/repo"

from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def build_database(rows):
    """A candle store shaped like the real one, big enough to cross 1 MB."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(core.DATA_DB + suffix):
            os.remove(core.DATA_DB + suffix)
    con = sqlite3.connect(core.DATA_DB)
    con.execute("CREATE TABLE candles(symbol TEXT, dt TEXT, o REAL, h REAL, l REAL, c REAL, v INT)")
    con.executemany(
        "INSERT INTO candles VALUES (?,?,?,?,?,?,?)",
        [(f"SYM{i % 500:04d}", f"2026-01-{(i % 28) + 1:02d}", 100.0 + i, 101.0 + i,
          99.0 + i, 100.5 + i, 10_000 + i) for i in range(rows)],
    )
    con.commit()
    con.close()
    return os.path.getsize(core.DATA_DB)


# ------------------------------------------------------- a stub GitHub API ---
class Stub:
    """The two contents-API behaviours that actually bit, reproduced."""

    WRITE_LIMIT = 40 * 1024 * 1024   # the API rejects a larger upload
    JSON_READ_LIMIT = 1024 * 1024    # above this the JSON form carries no content

    def __init__(self):
        self.files = {}
        self.rejected_too_large = False

    def get(self, url, headers=None, timeout=None, params=None):
        path = url.split("/contents/", 1)[1]
        body = self.files.get(path)
        if body is None:
            return Resp(404, b'{"message":"Not Found"}')
        wants_raw = (headers or {}).get("Accept") == "application/vnd.github.raw"
        if wants_raw:
            return Resp(200, body)
        import base64 as b64, json as js
        content = "" if len(body) > self.JSON_READ_LIMIT else b64.b64encode(body).decode()
        return Resp(200, js.dumps({"content": content, "sha": "abc", "size": len(body)}).encode())

    def put(self, url, headers=None, json=None, timeout=None):
        import base64 as b64
        path = url.split("/contents/", 1)[1]
        body = b64.b64decode(json["content"])
        if len(body) > self.WRITE_LIMIT:
            self.rejected_too_large = True
            return Resp(422, b'{"message":"Sorry, the file is too large to be processed."}')
        self.files[path] = body
        return Resp(201, b"{}")


class Resp:
    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode(errors="replace")
        # Real responses carry these; the retry path reads Retry-After from them.
        self.headers = headers or {}

    def json(self):
        import json as js
        return js.loads(self.content)


stub = Stub()
core.requests.get = stub.get
core.requests.put = stub.put
core._github_ensure_branch = lambda repo, branch: (True, "")

# --------------------------------------- 1. a database larger than the read cap
raw_size = build_database(40_000)
check("setup: the database is over the 1 MB JSON read limit",
      raw_size > Stub.JSON_READ_LIMIT, f"{raw_size:,} bytes")

ok, reason = core.backup_db_to_github(return_reason=True)
check("the backup succeeds", ok, reason)
check("it was NOT rejected as too large", not stub.rejected_too_large)
check("it is stored gzipped", core.GITHUB_BACKUP_PATH_GZ in stub.files,
      ", ".join(stub.files) or "nothing stored")

stored = stub.files.get(core.GITHUB_BACKUP_PATH_GZ, b"")
check("the stored copy is smaller than the database", 0 < len(stored) < raw_size,
      f"{len(stored):,} vs {raw_size:,}")
check("the stored copy really is gzip", stored[:2] == bytes((0x1F, 0x8B)))

# ------------------------------------------------- 2. and it comes back intact
with open(core.DATA_DB, "rb") as f:
    original = f.read()
os.remove(core.DATA_DB)

check("the restore succeeds", core.restore_db_from_github())
with open(core.DATA_DB, "rb") as f:
    restored = f.read()
check("the restored file is byte-identical", restored == original,
      f"{len(restored):,} vs {len(original):,} bytes")

con = sqlite3.connect(core.DATA_DB)
rows = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
con.close()
check("every candle came back", rows == 40_000, str(rows))

# ------------------------- 3. a backup from before gzipping is still readable
os.remove(core.DATA_DB)
stub.files.pop(core.GITHUB_BACKUP_PATH_GZ)
stub.files[core.GITHUB_BACKUP_PATH] = original          # the old, plain format
check("a pre-gzip backup still restores", core.restore_db_from_github())
check("and it is intact too", os.path.exists(core.DATA_DB)
      and open(core.DATA_DB, "rb").read() == original)

# ------------------- 4. a transient 502 must not throw away a finished run
#
# One did: a daily job had already scanned and recorded four forward-test
# candidates when GitHub answered the upload with "502 Server Error". The run
# reported success and the candidates went with the container.
class FlakyStub(Stub):
    def __init__(self, failures):
        super().__init__()
        self.failures_left = failures
        self.attempts = 0

    def put(self, url, headers=None, json=None, timeout=None):
        self.attempts += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            return Resp(502, b'{"message":"Server Error"}')
        return super().put(url, headers=headers, json=json, timeout=timeout)


core.time.sleep = lambda seconds: None      # do not actually back off in a test

flaky = FlakyStub(failures=1)
core.requests.get = flaky.get
core.requests.put = flaky.put
build_database(2_000)
ok, reason = core.backup_db_to_github(return_reason=True)
check("one 502 is retried and the backup still lands", ok, reason)
check("it took a second attempt", flaky.attempts == 2, str(flaky.attempts))

# ...but a server that is genuinely down must still be reported as a failure.
down = FlakyStub(failures=99)
core.requests.get = down.get
core.requests.put = down.put
ok, reason = core.backup_db_to_github(return_reason=True)
check("a persistent 502 is reported as a failure", not ok, reason)
check("and it stops at the attempt limit",
      down.attempts == core.GITHUB_UPLOAD_ATTEMPTS, str(down.attempts))

# ---------- 5. a 403 is two different problems, and only one is worth retrying
#
# GitHub throttles repeated large writes with a 403 and an explanatory body, not
# a 429 — so after five multi-megabyte commits in under an hour a backup was
# refused with the same status code a bad token produces, and the canned
# "your token cannot write" message was simply wrong.
class Throttled(Stub):
    BODY = b'{"message":"You have exceeded a secondary rate limit. Please wait a few minutes."}'

    def __init__(self, failures):
        super().__init__()
        self.failures_left = failures
        self.attempts = 0

    def put(self, url, headers=None, json=None, timeout=None):
        self.attempts += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            return Resp(403, self.BODY)
        return super().put(url, headers=headers, json=json, timeout=timeout)


throttled = Throttled(failures=1)
core.requests.get = throttled.get
core.requests.put = throttled.put
build_database(2_000)
ok, reason = core.backup_db_to_github(return_reason=True)
check("a throttling 403 is retried and the backup lands", ok, reason)
check("it took a second attempt", throttled.attempts == 2, str(throttled.attempts))

check("a throttling 403 is recognised as a throttle",
      core._github_is_throttled(403, Throttled.BODY.decode()))
# The one this repository actually hit: ruleset validation giving up on an 18 MB
# file. It says "please try again" and means it.
check("a ruleset-validation timeout is recognised as temporary",
      core._github_is_throttled(403, '{"message":"Timed out validating rule, please try again"}'))
check("a permissions 403 is NOT treated as a throttle",
      not core._github_is_throttled(403, "Resource not accessible by personal access token"))
check("the temporary-403 message says to wait, not to fix the token",
      "Wait a few minutes" in core._github_error_hint(403, Throttled.BODY.decode()))
check("the permissions message still explains the permission",
      "Contents: Read and write"
      in core._github_error_hint(403, "Resource not accessible by personal access token"))
check("either way GitHub's own words are kept",
      "secondary rate limit" in core._github_error_hint(403, Throttled.BODY.decode()))


# A permissions 403 must fail immediately — waiting cannot grant a permission.
class Denied(Stub):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def put(self, url, headers=None, json=None, timeout=None):
        self.attempts += 1
        return Resp(403, b'{"message":"Resource not accessible by personal access token"}')


denied = Denied()
core.requests.get = denied.get
core.requests.put = denied.put
ok, reason = core.backup_db_to_github(return_reason=True)
check("a permissions 403 fails at once", not ok and denied.attempts == 1, str(denied.attempts))

# A 4xx is never retried: waiting cannot make a too-large file small.
class TooLarge(Stub):
    WRITE_LIMIT = 0

too_large = TooLarge()
core.requests.get = too_large.get
core.requests.put = too_large.put
ok, reason = core.backup_db_to_github(return_reason=True)
check("a 422 is not retried", not ok and too_large.rejected_too_large, reason)


# --------------- 6. the runner path: stage the file, let git do the storing
#
# The contents API stopped being able to store this database at all — three
# successes, then 403 "Timed out validating rule" on every attempt, retries
# included. On a runner the database is therefore written to BACKUP_STAGE_PATH
# and pushed by git in the next workflow step. What matters here is that the
# staged file is a real gzip of the real database, because the restore path
# reads exactly that.
import gzip as _gzip
import importlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
daily_job = importlib.import_module("daily_job")

build_database(2_000)
with open(core.DATA_DB, "rb") as f:
    expected = f.read()

stage = os.path.join(tempfile.mkdtemp(prefix="ati-stage-"), "nested", "market_data.sqlite3.gz")
os.environ["BACKUP_STAGE_PATH"] = stage
core._github_configured = lambda: True
core.requests.put = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("staging must not touch the contents API"))

# A derived cache the size of the real data must not ride along: 365 pickled
# feature frames were 65 MB, more than the candle history they are computed
# from, and the app unpacks the backup on every cold start with 512 MB of RAM.
_con = sqlite3.connect(core.DATA_DB)
_con.execute("CREATE TABLE IF NOT EXISTS feature_snapshots("
             "symbol TEXT PRIMARY KEY, last_dt TEXT, n_rows INTEGER, payload BLOB, "
             "engine_version TEXT)")
_con.executemany("INSERT OR REPLACE INTO feature_snapshots VALUES (?,?,?,?,?)",
                 [(f"SYM{i}", "2026-09-04", 100, b"x" * 50_000, "v1") for i in range(40)])
_con.commit()
_con.close()
with_cache_bytes = os.path.getsize(core.DATA_DB)

staged_ok = daily_job.step_backup()
check("staging reports success", staged_ok)
check("it created the staged file, directories and all", os.path.exists(stage))
check("the staged file is gzip", open(stage, "rb").read(2) == bytes((0x1F, 0x8B)))
restored_bytes = _gzip.decompress(open(stage, "rb").read())
scratch = os.path.join(tempfile.mkdtemp(prefix="ati-staged-"), "staged.sqlite3")
with open(scratch, "wb") as f:
    f.write(restored_bytes)
_scon = sqlite3.connect(scratch)
staged_candles = _scon.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
staged_cache = _scon.execute("SELECT COUNT(*) FROM feature_snapshots").fetchone()[0]
_scon.close()
check("every candle is in the staged copy", staged_candles == 2_000, str(staged_candles))
check("the rebuildable cache is left out", staged_cache == 0, str(staged_cache))
check("and leaving it out actually shrinks the file",
      len(restored_bytes) < with_cache_bytes,
      f"{len(restored_bytes):,} vs {with_cache_bytes:,} on disk")

# The live database keeps its cache — staging works on a copy.
_lcon = sqlite3.connect(core.DATA_DB)
check("the live database still has its cache",
      _lcon.execute("SELECT COUNT(*) FROM feature_snapshots").fetchone()[0] == 40)
_lcon.close()
check("no staging scratch file is left behind",
      not os.path.exists(stage + ".staging.sqlite3"))

os.environ.pop("BACKUP_STAGE_PATH")

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
