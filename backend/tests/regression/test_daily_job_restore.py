"""The scheduled job must actually restore the backup before it overwrites it.

Run directly:  python3 backend/tests/regression/test_daily_job_restore.py

The incident (GitHub Actions run 33990199497): a runner starts with an empty
filesystem, so the very first thing the job must do is pull the database back
from GitHub. It logged "local database already present, keeping it" instead —
on a machine created seconds earlier.

The cause is an ordering trap that the API server had already been fixed for.
Importing ``core`` runs ``_startup_restore_learning()``, which pulls the small
learning backup and thereby leaves the database holding rows.
``restore_db_from_github()`` refuses to overwrite a database that holds rows,
quite correctly — so by the time the job asked for the restore, it had already
been disqualified. The candle history never came back, and ``step_backup()`` at
the end of the run would then push that learning-only database over the real
backup, destroying every candle the bootstrap run had paid Dhan rate limit for.

So this checks the two things that settle it: that a fresh machine holding only
learning rows still gets the whole database back, and that a run which cannot
tell why the restore failed refuses to continue rather than backing up over it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import os, shutil, sqlite3, tempfile

os.environ.setdefault("DHAN_CLIENT_ID", "x")
os.environ["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-daily-restore-")
# Silence the engine's import-time network calls; the fakes below stand in for
# every GitHub round trip this test cares about.
os.environ.pop("GITHUB_TOKEN", None)
os.environ.pop("GH_TOKEN", None)
os.environ.pop("GH_BACKUP_TOKEN", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from app.engine import core
import daily_job

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def candle_count(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    finally:
        con.close()


def make_backup_file():
    """A stand-in for the backup on GitHub: a database with real candles in it."""
    path = os.path.join(tempfile.mkdtemp(prefix="ati-backup-"), "backup.sqlite3")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE candles(symbol TEXT, dt TEXT, close REAL)")
    con.executemany("INSERT INTO candles VALUES (?,?,?)",
                    [("AAA", f"2026-01-{d:02d}", 100.0 + d) for d in range(1, 21)])
    con.commit()
    con.close()
    return path


def reset_local_db_to_learning_only():
    """Reproduce what importing core leaves behind: rows, but no candles."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(core.DATA_DB + suffix):
            os.remove(core.DATA_DB + suffix)
    con = core._db()          # creates the schema, same as the engine does
    con.execute("INSERT INTO forward_tests(symbol, strategy, status) VALUES (?,?,?)",
                ("ZZZ", "S1", "ACTIVE"))
    con.commit()
    con.close()


BACKUP = make_backup_file()


class Fakes:
    """Replaces only the four functions that talk to GitHub."""

    def __init__(self, backup_exists=True, repo_visible=True, can_write=True):
        self.backup_exists = backup_exists
        self.repo_visible = repo_visible
        self.can_write = can_write
        self.restore_called = 0

    def configured(self):
        return True

    def restore_db(self):
        self.restore_called += 1
        # The real function's guard, reproduced exactly — it is the whole bug.
        if os.path.exists(core.DATA_DB) and core.db_row_count(core.DATA_DB) > 0:
            return False
        if not self.backup_exists:
            core._GITHUB_LAST_ERROR = core._github_error_hint(404, "")
            return False
        shutil.copy(BACKUP, core.DATA_DB)
        return True

    def restore_learning(self, return_reason=False):
        return (False, "no learning backup") if return_reason else False

    def diagnostic(self):
        return {"configured": True, "repo_format": True, "token_valid": self.repo_visible,
                "repo_visible": self.repo_visible, "can_write": self.can_write,
                "branch_ok": True, "backup_exists": self.backup_exists,
                "details": ["fake diagnostic"]}

    def install(self):
        core._github_configured = self.configured
        core.restore_db_from_github = self.restore_db
        core.restore_learning_from_github = self.restore_learning
        core.github_backup_diagnostic = self.diagnostic
        return self


# ---------------------------------------- 1. the incident, reproduced exactly
fakes = Fakes(backup_exists=True).install()
reset_local_db_to_learning_only()
check("setup: the local database holds rows but no candles",
      core.db_row_count(core.DATA_DB) > 0 and candle_count(core.DATA_DB) == 0)

restored = daily_job.step_restore()
check("a learning-only database does not block the whole-database restore", restored)
check("the candles from the backup are actually present",
      os.path.exists(core.DATA_DB) and candle_count(core.DATA_DB) == 20,
      f"{candle_count(core.DATA_DB) if os.path.exists(core.DATA_DB) else 'missing'} candles")

# ------------------------------- 2. first ever run: no backup, nothing to lose
fakes = Fakes(backup_exists=False).install()
reset_local_db_to_learning_only()
try:
    restored = daily_job.step_restore()
    check("the first run continues when no backup exists yet", restored is False)
except Exception as exc:
    check("the first run continues when no backup exists yet", False, f"{type(exc).__name__}: {exc}")

# ------------------------------ 3. a broken token must NOT reach step_backup()
fakes = Fakes(backup_exists=False, repo_visible=False, can_write=False).install()
reset_local_db_to_learning_only()
try:
    daily_job.step_restore()
    check("a restore it cannot explain aborts the run", False, "it continued")
except RuntimeError:
    check("a restore it cannot explain aborts the run", True)

# ------- 4. a token that cannot prove write access must still build history
#
# GitHub's own Actions token reports no push permission on the repository API
# even though the workflow grants it contents:write, and requiring that
# permission here stopped the first history build on a repository that had no
# backup yet. Nothing exists to overwrite, so there is nothing to protect: a
# token that truly cannot write just fails at the end, losing nothing.
fakes = Fakes(backup_exists=False, repo_visible=True, can_write=False).install()
reset_local_db_to_learning_only()
try:
    restored = daily_job.step_restore()
    check("an unprovable write permission does not block the first run", restored is False)
except Exception as exc:
    check("an unprovable write permission does not block the first run", False,
          f"{type(exc).__name__}: {exc}")

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "All checks passed.")
sys.exit(1 if FAILS else 0)
