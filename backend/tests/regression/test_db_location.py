"""The database must live outside the git checkout, and must fail loudly.

Run directly:  python3 backend/tests/regression/test_db_location.py
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
import os, sys, sqlite3, tempfile, subprocess, textwrap

os.environ.setdefault("DHAN_CLIENT_ID", "x")
_scratch = tempfile.mkdtemp()
os.environ["GTF_DATA_DIR"] = _scratch

from app.engine import core

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ------------------------------------------- 1. location is outside the repo
check("DATA_DB is an absolute path", os.path.isabs(core.DATA_DB), core.DATA_DB)
check("DATA_DB honours GTF_DATA_DIR",
      os.path.dirname(core.DATA_DB) == _scratch, core.DATA_DB)
check("DATA_DB is NOT the bare repo-relative filename",
      core.DATA_DB != "market_data.sqlite3", core.DATA_DB)
repo_copy = os.path.abspath("market_data.sqlite3")
check("DATA_DB is not inside the git checkout",
      os.path.abspath(core.DATA_DB) != repo_copy, core.DATA_DB)

# ------------------------------------ 2. the reported crash, reproduced exactly
ro_dir = tempfile.mkdtemp()
ro_db = os.path.join(ro_dir, "market_data.sqlite3")
seed = sqlite3.connect(ro_db)
# Mirror the deployed state: the tables _db() creates first already exist, so the
# first statement that must WRITE is the forward_tests CREATE - which is exactly
# the frame in the reported traceback ("created_at TEXT,").
seed.execute("CREATE TABLE candles(symbol TEXT, dt TEXT)")
seed.execute("CREATE TABLE dhan_token_cache(id INTEGER PRIMARY KEY)")
seed.commit(); seed.close()
os.chmod(ro_db, 0o444); os.chmod(ro_dir, 0o555)

# `su nobody` must be able to traverse and read the helper.
os.chmod(_scratch, 0o755)
helper = os.path.join(_scratch, "ro_child.py")
with open(helper, "w") as f:
    f.write(textwrap.dedent(f"""
        import os, sys
        os.environ["DATA_DB"] = {ro_db!r}
        os.environ.setdefault("DHAN_CLIENT_ID", "x")
        sys.path.insert(0, {str(pathlib.Path(core.__file__).resolve().parents[2])!r})
        from app.engine import core
        try:
            core._db().close()
            print("NO_ERROR")
        except Exception as exc:
            print(type(exc).__name__ + "|" + str(exc)[:400])
    """))
os.chmod(helper, 0o755)
os.chmod(ro_dir, 0o555)
# sys.executable, not "python3": the engine's dependencies may live in a
# virtualenv the system interpreter cannot see, and a ModuleNotFoundError from
# the child would be misread as the database error this test is checking for.
proc = subprocess.run(
    ["su", "nobody", "-s", "/bin/sh", "-c", f"{sys.executable} {helper}"],
    capture_output=True, text=True)
combined = proc.stdout + proc.stderr
check("a read-only database raises DatabaseUnavailable",
      "DatabaseUnavailable" in combined, combined[-300:])
check("the message names the cause, not a redacted traceback",
      "not writable" in combined.lower(), combined[-300:])
check("the message names the database path", ro_db in combined, combined[-300:])
check("the message reports free disk", "free disk" in combined.lower(), combined[-300:])
check("import core survives an unusable database",
      "NO_ERROR" in combined or "DatabaseUnavailable" in combined, combined[-300:])
os.chmod(ro_dir, 0o755); os.chmod(ro_db, 0o644)

# ------------------------------------------------- 3. legacy DB is migrated
legacy_cwd = tempfile.mkdtemp()
old_cwd = os.getcwd()
os.chdir(legacy_cwd)
try:
    legacy = os.path.join(legacy_cwd, "market_data.sqlite3")
    con = sqlite3.connect(legacy)
    con.execute("CREATE TABLE forward_tests(id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("INSERT INTO forward_tests(symbol) VALUES('KEEPME')")
    con.commit(); con.close()

    new_home = os.path.join(tempfile.mkdtemp(), "market_data.sqlite3")
    core.DATA_DB = new_home
    check("legacy DB has rows", core.db_row_count(legacy) == 1)
    check("migration copies it to the new location", core._migrate_legacy_db_location() is True)
    check("rows survive the migration", core.db_row_count(new_home) == 1,
          str(core.db_row_count(new_home)))
    check("migration is idempotent", core._migrate_legacy_db_location() is False)

    # It must never clobber a destination that already holds data.
    con = sqlite3.connect(new_home)
    con.execute("INSERT INTO forward_tests(symbol) VALUES('NEWER')")
    con.commit(); con.close()
    core._migrate_legacy_db_location()
    check("migration never overwrites live data", core.db_row_count(new_home) == 2,
          str(core.db_row_count(new_home)))
finally:
    os.chdir(old_cwd)

# --------------------------------- 4. decorator regression (dhan_master cache)
check("dhan_master is still cached",
      hasattr(core.dhan_master, "clear"), str(type(core.dhan_master)))
check("_startup_restore_learning is NOT cached",
      not hasattr(core._startup_restore_learning, "clear"),
      str(type(core._startup_restore_learning)))

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("All database-location checks passed.")
