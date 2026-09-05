"""Checks that accumulated learning data cannot be silently lost.

Run directly:  python3 backend/tests/regression/test_data_safety.py
No network: the GitHub calls are exercised through export/import only.
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
import os, sys, sqlite3, tempfile

_tmpdb = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DHAN_CLIENT_ID", "test")

from app.engine import core

core.DATA_DB = _tmpdb

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ------------------------------------------------- 1. row count vs file size
con = core._db()           # creates ~24 empty tables
con.close()
size = os.path.getsize(_tmpdb)
check("a schema-only DB is large on disk", size > 20_000, f"{size} bytes")
check("db_row_count sees it as empty", core.db_row_count(_tmpdb) == 0, str(core.db_row_count(_tmpdb)))

# This is the exact bug that made the loss permanent: restore was skipped
# whenever the file merely existed and was non-zero-length.
check("size check would have wrongly claimed data exists",
      os.path.exists(_tmpdb) and os.path.getsize(_tmpdb) > 0)

# ------------------------------------------------------- 2. seed real data
con = core._db()
try:
    for i in range(5):
        con.execute(
            "INSERT INTO forward_tests(created_at,symbol,strategy,score,regime,entry,sl,target,status)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (f"2026-08-0{i+1}", f"SYM{i}", "S1", 90.0 + i, "BULL", 100.0, 93.0, 115.0, "ACTIVE"))
    # A big, cheaply rebuildable table that must NOT bloat the backup.
    con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?)",
                    [("RELIANCE", f"2024-{m:02d}-{d:02d}", 1, 2, 0.5, 1.5, 100)
                     for m in range(1, 13) for d in range(1, 29)])
    con.commit()
    seeded_fwd = con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0]
    seeded_candles = con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
finally:
    con.close()
check("seeded forward tests", seeded_fwd == 5, str(seeded_fwd))
check("db_row_count now reports data", core.db_row_count(_tmpdb) > 0)

# --------------------------------------------------------- 3. export is small
bak = tempfile.NamedTemporaryFile(suffix=".bak.db", delete=False).name
os.unlink(bak)
copied = core.export_learning_db(bak)
check("export includes forward_tests", copied.get("forward_tests") == 5, str(copied.get("forward_tests")))
check("export EXCLUDES the candle cache", "candles" not in copied, str(list(copied)))
check("backup is far smaller than the live DB",
      os.path.getsize(bak) < os.path.getsize(_tmpdb),
      f"{os.path.getsize(bak)} vs {os.path.getsize(_tmpdb)}")

# ------------------------------------- 4. restore into a wiped DB (the reboot)
os.unlink(_tmpdb)
con = core._db()           # fresh empty schema, as after a Streamlit reboot
try:
    check("reboot leaves zero forward tests",
          con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0] == 0)
finally:
    con.close()

restored = core.import_learning_db(bak)
con = core._db()
try:
    back = con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0]
    syms = sorted(r[0] for r in con.execute("SELECT symbol FROM forward_tests"))
finally:
    con.close()
check("restore brings the forward tests back", back == 5, str(back))
check("restore preserves the actual rows", syms == [f"SYM{i}" for i in range(5)], str(syms))
check("restore reports what it added", restored.get("forward_tests") == 5, str(restored))

# ------------------------------------------- 5. restore is additive, not lossy
con = core._db()
try:
    con.execute(
        "INSERT INTO forward_tests(created_at,symbol,strategy,score,regime,entry,sl,target,status)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        ("2026-09-01", "NEWROW", "S2", 88.0, "BULL", 50.0, 46.0, 60.0, "ACTIVE"))
    con.commit()
finally:
    con.close()
core.import_learning_db(bak)
con = core._db()
try:
    after = con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0]
    kept = con.execute("SELECT COUNT(*) FROM forward_tests WHERE symbol='NEWROW'").fetchone()[0]
finally:
    con.close()
check("re-restoring does not duplicate rows", after == 6, str(after))
check("restore never deletes newer rows", kept == 1, str(kept))

# --------------------------- 6. an empty local DB must not erase a good backup
os.unlink(_tmpdb)
core._db().close()
core._github_setting = lambda name: "tok" if name == "GITHUB_TOKEN" else "o/r"
ok, reason = core.backup_learning_to_github(return_reason=True)
check("empty DB refuses to overwrite the remote backup",
      ok is False and "refusing" in reason.lower(), f"{ok} / {reason}")

for f in (_tmpdb, bak):
    try:
        os.unlink(f)
    except OSError:
        pass

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All data-safety checks passed.")
