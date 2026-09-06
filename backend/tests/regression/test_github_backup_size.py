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
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content
        self.text = content.decode(errors="replace")

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

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
