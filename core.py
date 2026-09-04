"""Adaptive Trading Intelligence Lab — engine.

Everything that is NOT the Streamlit UI lives here: data acquisition, the
candle store, features, strategies S1-S4, scoring, safety, forward-test
bookkeeping, learning and research.

Importing this module runs no UI, so the scheduled jobs in
.github/workflows can drive the same engine headlessly on GitHub's runners
(see daily_job.py). app.py imports it and adds the Streamlit interface on top.

Credentials are read through _secret(), which falls back from Streamlit
Secrets to environment variables for exactly that reason.
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import re
import sqlite3
import time
import threading
import queue
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from pathlib import Path
import math
import bisect
import os
import base64
import anthropic


APP_VERSION = "GTF PROFESSIONAL CORE v2 — Single Dataset / Local Research"
ARCHITECTURE_STANDARD = "Deterministic rules • no-lookahead • persistent data • adaptive ranking • human approval"

# ========================= DATA =========================

INDEX_URLS = {
    "Nifty 500": "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty Smallcap 100": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",
    "Nifty Smallcap 250": "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty Midcap 150": "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}

@st.cache_data(ttl=86400)
def index_universe(name):
    r = requests.get(INDEX_URLS[name], headers={"User-Agent":"Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(pd.io.common.BytesIO(r.content))
    col = next(c for c in df.columns if str(c).strip().upper() == "SYMBOL")
    return sorted({str(s).strip().upper()+".NS" for s in df[col].dropna()})


# ========================= DHAN PERSISTENT DATA ENGINE =========================
DHAN_BASE_URL="https://api.dhan.co/v2"
DATA_DB="market_data.sqlite3"

# ---- GitHub-based DB backup/restore (Tier 1 fix for Streamlit Cloud's
# ephemeral filesystem: every reboot/redeploy clones a fresh container from
# GitHub, and DATA_DB is not committed to git, so accumulated learning data
# would otherwise vanish on any restart). This is a stopgap, not a permanent
# architecture - it commits a binary SQLite file to git on every backup,
# which will bloat the repo's history over months. A hosted SQLite-compatible
# DB (e.g. Turso) is the real long-term fix; this just prevents data loss now.
GITHUB_BACKUP_PATH = "backups/market_data.sqlite3"


# GitHub refuses to create any Actions secret or repository variable whose name
# starts with "GITHUB_" — the prefix is reserved. The original setting names all
# used it, which made them impossible to configure for the scheduled jobs. Each
# setting therefore accepts a non-reserved alias, tried in order.
_GITHUB_SETTING_ALIASES = {
    "GITHUB_TOKEN": ("GITHUB_TOKEN", "GH_TOKEN", "GH_BACKUP_TOKEN"),
    "GITHUB_REPO": ("GITHUB_REPO", "GH_REPO", "DB_BACKUP_REPO"),
    "GITHUB_BACKUP_BRANCH": ("GITHUB_BACKUP_BRANCH", "GH_BACKUP_BRANCH", "DB_BACKUP_BRANCH"),
}

# Last failure from a backup/restore attempt, so the UI can show a real reason
# instead of a bare "backup failed".
_GITHUB_LAST_ERROR = ""


def _github_setting(name):
    """Read one backup setting by its canonical name, honouring the aliases."""
    for key in _GITHUB_SETTING_ALIASES.get(name, (name,)):
        val = _secret(key)
        if val not in (None, ""):
            return str(val).strip()
    return None


def _github_backup_branch():
    """Branch the database backup is committed to.

    Defaults to the repository's default branch, which is what the in-app
    "Backup DB Now" button has always used. Set DB_BACKUP_BRANCH to a dedicated
    branch (e.g. "db-backup") before enabling the daily job: each backup commits
    the whole SQLite file, so a scheduled run would otherwise add one binary
    blob per day to your code branch's history forever.
    """
    return _github_setting("GITHUB_BACKUP_BRANCH") or None


def _github_default_branch(repo):
    r = requests.get(f"https://api.github.com/repos/{repo}", headers=_github_headers(), timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("default_branch")


def _github_ensure_branch(repo, branch):
    """Create `branch` off the default branch if it does not exist yet.

    Without this, pointing the backup at a dedicated branch that has never been
    created makes every PUT fail with a 404 that looks identical to a bad token.
    """
    if not branch:
        return True, ""
    r = requests.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}",
                     headers=_github_headers(), timeout=30)
    if r.status_code == 200:
        return True, ""
    base = _github_default_branch(repo)
    if not base:
        return False, f"Could not read the repository's default branch to create '{branch}'."
    head = requests.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{base}",
                        headers=_github_headers(), timeout=30)
    if head.status_code != 200:
        return False, f"Could not read '{base}' to branch from ({head.status_code})."
    sha = head.json().get("object", {}).get("sha")
    mk = requests.post(f"https://api.github.com/repos/{repo}/git/refs",
                       headers=_github_headers(), timeout=30,
                       json={"ref": f"refs/heads/{branch}", "sha": sha})
    if mk.status_code in (200, 201):
        return True, f"Created backup branch '{branch}' from '{base}'."
    return False, f"Could not create branch '{branch}': {mk.status_code} {mk.text[:200]}"


def _github_error_hint(status, body):
    """Turn a GitHub API status into something actionable."""
    if status == 401:
        return ("401 Unauthorized — the token is invalid or expired. Generate a new one and "
                "update it in Streamlit Secrets / Actions secrets.")
    if status == 403:
        return ("403 Forbidden — the token authenticated but is not allowed to write. A "
                "fine-grained token needs Repository permissions → Contents: Read and write, "
                "AND this repository selected under 'Repository access'. In Actions, the "
                "workflow also needs 'permissions: contents: write'.")
    if status == 404:
        return ("404 Not Found — the repository name is wrong, the branch does not exist, or "
                "the token cannot see this repository. GITHUB_REPO must be 'owner/repo', not "
                "a URL.")
    if status == 409:
        return "409 Conflict — the backup changed underneath this write. Try again."
    if status == 422:
        return f"422 Unprocessable — GitHub rejected the request: {body[:200]}"
    return f"HTTP {status}: {body[:200]}"

def _secret(name, default=None):
    """One place to read configuration, from Streamlit Secrets OR the environment.

    The scheduled jobs in .github/workflows run this same engine headlessly on
    GitHub's runners, where there is no secrets.toml and st.secrets raises. Every
    credential therefore falls back to an environment variable of the same name,
    so one set of code serves both the Streamlit app and the cron jobs.
    """
    try:
        val = st.secrets.get(name)
        if val not in (None, ""):
            return val
    except Exception:
        # No secrets.toml at all — st.secrets raises rather than returning None.
        pass
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _secret_required(name):
    val = _secret(name)
    if val in (None, ""):
        raise RuntimeError(
            f"{name} is not configured. Set it in Streamlit Secrets, or as an "
            f"environment variable when running headlessly."
        )
    return val


def _github_configured():
    try:
        return bool(_github_setting("GITHUB_TOKEN")) and bool(_github_setting("GITHUB_REPO"))
    except Exception:
        return False

def _github_headers():
    return {
        "Authorization": f"token {_github_setting('GITHUB_TOKEN') or ''}",
        "Accept": "application/vnd.github+json",
    }

def restore_db_from_github():
    """Call once at app startup, before any _db() call. If the local DB file
    is missing or empty, pulls the last backup from GitHub so learning data
    survives a Streamlit Cloud reboot. Never raises - a failed restore just
    means the app starts fresh, same as today's behavior without this patch."""
    global _GITHUB_LAST_ERROR
    if not _github_configured():
        return False
    if os.path.exists(DATA_DB) and os.path.getsize(DATA_DB) > 0:
        return False  # local file already present this container session
    try:
        repo = _github_setting("GITHUB_REPO")
        url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"
        branch = _github_backup_branch()
        r = requests.get(url, headers=_github_headers(), timeout=30,
                         params={"ref": branch} if branch else None)
        if r.status_code != 200:
            # No backup exists yet, or auth/branch problem. Record why so the
            # Data Manager and the scheduled job can report it instead of
            # silently starting from an empty database.
            _GITHUB_LAST_ERROR = _github_error_hint(r.status_code, r.text)
            return False
        content_b64 = r.json().get("content", "")
        raw = base64.b64decode(content_b64)
        with open(DATA_DB, "wb") as f:
            f.write(raw)
        return True
    except Exception as exc:
        _GITHUB_LAST_ERROR = f"{type(exc).__name__}: {exc}"
        return False

def backup_db_to_github(return_reason=False):
    """Upload the local DB to GitHub, overwriting the last backup.

    Returns True/False, or (ok, reason) when return_reason=True. Every failure
    also lands in _GITHUB_LAST_ERROR. The previous version swallowed the API
    response entirely, so a wrong repo name, an expired token and a missing
    branch were all indistinguishable from each other — and from success.
    """
    global _GITHUB_LAST_ERROR

    def done(ok, reason=""):
        global _GITHUB_LAST_ERROR
        _GITHUB_LAST_ERROR = "" if ok else reason
        return (ok, reason) if return_reason else ok

    if not _github_configured():
        missing = [n for n in ("GITHUB_TOKEN", "GITHUB_REPO") if not _github_setting(n)]
        return done(False, "Not configured — missing " + " and ".join(missing) +
                           ". Set them in Streamlit Secrets (for the app) or Actions secrets "
                           "(for the scheduled jobs); those two stores are separate.")
    if not os.path.exists(DATA_DB):
        return done(False, f"No local database at {DATA_DB} — nothing to back up yet.")

    repo = _github_setting("GITHUB_REPO")
    if "/" not in repo or repo.startswith("http"):
        return done(False, f"GITHUB_REPO is '{repo}' but must be 'owner/repo' — not a URL.")

    try:
        branch = _github_backup_branch()
        note = ""
        if branch:
            ok, msg = _github_ensure_branch(repo, branch)
            if not ok:
                return done(False, msg)
            note = msg

        url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"
        with open(DATA_DB, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()

        # Need the current file's SHA if it already exists, else GitHub
        # rejects the update as a conflicting create.
        sha = None
        r = requests.get(url, headers=_github_headers(), timeout=30,
                         params={"ref": branch} if branch else None)
        if r.status_code == 200:
            sha = r.json().get("sha")
        elif r.status_code in (401, 403):
            return done(False, _github_error_hint(r.status_code, r.text))

        payload = {
            "message": f"Auto-backup DB {datetime.now().isoformat(timespec='seconds')}",
            "content": content_b64,
        }
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch

        put_r = requests.put(url, headers=_github_headers(), json=payload, timeout=120)
        if put_r.status_code in (200, 201):
            mb = os.path.getsize(DATA_DB) / 1_048_576
            where = f"{repo}@{branch or 'default branch'}:{GITHUB_BACKUP_PATH}"
            return done(True, (note + " " if note else "") + f"Backed up {mb:.1f} MB to {where}.")
        return done(False, _github_error_hint(put_r.status_code, put_r.text))
    except Exception as exc:
        return done(False, f"{type(exc).__name__}: {exc}")


def github_backup_diagnostic():
    """Step-by-step check of the GitHub backup path, naming the exact failure.

    Read-only: it never writes a commit. It verifies configuration, that the
    token authenticates, that it can actually see the repository, that it holds
    write permission, and whether a backup already exists.
    """
    result = {"configured": False, "repo_format": False, "token_valid": False,
              "repo_visible": False, "can_write": False, "branch_ok": False,
              "backup_exists": False, "details": []}
    say = result["details"].append

    token = _github_setting("GITHUB_TOKEN")
    repo = _github_setting("GITHUB_REPO")
    if not token or not repo:
        missing = [n for n in ("GITHUB_TOKEN", "GITHUB_REPO") if not _github_setting(n)]
        say(f"Missing {' and '.join(missing)}.")
        say("These are two separate stores: the Streamlit app reads Streamlit Secrets, the "
            "scheduled jobs read GitHub Actions secrets. Setting one does NOT configure the other.")
        say("Aliases accepted: GH_TOKEN / GH_BACKUP_TOKEN for the token, GH_REPO for the repo, "
            "DB_BACKUP_BRANCH for the branch (GitHub forbids names starting with GITHUB_).")
        return result
    result["configured"] = True
    say(f"Token present ({len(token)} chars, starts '{token[:4]}…').")

    if "/" not in repo or repo.startswith("http"):
        say(f"GITHUB_REPO is '{repo}' but must be 'owner/repo' — not a URL.")
        return result
    result["repo_format"] = True
    say(f"Repository: {repo}")

    try:
        r = requests.get(f"https://api.github.com/repos/{repo}", headers=_github_headers(), timeout=30)
    except Exception as exc:
        say(f"Could not reach api.github.com: {exc}")
        return result

    if r.status_code in (401,):
        say(_github_error_hint(401, r.text))
        return result
    if r.status_code == 404:
        say(_github_error_hint(404, r.text))
        say("A fine-grained token also 404s on a repository it was not granted access to, "
            "even when the repository exists.")
        return result
    if r.status_code != 200:
        say(_github_error_hint(r.status_code, r.text))
        return result

    result["token_valid"] = True
    result["repo_visible"] = True
    info = r.json()
    default_branch = info.get("default_branch")
    say(f"Repository visible. Default branch: {default_branch}. "
        f"Private: {info.get('private')}.")

    perms = info.get("permissions") or {}
    if perms.get("push") or perms.get("admin"):
        result["can_write"] = True
        say("Token has write (push) access.")
    else:
        say(_github_error_hint(403, ""))
        say(f"Reported permissions: {perms or 'none'}")

    branch = _github_backup_branch()
    if not branch:
        result["branch_ok"] = True
        say(f"Backup branch: (default branch '{default_branch}'). "
            "Set DB_BACKUP_BRANCH to a dedicated branch before enabling the daily job — "
            "each backup commits the whole database file.")
    else:
        br = requests.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{branch}",
                          headers=_github_headers(), timeout=30)
        if br.status_code == 200:
            result["branch_ok"] = True
            say(f"Backup branch '{branch}' exists.")
        else:
            say(f"Backup branch '{branch}' does not exist yet — it will be created "
                "automatically on the next backup.")
            result["branch_ok"] = result["can_write"]

    fr = requests.get(f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}",
                      headers=_github_headers(), timeout=30,
                      params={"ref": branch} if branch else None)
    if fr.status_code == 200:
        result["backup_exists"] = True
        size_mb = (fr.json().get("size") or 0) / 1_048_576
        say(f"Existing backup found: {GITHUB_BACKUP_PATH} ({size_mb:.1f} MB).")
    else:
        say(f"No backup at {GITHUB_BACKUP_PATH} yet — the first successful backup creates it.")

    if _GITHUB_LAST_ERROR:
        say(f"Last backup error was: {_GITHUB_LAST_ERROR}")
    return result

def maybe_backup_db(min_interval_minutes=15):
    """Rate-limited backup trigger - call after any write worth protecting
    (a learning trade recorded, a forward test closed, a candidate added).
    Only actually uploads if enough time has passed since the last backup
    this session, so routine activity doesn't spam GitHub commits."""
    key = "_last_db_backup_ts"
    last = st.session_state.get(key)
    now = datetime.now()
    if last is not None and (now - last).total_seconds() < min_interval_minutes * 60:
        return False
    ok = backup_db_to_github()
    if ok:
        st.session_state[key] = now
    return ok

restore_db_from_github()

DHAN_MIN_INTERVAL=0.205  # stay below the documented 5 data-API requests/sec
_DHAN_RATE_LOCK=threading.Lock()
_DHAN_LAST_REQUEST=0.0
_DHAN_LAST_DATA_ERRORS=[]

# DH-907 ("no data present") is NOT a failure the way a 4xx/5xx is: it is Dhan
# telling us the requested window simply predates the symbol's listing (or
# post-dates its last published session). Recording it in _DHAN_LAST_DATA_ERRORS
# turned every recently listed Nifty-500 constituent into a permanent red error
# on every single sync, because the head-gap request below the stock's own
# listing date can never succeed. These are tracked separately and reported as
# an expected condition instead.
_DHAN_LAST_NO_DATA=[]
_DHAN_NO_DATA_LOCK=threading.Lock()


class DhanNoDataError(RuntimeError):
    """Dhan answered DH-907: no candles exist in the requested date range."""


def _note_no_data(symbol,start_date,end_date,scope):
    """Record one DH-907 window for the Data Manager, newest-last, de-duplicated."""
    entry=(f"{str(symbol).upper().replace('.NS','')}: no Dhan data for "
           f"{pd.Timestamp(start_date).date()} to {pd.Timestamp(end_date).date()} ({scope})")
    global _DHAN_LAST_NO_DATA
    with _DHAN_NO_DATA_LOCK:
        _DHAN_LAST_NO_DATA=[e for e in _DHAN_LAST_NO_DATA if e!=entry][-199:]+[entry]

# A WebSocket tick older than this is treated as stale and re-fetched over REST,
# so a dead/disconnected feed can never masquerade as a current price.
LIVE_TICK_MAX_AGE_MINUTES = 10

# How many recent calendar days a sync re-requests even though candles already
# exist there, so partially-formed or exchange-revised bars are corrected.
LATEST_SYNC_TAIL_DAYS = 10

# Dhan access tokens are only valid 24h (SEBI/exchange requirement) with no
# refresh-token flow for a bare access token - PIN+TOTP (or a browser OAuth
# login) is required to mint a new one. If DHAN_PIN and DHAN_TOTP_SECRET are
# configured, the app renews the token itself once the cached one is older
# than DHAN_TOKEN_MAX_AGE_HOURS, instead of a manual daily Secrets paste.
# DHAN_ACCESS_TOKEN remains supported as a manual fallback when PIN+TOTP
# aren't configured.
DHAN_TOKEN_MAX_AGE_HOURS = 23
_DHAN_TOKEN_LOCK = threading.Lock()

def _dhan_pin_totp_configured():
    try:
        return bool(_secret("DHAN_CLIENT_ID")) and bool(_secret("DHAN_PIN")) and bool(_secret("DHAN_TOTP_SECRET"))
    except Exception:
        return False

def _dhan_manual_token_configured():
    try:
        return bool(_secret("DHAN_ACCESS_TOKEN"))
    except Exception:
        return False

def dhan_configured():
    try:
        if not _secret("DHAN_CLIENT_ID"):
            return False
    except Exception:
        return False
    return _dhan_pin_totp_configured() or _dhan_manual_token_configured()

def _read_cached_dhan_token():
    con=_db()
    try:
        row=con.execute("SELECT access_token,issued_at FROM dhan_token_cache WHERE id=1").fetchone()
    finally:
        con.close()
    return (row[0],row[1]) if row else (None,None)

def _write_cached_dhan_token(token):
    con=_db()
    try:
        con.execute("""INSERT INTO dhan_token_cache(id,access_token,issued_at) VALUES(1,?,?)
            ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token,issued_at=excluded.issued_at""",
            (token,datetime.now().isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()

def _dhan_generate_fresh_token():
    """Headless PIN+TOTP login (no browser step). Requires DHAN_PIN and
    DHAN_TOTP_SECRET (the base32 secret shown once when enabling TOTP-based
    API login in Dhan's console) alongside DHAN_CLIENT_ID in Streamlit Secrets."""
    import pyotp
    from dhanhq import DhanLogin
    code = pyotp.TOTP(str(_secret_required("DHAN_TOTP_SECRET"))).now()
    login = DhanLogin(str(_secret_required("DHAN_CLIENT_ID")))
    result = login.generate_token(str(_secret_required("DHAN_PIN")), code)
    token = None
    if isinstance(result, str):
        token = result
    elif isinstance(result, dict):
        if result.get("status") == "error":
            # A real Dhan API error (e.g. "Token can be generated once every
            # 2 minutes.") - distinct from an unrecognized SDK response shape,
            # so the caller sees the actual reason instead of a confusing
            # "unrecognized response" message.
            raise RuntimeError(f"Dhan rejected the token request: {result.get('message', 'unknown error')}")
        for key in ("accessToken", "access_token", "token"):
            v = result.get(key)
            if isinstance(v, str) and v:
                token = v
                break
    if not token:
        # Unknown response shape from the dhanhq SDK - fail loudly rather than
        # silently caching a bad value. Whatever `result` actually looks like
        # here tells us exactly which key name to add above.
        raise RuntimeError(f"Dhan generate_token() returned an unrecognized response: {result!r}")
    _write_cached_dhan_token(token)
    return token

def _dhan_ensure_fresh_token():
    """Returns a valid Dhan access token, auto-renewing via PIN+TOTP if the
    cached one is missing/expired. Falls back to a manually-pasted
    DHAN_ACCESS_TOKEN secret when PIN+TOTP aren't configured."""
    if not _dhan_pin_totp_configured():
        return str(_secret_required("DHAN_ACCESS_TOKEN"))
    with _DHAN_TOKEN_LOCK:
        token, issued_at = _read_cached_dhan_token()
        fresh = False
        age_hours = None
        if token and issued_at:
            try:
                age_hours = (datetime.now() - datetime.fromisoformat(issued_at)).total_seconds() / 3600
                fresh = age_hours < DHAN_TOKEN_MAX_AGE_HOURS
            except Exception:
                fresh = False
        if fresh:
            return token
        try:
            return _dhan_generate_fresh_token()
        except Exception:
            # Renewal failed - most commonly Dhan's own 2-minute rate limit on
            # token generation, hit by an app rerun or a manual force-renew
            # shortly after an automatic one. The cached token is only
            # renewed early (past DHAN_TOKEN_MAX_AGE_HOURS) as a safety
            # margin - it's still genuinely valid for Dhan's real 24h expiry,
            # so keep using it rather than breaking every Dhan call over a
            # renewal hiccup. Only propagate when there's nothing usable.
            if token and age_hours is not None and age_hours < 24:
                return token
            raise

def _dhan_headers():
    return {
        "access-token":_dhan_ensure_fresh_token(),
        "client-id":str(_secret_required("DHAN_CLIENT_ID")),
        "Content-Type":"application/json","Accept":"application/json"
    }

def _db():
    con=sqlite3.connect(DATA_DB,timeout=60,check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS candles(
        symbol TEXT NOT NULL, dt TEXT NOT NULL, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY(symbol,dt))""")
    con.execute("""CREATE TABLE IF NOT EXISTS dhan_token_cache(
        id INTEGER PRIMARY KEY CHECK (id=1), access_token TEXT, issued_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS forward_tests(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, symbol TEXT,
        strategy TEXT, score REAL, regime TEXT, entry REAL, sl REAL, target REAL,
        status TEXT DEFAULT 'ACTIVE', ltp REAL, mfe REAL DEFAULT 0,
        mae REAL DEFAULT 0, exit_price REAL, result_r REAL, updated_at TEXT,
        signal_date TEXT, signal_json TEXT)""")
    existing_cols={r[1] for r in con.execute("PRAGMA table_info(forward_tests)").fetchall()}
    for col,typ in [("signal_date","TEXT"),("signal_json","TEXT")]:
        if col not in existing_cols:
            con.execute(f"ALTER TABLE forward_tests ADD COLUMN {col} {typ}")
    # S4 SEPA migration: old rows tagged strategy='S4' were qualified under the
    # pre-SEPA literal formula, not the live SEPA rule. Re-tag them so
    # historical results stay distinguishable from new S4_SEPA signals.
    # Idempotent by construction: once a row's strategy has been rewritten to
    # 'S4_RECOVERY_LEGACY' it no longer matches WHERE strategy='S4', so
    # running this again (every _db() call) touches zero rows thereafter.
    con.execute("UPDATE forward_tests SET strategy='S4_RECOVERY_LEGACY' WHERE strategy='S4'")
    con.execute("""CREATE TABLE IF NOT EXISTS scanner_signals(
        signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_key TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        score REAL,
        learned_rank REAL,
        historical_edge_r REAL,
        learning_confidence TEXT,
        regime TEXT,
        safety_status TEXT,
        safety_score REAL,
        entry REAL,
        stop REAL,
        target REAL,
        rr REAL,
        rsi REAL,
        relvol REAL,
        htf_score REAL,
        footprint_score REAL,
        strategy_score REAL,
        entry_quality REAL,
        relative_strength REAL,
        safety_flags TEXT,
        selected_for_forward INTEGER DEFAULT 0
    )""")
    con.execute("""CREATE INDEX IF NOT EXISTS idx_scanner_signals_date
                   ON scanner_signals(signal_date)""")
    if False:
        con.execute("""CREATE INDEX IF NOT EXISTS idx_scanner_signals_forward
                       ON scanner_signals(selected_for_forward,status)""")
    con.execute("""CREATE TABLE IF NOT EXISTS forward_observations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forward_id INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        dt TEXT NOT NULL,
        ltp REAL,
        high REAL,
        low REAL,
        unrealized_return_pct REAL,
        mfe_pct REAL,
        mae_pct REAL,
        status TEXT,
        UNIQUE(forward_id,dt)
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS sync_diagnostics(
        symbol TEXT PRIMARY KEY, checked_at TEXT, bar_count INTEGER, reason TEXT)""")
    # Remembers, per symbol, that Dhan has already told us (DH-907) there is
    # nothing before our earliest stored candle. Without this the head-gap
    # request for every recently listed stock is re-sent on every single sync,
    # burning rate-limited API calls to be told "no data" again.
    con.execute("""CREATE TABLE IF NOT EXISTS dhan_history_floor(
        symbol TEXT PRIMARY KEY, earliest_available TEXT, probed_from TEXT,
        checked_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sync_freshness_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, synced_at TEXT,
        most_recent_date_pulled TEXT, symbols_updated INTEGER)""")
    con.execute("""CREATE TABLE IF NOT EXISTS forward_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        forward_id INTEGER NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        strategy TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        entry REAL,
        exit_price REAL,
        result_r REAL,
        return_pct REAL,
        outcome TEXT,
        holding_bars INTEGER,
        mfe_pct REAL,
        mae_pct REAL,
        regime TEXT,
        score REAL,
        closed_at TEXT
    )""")
    con.commit(); return con

@st.cache_data(ttl=86400,show_spinner=False)
def dhan_master():
    urls=["https://images.dhan.co/api-data/api-scrip-master.csv",
          "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"]
    last=""
    for u in urls:
        try:
            r=requests.get(u,timeout=45); r.raise_for_status()
            if len(r.content)>1000:return pd.read_csv(io.BytesIO(r.content),low_memory=False)
        except Exception as e:last=str(e)
    raise RuntimeError("Dhan instrument master failed: "+last)

@st.cache_data(ttl=86400,show_spinner=False)
def dhan_map():
    m=dhan_master()
    cols={str(c).strip().lower():c for c in m.columns}
    sym=next((cols[k] for k in ["sem_trading_symbol","trading_symbol","sem_custom_symbol","custom_symbol"] if k in cols),None)
    sid=next((cols[k] for k in ["sem_smst_security_id","sem_security_id","security_id"] if k in cols),None)
    ex=next((cols[k] for k in ["sem_exm_exch_id","exchange"] if k in cols),None)
    seg=next((cols[k] for k in ["sem_segment","segment"] if k in cols),None)
    if not sym or not sid:raise RuntimeError("Dhan symbol/Security ID columns not found")
    keep=[sym,sid]+([ex] if ex else [])+([seg] if seg else [])
    m=m[keep].copy()
    names=["symbol","security_id"]+((["exchange"] if ex else [])+(["segment"] if seg else []))
    m.columns=names
    m.symbol=m.symbol.astype(str).str.upper().str.strip()
    if ex:
        m=m[m.exchange.astype(str).str.upper().isin(["NSE","NSE_EQ"])]
    if seg:
        sv=m.segment.astype(str).str.upper().str.strip()
        q=sv.isin(["E","EQUITY","NSE_EQ"])
        if q.any():m=m[q]
    return dict(zip(m.symbol,m.security_id.astype(str)))

def last_expected_nse_session(day=None):
    """Return the most recent weekday NSE cash-market session date.

    This intentionally does not invent a candle for Saturday/Sunday.  The
    current request (e.g. Saturday 29-Aug-2026) therefore targets Friday
    28-Aug-2026, which is the latest expected equity trading session.
    """
    d = pd.Timestamp(day or date.today()).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# NSE cash-market close, IST wall-clock. The whole app already treats
# datetime.now()/date.today() as local wall-clock time (see the Dhan token
# cache above), so this follows the same convention rather than introducing
# timezone-aware datetimes into a codebase that has none.
NSE_MARKET_CLOSE_HOUR = 15
NSE_MARKET_CLOSE_MINUTE = 30

def latest_completed_nse_session(now=None):
    """Most recently *completed* NSE cash session: weekday-aware (via
    last_expected_nse_session) AND time-of-day aware (rolls back one more
    day before today's 15:30 IST close). Distinct from
    last_expected_nse_session(), which is date-only and used for sync/backtest
    date-range bounds where an off-by-one before market close is harmless.

    `now` is an injectable datetime for testing; defaults to wall-clock now.
    """
    now = now if now is not None else datetime.now()
    close_today = now.replace(hour=NSE_MARKET_CLOSE_HOUR, minute=NSE_MARKET_CLOSE_MINUTE,
                               second=0, microsecond=0)
    d = now.date()
    if now < close_today:
        d -= timedelta(days=1)
    return last_expected_nse_session(d)


NSE_MARKET_OPEN_HOUR = 9
NSE_MARKET_OPEN_MINUTE = 15


def nse_market_is_open(now=None):
    """True while the NSE cash session is actually trading (weekday, 09:15-15:30
    IST wall-clock). Used to decide whether a live intraday price is meaningful;
    outside the session the last completed daily candle IS the current price."""
    now = now if now is not None else datetime.now()
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=NSE_MARKET_OPEN_HOUR, minute=NSE_MARKET_OPEN_MINUTE,
                         second=0, microsecond=0)
    close_t = now.replace(hour=NSE_MARKET_CLOSE_HOUR, minute=NSE_MARKET_CLOSE_MINUTE,
                          second=0, microsecond=0)
    return open_t <= now <= close_t


def current_session_date(now=None):
    """The trading date a live price belongs to. During a live session that is
    today; otherwise it is the most recently completed session."""
    now = now if now is not None else datetime.now()
    if nse_market_is_open(now):
        return now.date()
    return latest_completed_nse_session(now)


def data_freshness_status(tickers, now=None):
    """Compare the MAX cached candle date across `tickers` against the most
    recently completed NSE session. Read-only diagnostics — never syncs."""
    expected = latest_completed_nse_session(now)
    symbols = sorted({str(t).upper().replace(".NS", "") for t in tickers}) if tickers else []
    latest = None
    if symbols:
        con = _db()
        try:
            qmarks = ",".join(["?"] * len(symbols))
            row = con.execute(f"SELECT MAX(dt) FROM candles WHERE symbol IN ({qmarks})", symbols).fetchone()
        finally:
            con.close()
        if row and row[0]:
            latest = pd.Timestamp(row[0]).date()
    if latest is None:
        return {"expected": expected, "latest": None, "current": False, "days_behind": None}
    if latest >= expected:
        days_behind = 0
    else:
        days_behind = len(pd.bdate_range(start=latest + timedelta(days=1), end=expected))
    return {"expected": expected, "latest": latest, "current": latest >= expected, "days_behind": int(days_behind)}


def render_data_freshness_banner(tickers, now=None):
    """Prominent freshness indicator for the Scanner/Backtest tabs.

    Read-only: it reports state, it never syncs. The Scanner tab pairs it with
    an explicit top-up button so a stale cache can be fixed without leaving the
    tab, which is what previously forced scans to run on old closes.
    """
    if not tickers:
        st.info("Select a universe to check local data freshness.")
        return None
    status = data_freshness_status(tickers, now=now)
    if status["latest"] is None:
        st.error("⚠️ No local candle data found for this universe yet. Run Data Manager → SYNC ONLY MISSING DATA before scanning.")
    elif status["current"]:
        st.success(f"✅ Stored candles current as of {status['latest'].strftime('%d-%b-%Y')} (last completed session).")
    else:
        n = status["days_behind"]
        unit = "session" if n == 1 else "sessions"
        st.error(
            f"🛑 STALE DATA — local cache ends {status['latest'].strftime('%d-%b-%Y')}, but "
            f"{status['expected'].strftime('%d-%b-%Y')} has already closed ({n} {unit} behind). "
            "Scanning now would rank prices that are out of date and produce late entries. "
            "Run the top-up button below first."
        )
    if nse_market_is_open(now):
        st.info(
            "🟢 NSE cash session is OPEN. Stored daily candles can only ever be as new as "
            "yesterday's close — tick 'Use live intraday price' below to scan against the "
            "current price instead of the last close."
        )
    return status


DHAN_RETRY_STATUSES = (429, 500, 502, 503, 504)


def _dhan_post(path, payload, timeout=45, label="request", attempts=5):
    """Single entry point for every Dhan data-API POST.

    Two things every caller needs and only dhan_history() used to do:
      - the global rate-limit throttle (DHAN_MIN_INTERVAL between requests,
        shared across threads via _DHAN_RATE_LOCK)
      - retry with exponential backoff on 429/5xx/DH-904, honouring a
        Retry-After header when Dhan sends one

    dhan_live_ltp() previously had NEITHER, so it fired an unthrottled request
    that could trip Dhan's per-second limit on its own - and once tripped, the
    throttled-but-retrying calls right after it (historical) burned all their
    retries while still inside the same cooldown. That is exactly the
    "Authenticated LTP API: FAIL / Authenticated historical API: FAIL" pair
    the Dhan Connection Test reported, with a 429 on /marketfeed/ltp.

    Returns the successful Response. Raises RuntimeError with the last error
    text when every attempt fails, or immediately on a non-retryable status.
    """
    global _DHAN_LAST_REQUEST
    last_error = None
    for attempt in range(attempts):
        with _DHAN_RATE_LOCK:
            wait = DHAN_MIN_INTERVAL - (time.monotonic() - _DHAN_LAST_REQUEST)
            if wait > 0:
                time.sleep(wait)
            _DHAN_LAST_REQUEST = time.monotonic()
        r = requests.post(f"{DHAN_BASE_URL}{path}", headers=_dhan_headers(),
                          json=payload, timeout=timeout)
        if r.ok:
            return r
        last_error = f"Dhan {label} {r.status_code}: {r.text[:250]}"
        # DH-907 means "no data present for these parameters". Retrying cannot
        # change that, and neither can the caller - but it is a legitimate,
        # expected answer for a window that predates a stock's listing, so it
        # gets its own type instead of being reported as a build failure.
        if "DH-907" in r.text:
            raise DhanNoDataError(last_error)
        if r.status_code in DHAN_RETRY_STATUSES or "DH-904" in r.text:
            backoff = min(8, 2 ** attempt)
            # Dhan does not always send Retry-After, but when it does it is
            # authoritative about how long the cooldown actually lasts.
            try:
                retry_after = float(r.headers.get("Retry-After", "") or 0)
                if retry_after > 0:
                    backoff = max(backoff, min(30.0, retry_after))
            except (TypeError, ValueError):
                pass
            time.sleep(backoff)
            continue
        raise RuntimeError(last_error)
    raise RuntimeError(last_error or f"Dhan {label} request failed")


def dhan_history(symbol,start_date,end_date):
    clean=str(symbol).upper().replace(".NS","")
    sid=dhan_map().get(clean)
    if not sid:raise ValueError("Security ID not found: "+clean)
    payload={"securityId":sid,"exchangeSegment":"NSE_EQ","instrument":"EQUITY",
             "expiryCode":0,"oi":False,
             "fromDate":pd.Timestamp(start_date).strftime("%Y-%m-%d"),
             "toDate":(pd.Timestamp(end_date)+pd.Timedelta(days=1)).strftime("%Y-%m-%d")}
    r=_dhan_post("/charts/historical",payload,timeout=45,label="historical")
    j=r.json()
    if "close" not in j:raise RuntimeError("Unexpected Dhan historical response")
    d=pd.DataFrame({k:j.get(k,[]) for k in ["open","high","low","close","volume"]})
    if j.get("timestamp"):d.index=pd.to_datetime(j["timestamp"],unit="s",errors="coerce")
    d=d.apply(pd.to_numeric,errors="coerce").dropna(subset=["close"]).sort_index()
    return d

def dhan_historical_smoke_test(symbol="RELIANCE", days=30):
    """One-symbol end-to-end test: Dhan -> parser -> SQLite.

    This is intentionally separate from the 500-stock sync so a broken data
    request or database write can be diagnosed without wasting time.
    """
    symbol=str(symbol).upper().replace(".NS","").strip()
    before_con=_db()
    try:
        before=int(before_con.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",(symbol,)).fetchone()[0])
    finally:
        before_con.close()

    end=last_expected_nse_session()
    start=end-timedelta(days=int(days))
    started=time.perf_counter()
    d=dhan_history(symbol,start,end)
    request_seconds=time.perf_counter()-started
    if d is None or d.empty:
        raise RuntimeError(f"Dhan returned zero candles for {symbol} ({start} to {end}).")

    d=d.copy().sort_index()
    required=["open","high","low","close","volume"]
    missing=[x for x in required if x not in d.columns]
    if missing:
        raise RuntimeError("Parsed historical data is missing columns: "+", ".join(missing))

    con=_db()
    try:
        saved=_save(con,symbol,d)
        after=int(con.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",(symbol,)).fetchone()[0])
        bounds=con.execute("SELECT MIN(dt),MAX(dt) FROM candles WHERE symbol=?",(symbol,)).fetchone()
    finally:
        con.close()

    return {
        "symbol":symbol,"security_id":str(dhan_map().get(symbol,"")),
        "requested_start":str(start),"requested_end":str(end),
        "http/parser_candles":int(len(d)),"saved_rows":int(saved),
        "db_rows_before":before,"db_rows_after":after,
        "db_min":bounds[0] if bounds else None,"db_max":bounds[1] if bounds else None,
        "request_seconds":round(request_seconds,2),
        "sample_first":d.index[0].strftime("%Y-%m-%d"),
        "sample_last":d.index[-1].strftime("%Y-%m-%d"),
        "sample_close":float(d.close.iloc[-1]),
    }


def _bounds(con,s):
    return con.execute("SELECT MIN(dt),MAX(dt) FROM candles WHERE symbol=?",(s,)).fetchone()

def _save(con,s,d):
    if d.empty:return 0
    rows=[(s,pd.Timestamp(i).strftime("%Y-%m-%d"),float(r.open),float(r.high),
           float(r.low),float(r.close),float(r.volume)) for i,r in d.iterrows()]
    con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?)",rows)
    con.commit();return len(rows)

def _read_history_floor(con,symbol):
    """Return (earliest_available, probed_from) previously proven empty, or None."""
    row=con.execute("SELECT earliest_available,probed_from FROM dhan_history_floor WHERE symbol=?",
                    (symbol,)).fetchone()
    if not row or not row[0] or not row[1]:
        return None
    try:
        return pd.Timestamp(row[0]).date(),pd.Timestamp(row[1]).date()
    except Exception:
        return None


def _write_history_floor(con,symbol,earliest_available,probed_from):
    con.execute("""INSERT INTO dhan_history_floor(symbol,earliest_available,probed_from,checked_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       earliest_available=excluded.earliest_available,
                       probed_from=excluded.probed_from,
                       checked_at=excluded.checked_at""",
                (symbol,pd.Timestamp(earliest_available).strftime("%Y-%m-%d"),
                 pd.Timestamp(probed_from).strftime("%Y-%m-%d"),
                 datetime.now().isoformat(timespec="seconds")))
    con.commit()


def update_dhan_symbol(symbol,start_date,end_date,refresh_tail_days=0):
    """Fill only the missing head/tail ranges for one symbol.

    `refresh_tail_days` re-requests the most recent N calendar days even though
    candles already exist there. Without it the newest stored bar was never
    revisited, so any candle first written while its session was still open (or
    later revised/adjusted by the exchange) stayed wrong forever - MAX(dt) had
    already advanced past it, and the "end_date > mx" branch below could never
    reach back to correct it. INSERT OR REPLACE makes the re-request idempotent.

    Every request is wrapped for DhanNoDataError (DH-907). The sync asks for
    ~1900 calendar days of history, which predates the listing date of every
    recently listed constituent (AFCONS, ATHERENERG, BAJAJHFL, BELRISE,
    BHARTIHEXA, ANANDRATHI ...). For those the head-gap request can only ever
    return "no data present", so treating it as an error made them fail loudly
    on every sync forever. It is recorded as an expected condition instead, and
    the proven floor is remembered so the futile request is not repeated.
    """
    s=str(symbol).upper().replace(".NS","");con=_db()
    try:
        mn,mx=_bounds(con,s)
        if not mn:
            try:
                return _save(con,s,dhan_history(s,start_date,end_date))
            except DhanNoDataError:
                _note_no_data(s,start_date,end_date,"Dhan has no candles anywhere in the requested range")
                return 0
        n=0;mn=pd.Timestamp(mn).date();mx=pd.Timestamp(mx).date()
        req_start=pd.Timestamp(start_date).date()
        if req_start<mn:
            floor=_read_history_floor(con,s)
            # Skip only when the earlier probe covered at least this far back
            # AND our earliest stored bar has not moved since; widening the
            # historical range re-probes rather than trusting a narrower answer.
            proven_empty=floor is not None and floor[0]==mn and req_start>=floor[1]
            if not proven_empty:
                head_end=mn-timedelta(days=1)
                try:
                    n+=_save(con,s,dhan_history(s,req_start,head_end))
                except DhanNoDataError:
                    _write_history_floor(con,s,mn,req_start)
                    _note_no_data(s,req_start,head_end,
                                  f"Dhan history for this symbol starts at {mn} (listed later than the requested start)")
        tail=int(refresh_tail_days or 0)
        if tail>0:
            tail_start=max(mn,mx-timedelta(days=tail))
            if tail_start<=pd.Timestamp(end_date).date():
                try:
                    n+=_save(con,s,dhan_history(s,tail_start,end_date))
                except DhanNoDataError:
                    _note_no_data(s,tail_start,end_date,"no sessions published by Dhan for the tail range yet")
        elif pd.Timestamp(end_date).date()>mx:
            try:
                n+=_save(con,s,dhan_history(s,mx+timedelta(days=1),end_date))
            except DhanNoDataError:
                _note_no_data(s,mx+timedelta(days=1),end_date,"no sessions published by Dhan for the tail range yet")
        return n
    finally:con.close()

def _read_cache(con,s,start_date,end_date):
    d=pd.read_sql_query("""SELECT dt,open,high,low,close,volume FROM candles
        WHERE symbol=? AND dt>=? AND dt<=? ORDER BY dt""",con,
        params=(s,pd.Timestamp(start_date).strftime("%Y-%m-%d"),pd.Timestamp(end_date).strftime("%Y-%m-%d")))
    if d.empty:return pd.DataFrame()
    d.dt=pd.to_datetime(d.dt);d=d.set_index("dt");d.index.name="date";return d

def download_prices(tickers,start,end,max_workers=4,refresh_tail_days=0):
    """
    Dhan historical loader with bounded concurrency and transparent failures.

    Dhan data requests are globally rate-limited by dhan_history(). The worker
    count therefore controls concurrency, not API request rate. Existing local
    candles are reused and only missing ranges are requested.
    """
    if not dhan_configured():
        raise RuntimeError(
            "Dhan credentials are not configured. Add DHAN_CLIENT_ID and "
            "DHAN_ACCESS_TOKEN to Streamlit Secrets."
        )

    dhan_map()
    tickers=list(dict.fromkeys(tickers))
    errors=[]
    workers=max(1,min(int(max_workers),5))

    def worker(symbol):
        try:
            saved=update_dhan_symbol(symbol,start,end,refresh_tail_days=refresh_tail_days)
            return symbol,saved,None
        except Exception as exc:
            return symbol,0,str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(worker,s):s for s in tickers}
        for fut in as_completed(futures):
            symbol,saved,err=fut.result()
            if err:
                errors.append(f"{symbol}: {err}")

    con=_db()
    out={}
    try:
        for symbol in tickers:
            clean=str(symbol).upper().replace(".NS","")
            d=_read_cache(con,clean,start,end)
            if not d.empty:
                out[symbol]=d
    finally:
        con.close()

    # Keep the last build errors available to the Data Manager instead of
    # silently converting API failures into "0 cached stocks".
    global _DHAN_LAST_DATA_ERRORS
    _DHAN_LAST_DATA_ERRORS=errors[-100:]

    return out

def dhan_live_ltp(symbols):
    mp=dhan_map()
    pairs=[(mp[s.replace(".NS","").upper()],s.replace(".NS","").upper())
           for s in symbols if s.replace(".NS","").upper() in mp]
    if not pairs:return {}
    # Throttled + retried like every other Dhan data call - see _dhan_post().
    r=_dhan_post("/marketfeed/ltp",{"NSE_EQ":[int(a) for a,b in pairs]},
                 timeout=20,label="LTP")
    raw=r.json().get("data",{}).get("NSE_EQ",{});rev={a:b for a,b in pairs}
    return {rev[str(k)]:float(v["last_price"]) for k,v in raw.items()
            if str(k) in rev and isinstance(v,dict) and v.get("last_price") is not None}

DHAN_QUOTE_CHUNK = 1000  # Dhan market-feed accepts up to 1000 instruments per request


def _dhan_quote_raw(security_ids):
    """POST /marketfeed/quote for one chunk of NSE_EQ security IDs, honouring the
    same global data-API rate limit AND 429 backoff as every other Dhan data
    call - see _dhan_post(). It used to throttle but not retry, so a single 429
    aborted the whole quote snapshot instead of waiting out the cooldown."""
    r = _dhan_post("/marketfeed/quote", {"NSE_EQ": [int(s) for s in security_ids]},
                   timeout=30, label="quote")
    return r.json().get("data", {}).get("NSE_EQ", {}) or {}


def _quote_num(payload, *keys):
    """Dhan has shipped several spellings of the same quote fields across API
    versions. Read the first key that carries a usable number instead of
    hard-coding one spelling and silently getting NaN."""
    for k in keys:
        if not isinstance(payload, dict):
            return np.nan
        if k in payload and payload[k] is not None:
            try:
                v = float(payload[k])
            except (TypeError, ValueError):
                continue
            if np.isfinite(v):
                return v
    return np.nan


def dhan_quote_snapshot(symbols):
    """Bulk live quote for NSE equities: last price plus the session's running
    open/high/low and volume.

    This is the piece the scanner was missing. dhan_live_ltp() returns only a
    last price, and the WebSocket manager only ever tracked the handful of
    active forward-test symbols - so a universe scan had no way to see today's
    price at all and always ranked yesterday's close.

    Returns {SYMBOL: {"ltp","open","high","low","prev_close","volume","ts"}}.
    Symbols Dhan does not return are simply absent; callers fall back to the
    stored daily candle rather than failing the whole scan.
    """
    clean = sorted({str(s).upper().replace(".NS", "").strip() for s in symbols if str(s).strip()})
    if not clean:
        return {}
    mp = dhan_map()
    pairs = [(mp[s], s) for s in clean if s in mp]
    if not pairs:
        return {}

    out = {}
    ts = datetime.now().isoformat(timespec="seconds")
    for i in range(0, len(pairs), DHAN_QUOTE_CHUNK):
        chunk = pairs[i:i + DHAN_QUOTE_CHUNK]
        rev = {str(sid): sym for sid, sym in chunk}
        try:
            raw = _dhan_quote_raw([sid for sid, _ in chunk])
        except Exception:
            continue
        for sid, payload in raw.items():
            sym = rev.get(str(sid))
            if not sym or not isinstance(payload, dict):
                continue
            ohlc = payload.get("ohlc") if isinstance(payload.get("ohlc"), dict) else {}
            ltp = _quote_num(payload, "last_price", "LTP", "lastTradedPrice")
            if not np.isfinite(ltp) or ltp <= 0:
                continue
            out[sym] = {
                "ltp": ltp,
                "open": _quote_num(ohlc, "open", "Open"),
                "high": _quote_num(ohlc, "high", "High"),
                "low": _quote_num(ohlc, "low", "Low"),
                # Dhan reports the PREVIOUS session's close in the quote ohlc
                # block (same convention as other Indian broker APIs), so it is
                # deliberately not treated as today's close.
                "prev_close": _quote_num(ohlc, "close", "Close"),
                "volume": _quote_num(payload, "volume", "Volume", "last_quantity"),
                "ts": ts,
            }
    return out


def live_price_map(symbols, prefer_websocket=True):
    """Best available current price per symbol, with provenance.

    Order of preference: a fresh WebSocket tick (already streaming, zero extra
    API cost) -> a bulk REST quote -> nothing. Returns
    {SYMBOL: {"price","ts","source"}}.
    """
    clean = sorted({str(s).upper().replace(".NS", "").strip() for s in symbols if str(s).strip()})
    if not clean:
        return {}
    prices = {}

    if prefer_websocket:
        try:
            live = read_live_prices(clean)
        except Exception:
            live = pd.DataFrame()
        if live is not None and not live.empty:
            cutoff = datetime.now() - timedelta(minutes=LIVE_TICK_MAX_AGE_MINUTES)
            for r in live.itertuples():
                try:
                    px = float(r.ltp)
                    tick_ts = pd.Timestamp(r.ts).to_pydatetime()
                except Exception:
                    continue
                if np.isfinite(px) and px > 0 and tick_ts >= cutoff:
                    prices[str(r.symbol).upper()] = {
                        "price": px, "ts": str(r.ts), "source": "WEBSOCKET"
                    }

    missing = [s for s in clean if s not in prices]
    if missing:
        try:
            quotes = dhan_quote_snapshot(missing)
        except Exception:
            quotes = {}
        for sym, q in quotes.items():
            prices[sym] = {"price": float(q["ltp"]), "ts": q["ts"], "source": "QUOTE"}
    return prices


def build_live_daily_bars(symbols):
    """Today's still-forming daily candle per symbol, from the live quote feed.

    Only meaningful while the cash session is open. Outside market hours the
    completed daily candle already IS the latest price, so this returns {} and
    callers transparently keep using the stored candle.
    """
    if not nse_market_is_open():
        return {}
    try:
        quotes = dhan_quote_snapshot(symbols)
    except Exception:
        return {}
    session = date.today()
    bars = {}
    for sym, q in quotes.items():
        ltp = float(q["ltp"])
        o = q["open"] if np.isfinite(q["open"]) and q["open"] > 0 else ltp
        # The running high/low can lag the last tick by a moment, so widen them
        # with the LTP instead of publishing a bar where close > high.
        h = max(ltp, q["high"] if np.isfinite(q["high"]) else ltp, o)
        l = min(ltp, q["low"] if np.isfinite(q["low"]) and q["low"] > 0 else ltp, o)
        v = q["volume"] if np.isfinite(q["volume"]) and q["volume"] >= 0 else 0.0
        bars[sym] = {"date": session, "open": o, "high": h, "low": l,
                     "close": ltp, "volume": v, "ts": q["ts"]}
    return bars


def apply_live_bar(df, bar):
    """Return a copy of a daily OHLCV frame with today's forming candle appended
    (or replaced if a row for that date already exists).

    Deliberately in-memory only: a partial intraday bar must never be written
    into the `candles` table, or every backtest from that day forward would be
    computed against a candle that never actually closed at that price.
    """
    if df is None or df.empty or not bar:
        return df
    try:
        ts = pd.Timestamp(bar["date"])
        close = float(bar["close"])
    except Exception:
        return df
    if not np.isfinite(close) or close <= 0:
        return df
    values = {
        "open": float(bar.get("open", close) or close),
        "high": float(bar.get("high", close) or close),
        "low": float(bar.get("low", close) or close),
        "close": close,
        "volume": float(bar.get("volume", 0.0) or 0.0),
    }
    # Build the row as its own float frame and concat, rather than assigning via
    # .loc: a cached frame whose OHLCV columns came back from SQLite as int64
    # raises on an in-place float assignment under pandas 2/3 dtype rules.
    row = pd.DataFrame(
        {c: [values.get(c, np.nan)] for c in df.columns},
        index=pd.DatetimeIndex([ts], name=df.index.name),
    )
    out = df[df.index != ts].copy()
    # Widen only the OHLCV columns we are about to write. astype(errors="ignore")
    # would do this in one line but is deprecated from pandas 2.2 onward.
    for c in values:
        if c in out.columns and not pd.api.types.is_float_dtype(out[c]):
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    out = pd.concat([out, row])
    out.index.name = df.index.name
    return out.sort_index()


def attach_live_bars(data, symbols=None):
    """Overlay today's forming candle onto a {ticker: daily_df} scan dataset.

    Returns (data_with_live, live_bars). On any failure the original dataset is
    returned unchanged - a live-feed problem degrades the scan to end-of-day
    prices, it never blocks it.
    """
    if not data:
        return data, {}
    wanted = symbols if symbols is not None else list(data.keys())
    bars = build_live_daily_bars(wanted)
    if not bars:
        return data, {}
    merged = {}
    for ticker, df in data.items():
        key = str(ticker).upper().replace(".NS", "")
        bar = bars.get(key)
        merged[ticker] = apply_live_bar(df, bar) if bar else df
    return merged, bars


def dhan_connection_diagnostic():
    """
    Safe, read-only Dhan connectivity test.

    Checks:
      1. Secrets are present.
      2. Dhan instrument master can be downloaded.
      3. RELIANCE has an NSE equity security ID.
      4. Authenticated Dhan LTP endpoint responds.
      5. Authenticated Dhan historical endpoint returns candles.

    No order endpoint is called.
    """
    result={
        "credentials":False,
        "instrument_master":False,
        "reliance_mapping":False,
        "ltp_api":False,
        "historical_api":False,
        "details":[]
    }

    if not dhan_configured():
        result["details"].append("Dhan secrets missing: DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN")
        return result

    result["credentials"]=True

    try:
        mp=dhan_map()
        result["instrument_master"]=True
    except Exception as exc:
        result["details"].append(f"Instrument master failed: {exc}")
        return result

    sid=mp.get("RELIANCE")
    if not sid:
        result["details"].append("RELIANCE NSE security ID was not found in Dhan instrument master.")
        return result

    result["reliance_mapping"]=True
    result["details"].append(f"RELIANCE security ID: {sid}")

    try:
        ltp=dhan_live_ltp(["RELIANCE"])
        if ltp:
            result["ltp_api"]=True
            result["details"].append(f"RELIANCE LTP: ₹{ltp.get('RELIANCE', 0):,.2f}")
        else:
            result["details"].append("LTP endpoint responded but returned no RELIANCE price.")
    except Exception as exc:
        result["details"].append(f"LTP API failed: {exc}")

    try:
        d=dhan_history("RELIANCE",date.today()-timedelta(days=7),date.today())
        if d is not None and not d.empty:
            result["historical_api"]=True
            result["details"].append(f"Historical API returned {len(d)} candles.")
        else:
            result["details"].append("Historical API returned no candles.")
    except Exception as exc:
        result["details"].append(f"Historical API failed: {exc}")

    return result


@st.cache_data(ttl=3600)
def _ensure_ws_tables():
    con=_db()
    con.execute("""CREATE TABLE IF NOT EXISTS live_ticks(
        symbol TEXT NOT NULL, ts TEXT NOT NULL, ltp REAL,
        ltt INTEGER, volume REAL, buy_qty REAL, sell_qty REAL,
        PRIMARY KEY(symbol,ts))""")
    con.commit(); con.close()


# ========================= PERSISTENT DHAN WEBSOCKET =========================
class DhanLiveManager:
    """
    One persistent market-hours WebSocket for the active forward-test list.
    It runs outside the Streamlit UI thread, reconnects automatically, and
    stores the latest tick in SQLite. The UI reads the stored latest prices.
    """
    def __init__(self):
        self.thread=None
        self.stop_event=threading.Event()
        self.lock=threading.Lock()
        self.symbols=()
        self.status="STOPPED"
        self.last_error=""
        self.last_tick=None
        self.last_persist={}

    def _set_status(self,status,error=""):
        with self.lock:
            self.status=status
            self.last_error=error

    def update_symbols(self,symbols):
        clean=tuple(sorted({str(s).upper().replace(".NS","") for s in symbols if str(s).strip()}))
        with self.lock:
            changed=clean!=self.symbols
            self.symbols=clean
        if changed and clean and (self.thread is None or not self.thread.is_alive()):
            self.start()
        return changed

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread=threading.Thread(
            target=self._run,
            name="dhan-live-feed",
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self._set_status("STOPPING")

    def _run(self):
        # The official DhanHQ-py MarketFeed handles the websocket protocol.
        from dhanhq import DhanContext, MarketFeed

        backoff=2
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    symbols=list(self.symbols)
                if not symbols:
                    self._set_status("WAITING")
                    self.stop_event.wait(2)
                    continue

                mp=dhan_map()
                instruments=[]
                reverse={}
                for s in symbols:
                    sid=mp.get(s)
                    if sid:
                        instruments.append((MarketFeed.NSE,str(sid),MarketFeed.Ticker))
                        reverse[str(sid)]=s

                if not instruments:
                    self._set_status("WAITING","No Dhan security IDs found for active candidates")
                    self.stop_event.wait(5)
                    continue

                self._set_status("CONNECTING")
                ctx=DhanContext(
                    str(_secret_required("DHAN_CLIENT_ID")),
                    str(_dhan_ensure_fresh_token())
                )
                feed=MarketFeed(ctx,instruments,version="v2")
                feed.run_forever()
                self._set_status("CONNECTED")
                backoff=2

                while not self.stop_event.is_set():
                    data=feed.get_data()
                    if not data:
                        time.sleep(0.05)
                        continue

                    packets=data if isinstance(data,list) else [data]
                    for pkt in packets:
                        if not isinstance(pkt,dict):
                            continue
                        sid=str(pkt.get("security_id",pkt.get("SecurityId","")))
                        symbol=reverse.get(sid)
                        ltp=pkt.get("LTP",pkt.get("last_price",pkt.get("LastTradedPrice")))
                        if not symbol or ltp is None:
                            continue
                        self._save_tick(symbol,float(ltp),pkt)

                try:
                    feed.disconnect()
                except Exception:
                    pass

            except Exception as e:
                self._set_status("RECONNECTING",str(e))
                # Automatic reconnect with capped exponential backoff.
                self.stop_event.wait(backoff)
                backoff=min(backoff*2,30)

        self._set_status("STOPPED")

    def _save_tick(self,symbol,ltp,pkt):
        # Persist at most once per second per symbol. Dhan remains tick-by-tick,
        # but the database does not need every tick for a research dashboard.
        now_dt=datetime.now()
        last=self.last_persist.get(symbol)
        if last is not None and (now_dt-last).total_seconds()<1.0:
            with self.lock:
                self.last_tick=now_dt.isoformat(timespec="seconds")
                self.status="LIVE"
            return
        self.last_persist[symbol]=now_dt
        now=now_dt.isoformat(timespec="seconds")
        con=_db()
        try:
            con.execute("""
                CREATE TABLE IF NOT EXISTS live_latest(
                    symbol TEXT PRIMARY KEY, ts TEXT, ltp REAL,
                    volume REAL, raw TEXT
                )
            """)
            con.execute("""
                INSERT OR REPLACE INTO live_latest(symbol,ts,ltp,volume,raw)
                VALUES(?,?,?,?,?)
            """,(
                symbol,now,ltp,
                pkt.get("volume",pkt.get("Volume")),
                str(pkt)
            ))
            con.commit()
        finally:
            con.close()
        with self.lock:
            self.last_tick=now
            self.status="LIVE"

    def snapshot(self):
        with self.lock:
            return self.status,self.last_error,self.last_tick,list(self.symbols)

@st.cache_resource
def get_dhan_live_manager():
    return DhanLiveManager()

def start_persistent_live_feed(symbols):
    mgr=get_dhan_live_manager()
    mgr.update_symbols(symbols)
    mgr.start()
    return mgr

def stop_persistent_live_feed():
    mgr=get_dhan_live_manager()
    mgr.stop()
    return mgr

def read_live_prices(symbols=None):
    con=_db()
    try:
        if symbols:
            clean=[str(s).upper().replace(".NS","") for s in symbols]
            placeholders=",".join(["?"]*len(clean))
            q=pd.read_sql_query(
                f"SELECT symbol,ts,ltp,volume FROM live_latest WHERE symbol IN ({placeholders})",
                con,params=clean
            )
        else:
            q=pd.read_sql_query("SELECT symbol,ts,ltp,volume FROM live_latest",con)
    except Exception:
        q=pd.DataFrame(columns=["symbol","ts","ltp","volume"])
    finally:
        con.close()
    return q

def live_forward_test_table():
    con = _db()
    try:
        q = pd.read_sql_query(
            "SELECT * FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",
            con
        )
    finally:
        con.close()

    if q.empty:
        return q

    # WebSocket ticks first, then a REST quote for anything the socket has not
    # delivered. Previously this table stayed blank whenever the socket was
    # connecting, throttled, or had simply not ticked an illiquid symbol yet.
    prices = live_price_map(q.symbol.tolist())
    if prices:
        q["LTP"] = [prices.get(str(s).upper(), {}).get("price", np.nan) for s in q.symbol]
        q["Live Updated"] = [prices.get(str(s).upper(), {}).get("ts", "") for s in q.symbol]
        q["Price Source"] = [prices.get(str(s).upper(), {}).get("source", "—") for s in q.symbol]
    else:
        q["LTP"] = np.nan
        q["Live Updated"] = ""
        q["Price Source"] = "—"

    entry = pd.to_numeric(q["entry"], errors="coerce")
    stop = pd.to_numeric(q["sl"], errors="coerce")
    target = pd.to_numeric(q["target"], errors="coerce")
    ltp = pd.to_numeric(q["LTP"], errors="coerce")
    # Fall back to the last stored close so the P/L column is never blank.
    ltp = ltp.fillna(pd.to_numeric(q.get("ltp"), errors="coerce"))
    q["LTP"] = ltp
    q["P/L %"] = (ltp / entry - 1) * 100
    q["P/L ₹"] = ltp - entry
    q["Unrealized R"] = (ltp - entry) / (entry - stop).replace(0, np.nan)
    q["To Target %"] = (target / ltp - 1) * 100
    q["To Stop %"] = (stop / ltp - 1) * 100
    return q


FUNDAMENTAL_CACHE_TTL_HOURS = 24
NEWS_CACHE_TTL_HOURS = 6

def _ensure_research_tables():
    con=_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS fundamentals_cache(
            symbol TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT, score REAL, status TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS news_cache(
            symbol TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT, sentiment REAL, risk REAL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS research_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT, symbol TEXT,
            study TEXT, score REAL, outcome TEXT, r_multiple REAL, regime TEXT, features TEXT)""")
        con.commit()
    finally: con.close()

def _td_get(endpoint, params, timeout=30):
    if not twelvedata_configured(): return {}
    try:
        r=requests.get(f"{TWELVE_BASE}/{endpoint}",headers=_td_headers(),params=params,timeout=timeout)
    except Exception as exc:
        return {"_error":f"Network error: {exc}"}
    if not r.ok: return {"_error":f"HTTP {r.status_code}"}
    try:j=r.json()
    except Exception:return {"_error":"Invalid JSON"}
    if isinstance(j,dict) and j.get("status")=="error": return {"_error":j.get("message","API error")}
    return j

def _fresh(ts, hours):
    try:return (datetime.now()-pd.Timestamp(ts).to_pydatetime()).total_seconds()<hours*3600
    except Exception:return False

def _fundamental_score(payload):
    if not payload:return 0,"NO_DATA",[]
    vals=[]; flags=[]
    stats=payload.get("statistics",{}) if isinstance(payload.get("statistics"),dict) else {}
    prof=payload.get("profile",{}) if isinstance(payload.get("profile"),dict) else {}
    def num(*keys):
        for k in keys:
            v=stats.get(k,prof.get(k))
            try:
                if v is not None:return float(v)
            except:pass
        return np.nan
    roe=num("return_on_equity","roe"); margin=num("profit_margin","net_profit_margin"); debt=num("debt_to_equity","debt_equity"); pe=num("pe_ratio","trailing_pe"); pb=num("price_to_book","pb_ratio")
    score=50
    if np.isfinite(roe): score += 10 if roe>=15 else 5 if roe>=10 else -5 if roe<5 else 0
    if np.isfinite(margin): score += 10 if margin>=10 else 5 if margin>=5 else -5 if margin<0 else 0
    if np.isfinite(debt): score += 10 if debt<=0.5 else 5 if debt<=1 else -10 if debt>2 else 0
    if np.isfinite(pe): score += 5 if 5<=pe<=35 else -5 if pe>60 else 0
    if np.isfinite(pb): score += 5 if pb<=6 else -3 if pb>10 else 0
    if np.isfinite(roe) and roe<0: flags.append("Negative ROE")
    if np.isfinite(margin) and margin<0: flags.append("Negative margin")
    if np.isfinite(debt) and debt>2: flags.append("High leverage")
    return int(np.clip(score,0,100)),("STRONG" if score>=75 else "WATCH" if score>=55 else "WEAK"),flags

def company_info(ticker):
    _ensure_research_tables(); sym=str(ticker).upper().replace(".NS","")
    con=_db()
    try:
        row=con.execute("SELECT fetched_at,payload,score,status FROM fundamentals_cache WHERE symbol=?",(sym,)).fetchone()
    finally:con.close()
    if row and _fresh(row[0],FUNDAMENTAL_CACHE_TTL_HOURS):
        try:return json.loads(row[1]),[]
        except:return {},[]
    if not twelvedata_configured(): return {},["Twelve Data key not configured"]
    payload={}
    for ep in ["profile","statistics"]:
        j=_td_get(ep,{"symbol":sym,"exchange":"XNSE"})
        if j and "_error" not in j: payload[ep]=j
    score,status,flags=_fundamental_score(payload)
    con=_db()
    try:
        con.execute("INSERT OR REPLACE INTO fundamentals_cache VALUES(?,?,?,?,?)",(sym,datetime.now().isoformat(timespec="seconds"),json.dumps(payload,default=str),score,status));con.commit()
    finally:con.close()
    return payload,flags

def news_snapshot(ticker,days=30):
    _ensure_research_tables(); sym=str(ticker).upper().replace(".NS","")
    con=_db()
    try:row=con.execute("SELECT fetched_at,payload,sentiment,risk FROM news_cache WHERE symbol=?",(sym,)).fetchone()
    finally:con.close()
    if row and _fresh(row[0],NEWS_CACHE_TTL_HOURS):
        try:return json.loads(row[1]),float(row[2]),float(row[3])
        except:return [],0,0
    if not twelvedata_configured():return [],0,0
    j=_td_get("press_releases",{"symbol":sym,"exchange":"XNSE","start_date":(date.today()-timedelta(days=days)).isoformat(),"end_date":date.today().isoformat(),"outputsize":10})
    items=j.get("press_releases",[]) if isinstance(j,dict) else []
    pos=["order","contract","growth","profit","approval","launch","partnership","expansion","acquisition","award"]
    neg=["fraud","default","resign","resignation","penalty","investigation","notice","downgrade","loss","pledge","insolvency","regulatory"]
    sentiment=0; risk=0
    for it in items:
        text=(str(it.get("title",""))+" "+str(it.get("body",""))).lower()
        sentiment += sum(text.count(w) for w in pos)-sum(text.count(w) for w in neg)
        risk += sum(text.count(w) for w in neg)
    sentiment=float(np.clip(sentiment*5,-100,100)); risk=float(np.clip(risk*15,0,100))
    con=_db()
    try:con.execute("INSERT OR REPLACE INTO news_cache VALUES(?,?,?,?,?)",(sym,datetime.now().isoformat(timespec="seconds"),json.dumps(items,default=str),sentiment,risk));con.commit()
    finally:con.close()
    return items,sentiment,risk

def advanced_small_micro_safety(info,d,news_risk=0):
    score,status,flags=safety(info,d)
    extra=0
    if d is not None and len(d)>=60:
        traded=(d.close*d.volume).tail(20).mean(); gap=(d.open/d.close.shift(1)-1).abs().tail(60)
        circuit=(d.close.pct_change().abs().tail(120)>=0.095).sum()
        if traded<1_000_000: extra-=10; flags.append("Thin traded value")
        elif traded<5_000_000: extra-=5; flags.append("Moderate liquidity")
        if gap.mean()>0.05: extra-=10; flags.append("Frequent large gaps")
        if circuit>=3: extra-=15; flags.append("Frequent circuit-like moves")
    if news_risk>=30: extra-=10; flags.append("News/event risk")
    score=int(np.clip(score+extra,0,100)); status="ELIGIBLE" if score>=70 else "CAUTION" if score>=50 else "REJECT"
    return score,status,flags


# ========================= S4 SEPA — UNIVERSE + SAFETY GATE (shared by S1-S4) =========================
# Part of the SEPA (Specific Entry Point Analysis) replacement of live Strategy 4.
# nse_liquid_universe()/clean_liquid_universe() are shared by every strategy's live
# scan (see scan_dataset()) so that no strategy, not only S4, can surface a
# manipulated/illiquid name. The SEPA strategy logic itself lives further down,
# next to s4_base_conditions()/strategy_signal().

def nse_liquid_universe(exclude_sme=True):
    """The Dhan NSE cash-equity list (~1900-2100 names depending on the day's
    scrip master). Same universe for S1, S2, S3, and S4 - no BSE, no SME board
    by default, no derivatives-only names."""
    symbols = sorted(dhan_map().keys())
    tickers = [f"{s}.NS" for s in symbols]
    if exclude_sme:
        tickers = [t for t in tickers if not t.endswith("SM.NS") and "-SM" not in t]
    return tickers


def _price_action_quality(d, lookback=60):
    """Scores candle quality over the last `lookback` sessions:
      - low average wick-to-range ratio (clean bodies, not indecision candles)
      - close-location-value averaging mid-to-high (closes near the top of the
        day's range more often than not)
      - no clustering of huge single-day wicks or overnight gaps (operator-stock tell)
    Returns (score 0-100, flags list).
    """
    x = d.tail(lookback).copy()
    if len(x) < 20:
        return 0, ["Insufficient history for price action check"]

    rng = (x.high - x.low).replace(0, np.nan)
    upper_wick = (x.high - x[["open", "close"]].max(axis=1)) / rng
    lower_wick = (x[["open", "close"]].min(axis=1) - x.low) / rng
    wick_ratio = (upper_wick + lower_wick).clip(lower=0)
    close_loc = (x.close - x.low) / rng

    avg_wick_ratio = float(wick_ratio.mean())
    avg_close_loc = float(close_loc.mean())
    extreme_wick_days = int((wick_ratio >= 0.65).sum())

    gap_pct = ((x.open - x.close.shift(1)) / x.close.shift(1)).abs()
    big_gap_days = int((gap_pct >= 0.07).sum())

    flags = []
    score = 100
    if avg_wick_ratio > 0.55:
        score -= 25
        flags.append("High average wick ratio (indecisive/choppy candles)")
    elif avg_wick_ratio > 0.40:
        score -= 10
        flags.append("Moderate wick ratio")

    if avg_close_loc < 0.45:
        score -= 15
        flags.append("Closes tend toward the lower half of the daily range")

    if extreme_wick_days >= 8:
        score -= 20
        flags.append(f"{extreme_wick_days} extreme-wick days in last {lookback} sessions")

    if big_gap_days >= 5:
        score -= 20
        flags.append(f"{big_gap_days} large overnight gaps in last {lookback} sessions")

    return int(np.clip(score, 0, 100)), flags


def clean_liquid_universe(data, fundamentals=None, min_price=20,
                           min_safety_score=60, min_price_action_score=55):
    """Takes {ticker: OHLCV df} for nse_liquid_universe(), returns
    (clean_data, audit_df) where clean_data only contains tickers that are
    liquid, not manipulation-prone (via advanced_small_micro_safety), AND show
    decent price action. Feed clean_data into ANY strategy scan (S1-S4).

    fundamentals: optional {ticker: info_dict} from company_info() if already
    fetched - improves the debt/insider part of the safety check. Fine to omit.
    """
    fundamentals = fundamentals or {}
    clean = {}
    audit = []

    for ticker, d in data.items():
        if d is None or len(d) < 60:
            audit.append({"Ticker": str(ticker).replace(".NS", ""), "Passed": False,
                          "Reason": "Insufficient history"})
            continue

        info = fundamentals.get(ticker, {})
        safety_score, safety_status, safety_flags = advanced_small_micro_safety(info, d)
        price_ok = float(d.close.iloc[-1]) >= min_price
        pa_score, pa_flags = _price_action_quality(d)

        passed = (
            safety_status != "REJECT" and
            safety_score >= min_safety_score and
            price_ok and
            pa_score >= min_price_action_score
        )

        all_flags = list(safety_flags) + pa_flags + ([] if price_ok else [f"Price below {min_price}"])
        audit.append({
            "Ticker": str(ticker).replace(".NS", ""),
            "Safety Score": safety_score,
            "Price Action Score": pa_score,
            "Passed": passed,
            "Flags": ", ".join(all_flags) if all_flags else "",
        })
        if passed:
            clean[ticker] = d

    audit_df = pd.DataFrame(audit)
    if not audit_df.empty:
        audit_df = audit_df.sort_values(["Passed", "Safety Score"], ascending=[False, False])
    return clean, audit_df


# ========================= FOREX + CRYPTO DATA ENGINE =========================
TWELVE_BASE="https://api.twelvedata.com"

def twelvedata_configured():
    try:
        return bool(_secret("TWELVEDATA_API_KEY"))
    except Exception:
        return False

def _td_headers():
    return {"Authorization":f"apikey {str(_secret_required('TWELVEDATA_API_KEY'))}"}


# ============================================================================
# FUNDAMENTAL SCREENS A & B (Phase 2) — universe-wide quality screens built
# from raw Twelve Data financial statements, since Twelve Data has no direct
# "Piotroski score" field.
#
# UNVERIFIED ASSUMPTION — FLAGGED, NOT SILENTLY FIXED: this sandbox has no
# TWELVEDATA_API_KEY / live network access, so the exact field names inside
# Twelve Data's income_statement/balance_sheet/cash_flow responses have never
# been confirmed against a real response. _stmt_num() below tries several
# plausible key spellings per field, but they are GUESSES, exactly like the
# original patch this was built from. Do not trust a Piotroski score, ROCE
# fallback, or Screen A/B pass/fail without spot-checking it against a real
# filing first — see the st.info() caveat rendered in the Screen A/B tab.
# ============================================================================

def _td_get_statements(sym, outputsize=2):
    """Fetch income statement, balance sheet, cash flow (annual periods).
    outputsize defaults to 2 (enough for Screen A's YoY Piotroski checks);
    Screen B's 5-year sales-growth check needs 5 years of history, so its
    caller (run_fundamental_screens) passes outputsize=5 explicitly rather
    than this function always requesting 5 years regardless of which screen
    is running (that would cost extra Twelve Data API weight for history
    Screen A never uses).
    Returns dict with keys: income, balance, cashflow — each a list of
    period dicts (most recent first) or [] on failure. Never raises.
    """
    if not twelvedata_configured():
        return {"income": [], "balance": [], "cashflow": []}
    out = {}
    for key, ep in [("income", "income_statement"),
                     ("balance", "balance_sheet"),
                     ("cashflow", "cash_flow")]:
        try:
            j = _td_get(ep, {"symbol": sym, "exchange": "XNSE",
                              "period": "annual", "outputsize": outputsize})
            if isinstance(j, dict) and "_error" not in j:
                rows = j.get(key + "_statement", j.get("statement", []))
                if not rows:
                    for v in j.values():
                        if isinstance(v, list):
                            rows = v
                            break
                out[key] = rows if isinstance(rows, list) else []
            else:
                out[key] = []
        except Exception:
            out[key] = []
    return out


def _stmt_num(period_dict, *keys):
    """Pull a numeric field from one statement period, trying several
    possible key spellings (Twelve Data naming varies by statement type)."""
    if not isinstance(period_dict, dict):
        return np.nan
    flat = {}
    for section in period_dict.values():
        if isinstance(section, dict):
            flat.update(section)
    flat.update(period_dict)
    for k in keys:
        v = flat.get(k)
        try:
            if v is not None:
                return float(v)
        except Exception:
            pass
    return np.nan


def piotroski_score(statements):
    """Standard 9-point Piotroski F-Score using 2 years of statements.
    Returns (score:int 0-9, detail:dict) — missing data scores that test 0
    rather than raising, so a partial statement still returns a usable score.
    """
    inc = statements.get("income", [])
    bal = statements.get("balance", [])
    cf = statements.get("cashflow", [])
    if len(inc) < 2 or len(bal) < 2 or len(cf) < 1:
        return 0, {"error": "Insufficient statement history (need 2 years)"}

    cur_inc, prev_inc = inc[0], inc[1]
    cur_bal, prev_bal = bal[0], bal[1]
    cur_cf = cf[0]

    net_income = _stmt_num(cur_inc, "net_income", "netIncome")
    total_assets_cur = _stmt_num(cur_bal, "total_assets", "totalAssets")
    total_assets_prev = _stmt_num(prev_bal, "total_assets", "totalAssets")
    cfo = _stmt_num(cur_cf, "operating_cash_flow", "cash_from_operating_activities")
    lt_debt_cur = _stmt_num(cur_bal, "long_term_debt", "longTermDebt")
    lt_debt_prev = _stmt_num(prev_bal, "long_term_debt", "longTermDebt")
    cur_assets_cur = _stmt_num(cur_bal, "total_current_assets", "totalCurrentAssets")
    cur_liab_cur = _stmt_num(cur_bal, "total_current_liabilities", "totalCurrentLiabilities")
    cur_assets_prev = _stmt_num(prev_bal, "total_current_assets", "totalCurrentAssets")
    cur_liab_prev = _stmt_num(prev_bal, "total_current_liabilities", "totalCurrentLiabilities")
    shares_cur = _stmt_num(cur_bal, "common_shares_outstanding", "shares_outstanding")
    shares_prev = _stmt_num(prev_bal, "common_shares_outstanding", "shares_outstanding")
    gross_profit_cur = _stmt_num(cur_inc, "gross_profit", "grossProfit")
    revenue_cur = _stmt_num(cur_inc, "sales", "total_revenue", "revenue")
    gross_profit_prev = _stmt_num(prev_inc, "gross_profit", "grossProfit")
    revenue_prev = _stmt_num(prev_inc, "sales", "total_revenue", "revenue")
    net_income_prev = _stmt_num(prev_inc, "net_income", "netIncome")

    def safe_div(a, b):
        return a / b if (pd.notna(a) and pd.notna(b) and b != 0) else np.nan

    roa_cur = safe_div(net_income, total_assets_cur)
    roa_prev = safe_div(net_income_prev, total_assets_prev)
    leverage_cur = safe_div(lt_debt_cur, total_assets_cur)
    leverage_prev = safe_div(lt_debt_prev, total_assets_prev)
    current_ratio_cur = safe_div(cur_assets_cur, cur_liab_cur)
    current_ratio_prev = safe_div(cur_assets_prev, cur_liab_prev)
    gross_margin_cur = safe_div(gross_profit_cur, revenue_cur)
    gross_margin_prev = safe_div(gross_profit_prev, revenue_prev)
    asset_turnover_cur = safe_div(revenue_cur, total_assets_cur)
    asset_turnover_prev = safe_div(revenue_prev, total_assets_prev)

    tests = {}
    tests["positive_roa"] = pd.notna(roa_cur) and roa_cur > 0
    tests["positive_cfo"] = pd.notna(cfo) and cfo > 0
    tests["roa_improving"] = pd.notna(roa_cur) and pd.notna(roa_prev) and roa_cur > roa_prev
    tests["cfo_gt_netincome"] = pd.notna(cfo) and pd.notna(net_income) and cfo > net_income
    tests["leverage_decreasing"] = pd.notna(leverage_cur) and pd.notna(leverage_prev) and leverage_cur < leverage_prev
    tests["current_ratio_improving"] = pd.notna(current_ratio_cur) and pd.notna(current_ratio_prev) and current_ratio_cur > current_ratio_prev
    tests["no_new_shares"] = pd.notna(shares_cur) and pd.notna(shares_prev) and shares_cur <= shares_prev
    tests["gross_margin_improving"] = pd.notna(gross_margin_cur) and pd.notna(gross_margin_prev) and gross_margin_cur > gross_margin_prev
    tests["asset_turnover_improving"] = pd.notna(asset_turnover_cur) and pd.notna(asset_turnover_prev) and asset_turnover_cur > asset_turnover_prev

    score = int(sum(1 for v in tests.values() if v))
    return score, tests


def screen_a_metrics(sym, info, statements, price_return_1y):
    """Screen A — momentum + quality growth (Piotroski = 9 required)."""
    stats = info.get("statistics", {}) if isinstance(info.get("statistics"), dict) else {}
    prof = info.get("profile", {}) if isinstance(info.get("profile"), dict) else {}

    def num(*keys):
        for k in keys:
            v = stats.get(k, prof.get(k))
            try:
                if v is not None:
                    return float(v)
            except Exception:
                pass
        return np.nan

    mcap = num("market_capitalization", "market_cap")
    roce = num("return_on_capital_employed", "roce")
    roe = num("return_on_equity", "roe")
    qsales_g = num("quarterly_revenue_growth_yoy", "yoy_quarterly_sales_growth")
    qprofit_g = num("quarterly_earnings_growth_yoy", "yoy_quarterly_profit_growth")

    # ROCE fallback: EBIT / (Total Assets - Current Liabilities), latest statement
    if pd.isna(roce) and statements.get("income") and statements.get("balance"):
        ebit = _stmt_num(statements["income"][0], "operating_income", "ebit")
        ta = _stmt_num(statements["balance"][0], "total_assets", "totalAssets")
        cl = _stmt_num(statements["balance"][0], "total_current_liabilities", "totalCurrentLiabilities")
        if pd.notna(ebit) and pd.notna(ta) and pd.notna(cl) and (ta - cl) != 0:
            roce = 100.0 * ebit / (ta - cl)

    pscore, pdetail = piotroski_score(statements)

    checks = {
        "Market Cap (200-20000cr)": pd.notna(mcap) and 200 <= mcap <= 20000,
        "1Yr Return > 0": pd.notna(price_return_1y) and price_return_1y > 0,
        "YoY Qtr Sales Growth > 10%": pd.notna(qsales_g) and qsales_g > 10,
        "YoY Qtr Profit Growth > 10%": pd.notna(qprofit_g) and qprofit_g > 10,
        "ROCE > 15%": pd.notna(roce) and roce > 15,
        "ROE > 15%": pd.notna(roe) and roe > 15,
        "Piotroski = 9": pscore == 9,
    }
    passed = all(checks.values())
    return {
        "Ticker": sym, "Screen": "A", "Pass": passed,
        "Market Cap": mcap, "1Yr Return %": price_return_1y,
        "YoY Qtr Sales %": qsales_g, "YoY Qtr Profit %": qprofit_g,
        "ROCE %": roce, "ROE %": roe, "Piotroski": pscore,
        "Checks": checks,
    }


def screen_b_metrics(sym, info, statements):
    """Screen B — quality value + dividend (Promoter Holding flagged N/A:
    India shareholding-pattern disclosure, not carried by Twelve Data)."""
    stats = info.get("statistics", {}) if isinstance(info.get("statistics"), dict) else {}
    prof = info.get("profile", {}) if isinstance(info.get("profile"), dict) else {}

    def num(*keys):
        for k in keys:
            v = stats.get(k, prof.get(k))
            try:
                if v is not None:
                    return float(v)
            except Exception:
                pass
        return np.nan

    mcap = num("market_capitalization", "market_cap")
    eps = num("eps", "trailing_eps")
    roe = num("return_on_equity", "roe")
    debt_eq = num("debt_to_equity", "debt_equity")
    pe = num("pe_ratio", "trailing_pe")
    current_ratio = num("current_ratio")
    div_yield = num("dividend_yield")

    roce = num("return_on_capital_employed", "roce")
    if pd.isna(roce) and statements.get("income") and statements.get("balance"):
        ebit = _stmt_num(statements["income"][0], "operating_income", "ebit")
        ta = _stmt_num(statements["balance"][0], "total_assets", "totalAssets")
        cl = _stmt_num(statements["balance"][0], "total_current_liabilities", "totalCurrentLiabilities")
        if pd.notna(ebit) and pd.notna(ta) and pd.notna(cl) and (ta - cl) != 0:
            roce = 100.0 * ebit / (ta - cl)

    # Sales growth 5Y — needs 5+ annual periods. run_fundamental_screens()
    # requests outputsize=5 whenever Screen B is selected (see
    # _td_get_statements docstring) so this actually computes instead of
    # always being left NaN.
    sales_g5 = np.nan
    inc = statements.get("income", [])
    if len(inc) >= 5:
        rev_now = _stmt_num(inc[0], "sales", "total_revenue", "revenue")
        rev_5y = _stmt_num(inc[4], "sales", "total_revenue", "revenue")
        if pd.notna(rev_now) and pd.notna(rev_5y) and rev_5y > 0:
            sales_g5 = 100.0 * ((rev_now / rev_5y) ** (1/5) - 1)

    net_profit_margin = num("profit_margin", "net_profit_margin")
    op_profit_g = np.nan
    if len(inc) >= 2:
        op_cur = _stmt_num(inc[0], "operating_income", "ebit")
        op_prev = _stmt_num(inc[1], "operating_income", "ebit")
        if pd.notna(op_cur) and pd.notna(op_prev) and op_prev != 0:
            op_profit_g = 100.0 * (op_cur - op_prev) / abs(op_prev)

    pfcf = np.nan
    cf = statements.get("cashflow", [])
    if cf and pd.notna(mcap):
        cfo = _stmt_num(cf[0], "operating_cash_flow", "cash_from_operating_activities")
        capex = _stmt_num(cf[0], "capital_expenditure", "capex")
        if pd.notna(cfo) and pd.notna(capex):
            fcf = cfo - abs(capex)
            if fcf > 0:
                pfcf = mcap / fcf

    checks = {
        "Market Cap > 5000cr": pd.notna(mcap) and mcap > 5000,
        "EPS > 15": pd.notna(eps) and eps > 15,
        "Sales Growth 5Y > 10%": (pd.notna(sales_g5) and sales_g5 > 10) if pd.notna(sales_g5) else None,
        "ROE > 15%": pd.notna(roe) and roe > 15,
        "ROCE > 15%": pd.notna(roce) and roce > 15,
        "Debt/Equity < 0.5": pd.notna(debt_eq) and debt_eq < 0.5,
        "Price/FCF > 0": pd.notna(pfcf) and pfcf > 0,
        "Net Profit Margin > 10%": pd.notna(net_profit_margin) and net_profit_margin > 10,
        "PE < 25": pd.notna(pe) and pe < 25,
        "Current Ratio > 1.5": pd.notna(current_ratio) and current_ratio > 1.5,
        "Dividend Yield > 1%": pd.notna(div_yield) and div_yield > 1,
        "Operating Profit Growth > 15%": pd.notna(op_profit_g) and op_profit_g > 15,
        "Promoter Holding > 40%": None,  # data not available via Twelve Data — never silently true
    }
    evaluated = {k: v for k, v in checks.items() if v is not None}
    unverifiable = [k for k, v in checks.items() if v is None]
    passed = all(evaluated.values()) if evaluated else False

    return {
        "Ticker": sym, "Screen": "B", "Pass": passed,
        "Unverifiable": ", ".join(unverifiable) if unverifiable else "",
        "Market Cap": mcap, "EPS": eps, "ROE %": roe, "ROCE %": roce,
        "Debt/Equity": debt_eq, "P/E": pe, "Current Ratio": current_ratio,
        "Dividend Yield %": div_yield, "Sales Growth 5Y %": sales_g5,
        "Op Profit Growth %": op_profit_g, "Net Profit Margin %": net_profit_margin,
        "P/FCF": pfcf,
        "Checks": checks,
    }


def run_fundamental_screens(universe_names, run_a=True, run_b=True, progress_cb=None):
    """Scans the given universes against Screen A and/or B.
    progress_cb(done:int, total:int, symbol:str) is called after each stock
    if provided, so the UI can render a live progress bar.
    Returns a single DataFrame with all results (both screens if both run).
    """
    symbols = set()
    for u in universe_names:
        try:
            symbols.update(index_universe(u))
        except Exception:
            continue
    symbols = sorted(symbols)

    # Screen B's 5-year sales-growth check needs 5 annual periods; Screen A
    # only ever looks at 2. Only pay the extra Twelve Data outputsize cost
    # when Screen B is actually selected.
    stmt_outputsize = 5 if run_b else 2

    rows = []
    total = len(symbols)
    for i, full_sym in enumerate(symbols):
        sym = full_sym.replace(".NS", "")
        try:
            info, flags = company_info(sym)
            statements = _td_get_statements(sym, outputsize=stmt_outputsize)

            price_return_1y = np.nan
            try:
                stats = info.get("statistics", {}) if isinstance(info, dict) else {}
                price_return_1y = float(stats.get("52_week_change", stats.get("year_change", np.nan)))
            except Exception:
                pass

            if run_a:
                rows.append(screen_a_metrics(sym, info, statements, price_return_1y))
            if run_b:
                rows.append(screen_b_metrics(sym, info, statements))
        except Exception as e:
            rows.append({"Ticker": sym, "Screen": "ERROR", "Pass": False, "Checks": {"error": str(e)}})
        finally:
            if progress_cb:
                progress_cb(i + 1, total, sym)
            time.sleep(0.15)  # gentle pacing against Twelve Data rate limits

    return pd.DataFrame(rows)


def add_fundamental_forward_candidates(results_df):
    """Persists PASSing fundamental candidates into the existing forward_tests
    table (tagged FUNDA/FUNDB), same table/schema pattern as
    add_forward_candidates()/add_smc_forward_candidates() so they show up in
    the Forward Testing tab automatically — no new table.

    Unlike the original draft of this function, entry/sl/target are never
    left NULL: refresh_forward_positions() unconditionally does
    float(row.entry)/float(row.sl)/float(row.target) on every ACTIVE
    forward_tests row and would raise on a NULL price field, so a candidate
    without a resolvable local Dhan close price is skipped rather than
    inserted with placeholder nulls.

    Fundamental screens are long-term theses, not tactical S1-S4 setups, so
    entry/stop/target use a wider 15% stop (vs S1-S4's 7%) while keeping the
    same 3R target convention used everywhere else in the app, so result_r
    stays on a comparable scale across strategies in forward_summary_table().
    """
    if results_df is None or results_df.empty:
        return 0
    passed = results_df[results_df["Pass"] == True]
    if passed.empty:
        return 0
    con = _db(); added = 0
    try:
        today = str(date.today())
        for _, r in passed.iterrows():
            symbol = str(r.get("Ticker", "")).upper()
            strategy = "FUND" + str(r.get("Screen", "")).upper()
            if not symbol or strategy not in {"FUNDA", "FUNDB"}:
                continue
            exists = con.execute(
                "SELECT id FROM forward_tests WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1",
                (symbol, strategy, today)
            ).fetchone()
            if exists:
                continue

            d = _read_cache(con, symbol, date.today()-timedelta(days=30), date.today())
            if d is None or d.empty:
                continue  # no local Dhan price to anchor entry — skip rather than insert a NULL price row
            entry = float(d.close.iloc[-1])
            if not np.isfinite(entry) or entry <= 0:
                continue
            stop = entry * 0.85
            target = entry + 3 * (entry - stop)

            score = float(r.get("Piotroski", r.get("ROE %", 0)) or 0)
            now = datetime.now().isoformat(timespec="seconds")
            snapshot = {k: r.get(k, None) for k in r.index}
            cur = con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                now, symbol, strategy, score, "FUNDAMENTAL", entry, stop, target, "ACTIVE",
                entry, 0.0, 0.0, None, None, now, today,
                json.dumps(snapshot, default=str, allow_nan=True)
            ))
            fid = int(cur.lastrowid); added += 1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                fid, now, today, entry, entry, entry, 0.0, 0.0, 0.0, "ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    if added:
        maybe_backup_db()
    return added


@st.cache_data(ttl=86400,show_spinner=False)
def td_history(symbol, interval="1day", start_date=None, end_date=None, outputsize=5000):
    """Historical OHLCV for Forex and Crypto through Twelve Data."""
    if not twelvedata_configured():
        raise RuntimeError("TWELVEDATA_API_KEY is not configured in Streamlit Secrets.")
    params={"symbol":symbol,"interval":interval,"outputsize":int(outputsize)}
    if start_date is not None: params["start_date"]=pd.Timestamp(start_date).strftime("%Y-%m-%d")
    if end_date is not None: params["end_date"]=pd.Timestamp(end_date).strftime("%Y-%m-%d")
    r=requests.get(f"{TWELVE_BASE}/time_series",headers=_td_headers(),params=params,timeout=45)
    if not r.ok: raise RuntimeError(f"Twelve Data {r.status_code}: {r.text[:300]}")
    j=r.json()
    if j.get("status")=="error": raise RuntimeError(j.get("message","Twelve Data error"))
    vals=j.get("values",[])
    if not vals: return pd.DataFrame(columns=["open","high","low","close","volume"])
    d=pd.DataFrame(vals)
    d["datetime"]=pd.to_datetime(d["datetime"],errors="coerce")
    d=d.set_index("datetime").sort_index()
    for c in ["open","high","low","close","volume"]:
        if c in d.columns:d[c]=pd.to_numeric(d[c],errors="coerce")
        else:d[c]=np.nan
    return d[["open","high","low","close","volume"]].dropna(subset=["close"])

@st.cache_data(ttl=30,show_spinner=False)
def td_price(symbol):
    if not twelvedata_configured():
        raise RuntimeError("TWELVEDATA_API_KEY is not configured in Streamlit Secrets.")
    r=requests.get(f"{TWELVE_BASE}/price",headers=_td_headers(),params={"symbol":symbol},timeout=20)
    if not r.ok: raise RuntimeError(f"Twelve Data price {r.status_code}: {r.text[:250]}")
    j=r.json()
    if j.get("status")=="error": raise RuntimeError(j.get("message","Twelve Data price error"))
    return float(j["price"])

def td_market_history(symbol, market, interval="1day", years=2):
    start=date.today()-timedelta(days=365*years)
    return td_history(symbol,interval,start,date.today(),5000)

def td_validate_symbol(symbol,market):
    try:
        d=td_history(symbol,"1day",date.today()-timedelta(days=30),date.today(),100)
        return (not d.empty),len(d),"OK" if not d.empty else "No data"
    except Exception as e:
        return False,0,str(e)

# ============================================================================
# SMC PRICE ACTION STRATEGY (Forex/Crypto) — HTF=4h, LTF=15min
# ============================================================================
# detect_swings, _atr, detect_msb, find_order_block, detect_fvg, detect_sfp,
# premium_discount_zone, confluence_score, smc_htf_context, smc_ltf_trigger,
# and smc_signal below are taken from the user-supplied SMC patch, with one
# change: detect_msb's "strong MSB" thresholds (candle-body % and
# close-beyond %) were hardcoded literals (0.6, 0.10) in the supplied code
# despite the patch's own header saying they're "already" configurable via
# function args — they are now actual parameters (defaulting to the same
# 0.6/0.10 values) so the UI slider added below can actually vary them
# without editing this file.
#
# smc_backtest()'s loop body, scan_smc_pairs(), and add_smc_forward_
# candidates() were NOT present in the supplied patch (it was cut off
# mid-function) and are Claude's completion of the behavior described in
# the patch's own docstrings/header comment (partial-at-1R, move-to-
# breakeven, final target at opposing HTF liquidity; live multi-pair scan;
# tracking into the existing forward_tests table as strategy='FX_SMC').
# Review these three specifically before trusting their output — they are
# not verbatim from your file.
# ============================================================================

def detect_swings(df, left=3, right=3):
    """Marks swing highs/lows using a simple fractal: a bar is a swing high
    if its high is the max within [i-left, i+right], swing low similarly.
    Returns df copy with 'swing_high' and 'swing_low' boolean columns.
    """
    d = df.copy()
    d["swing_high"] = False
    d["swing_low"] = False
    n = len(d)
    highs = d["high"].values
    lows = d["low"].values
    for i in range(left, n - right):
        window_h = highs[i-left:i+right+1]
        window_l = lows[i-left:i+right+1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            d.iloc[i, d.columns.get_loc("swing_high")] = True
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            d.iloc[i, d.columns.get_loc("swing_low")] = True
    return d


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def detect_msb(df_swung, atr_series, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Walks swing points in order, tracks the prevailing trend (based on
    sequence of higher-highs/higher-lows vs lower-highs/lower-lows), and
    flags the bar where price breaks the most recent counter-trend swing —
    i.e. an MSB. Only the break of the swing belonging to the DEEPEST leg
    counts (per the guide's rule), not every minor swing break.

    strong_body_pct / strong_close_beyond_pct: configurable "strong MSB"
    thresholds (calibrated guesses per the source guide, not exact values
    from any source) - candle body must be >= strong_body_pct of its range
    AND close beyond the broken level by >= strong_close_beyond_pct of the
    candle's range.

    Returns a list of dicts, one per detected MSB:
      {idx, direction ('bull'/'bear'), strength ('strong'/'weak'),
       broken_level, deepest_extreme_idx, origin_swing_idx}
    """
    d = df_swung
    swing_rows = d[(d["swing_high"]) | (d["swing_low"])].copy()
    if len(swing_rows) < 3:
        return []

    events = []
    seen_idx = set()
    last_swing_high_idx = None
    last_swing_low_idx = None
    deepest_low_idx = None
    deepest_high_idx = None

    for i in range(len(d)):
        row = d.iloc[i]
        if row["swing_high"]:
            last_swing_high_idx = i
            if deepest_high_idx is None or d["high"].iloc[i] > d["high"].iloc[deepest_high_idx]:
                deepest_high_idx = i
        if row["swing_low"]:
            last_swing_low_idx = i
            if deepest_low_idx is None or d["low"].iloc[i] < d["low"].iloc[deepest_low_idx]:
                deepest_low_idx = i

        # Bullish MSB: in a downtrend, close breaks above last swing high
        # that sits between the deepest low and now.
        if last_swing_high_idx is not None and deepest_low_idx is not None and last_swing_high_idx > deepest_low_idx:
            level = d["high"].iloc[last_swing_high_idx]
            if d["close"].iloc[i] > level and i not in seen_idx:
                body = abs(d["close"].iloc[i] - d["open"].iloc[i])
                rng = max(d["high"].iloc[i] - d["low"].iloc[i], 1e-9)
                close_beyond = d["close"].iloc[i] - level
                strong = (body / rng >= strong_body_pct) and (close_beyond >= strong_close_beyond_pct * rng)
                events.append({
                    "idx": i, "direction": "bull",
                    "strength": "strong" if strong else "weak",
                    "broken_level": float(level),
                    "deepest_extreme_idx": deepest_low_idx,
                    "origin_swing_idx": last_swing_high_idx,
                })
                seen_idx.add(i)
                deepest_low_idx = None  # reset leg after confirmed break

        # Bearish MSB: mirror logic breaking below last swing low.
        if last_swing_low_idx is not None and deepest_high_idx is not None and last_swing_low_idx > deepest_high_idx:
            level = d["low"].iloc[last_swing_low_idx]
            if d["close"].iloc[i] < level and i not in seen_idx:
                body = abs(d["close"].iloc[i] - d["open"].iloc[i])
                rng = max(d["high"].iloc[i] - d["low"].iloc[i], 1e-9)
                close_beyond = level - d["close"].iloc[i]
                strong = (body / rng >= strong_body_pct) and (close_beyond >= strong_close_beyond_pct * rng)
                events.append({
                    "idx": i, "direction": "bear",
                    "strength": "strong" if strong else "weak",
                    "broken_level": float(level),
                    "deepest_extreme_idx": deepest_high_idx,
                    "origin_swing_idx": last_swing_low_idx,
                })
                seen_idx.add(i)
                deepest_high_idx = None

    return events


def find_order_block(df, msb_event):
    """Scans backward from the MSB's origin swing to find the last
    opposite-colored candle before the impulsive leg. Returns dict with
    zone_top/zone_bottom or None if not found.
    """
    d = df
    start = msb_event["deepest_extreme_idx"]
    end = msb_event["origin_swing_idx"]
    if start is None or end is None or start >= end:
        return None
    bullish = msb_event["direction"] == "bull"
    for i in range(end, start - 1, -1):
        is_bear_candle = d["close"].iloc[i] < d["open"].iloc[i]
        is_bull_candle = d["close"].iloc[i] > d["open"].iloc[i]
        if bullish and is_bear_candle:
            return {"idx": i, "zone_top": float(d["high"].iloc[i]), "zone_bottom": float(d["low"].iloc[i]), "type": "demand_OB"}
        if (not bullish) and is_bull_candle:
            return {"idx": i, "zone_top": float(d["high"].iloc[i]), "zone_bottom": float(d["low"].iloc[i]), "type": "supply_OB"}
    return None


def detect_fvg(df, atr_series, min_atr_mult=0.10):
    """3-candle gap pattern. Bullish FVG: low[i] > high[i-2] (gap not
    filled by candle i-1). Bearish FVG: high[i] < low[i-2].
    Returns list of dicts: {idx, type, top, bottom}.
    """
    fvgs = []
    n = len(df)
    for i in range(2, n):
        atr_v = atr_series.iloc[i]
        if pd.isna(atr_v) or atr_v <= 0:
            continue
        min_gap = atr_v * min_atr_mult
        low_i = df["low"].iloc[i]
        high_i2 = df["high"].iloc[i-2]
        high_i = df["high"].iloc[i]
        low_i2 = df["low"].iloc[i-2]
        if low_i - high_i2 > min_gap:
            fvgs.append({"idx": i, "type": "bullish_fvg", "top": float(low_i), "bottom": float(high_i2)})
        if low_i2 - high_i > min_gap:
            fvgs.append({"idx": i, "type": "bearish_fvg", "top": float(low_i2), "bottom": float(high_i)})
    return fvgs


def detect_sfp(df_swung, atr_series, tolerance_atr_mult=0.15):
    """A bar that wicks beyond a prior swing high/low but closes back
    inside it — a stop-hunt / liquidity grab. Returns list of dicts.
    """
    d = df_swung
    sfps = []
    swing_highs = d.index[d["swing_high"]].tolist()
    swing_lows = d.index[d["swing_low"]].tolist()
    for i in range(len(d)):
        atr_v = atr_series.iloc[i]
        if pd.isna(atr_v) or atr_v <= 0:
            continue
        tol = atr_v * tolerance_atr_mult
        recent_highs = [sh for sh in swing_highs if sh < d.index[i]]
        if recent_highs:
            level = d.loc[recent_highs[-1], "high"]
            if d["high"].iloc[i] > level and d["high"].iloc[i] - level <= tol and d["close"].iloc[i] < level:
                sfps.append({"idx": i, "type": "bearish_sfp", "level": float(level)})
        recent_lows = [sl for sl in swing_lows if sl < d.index[i]]
        if recent_lows:
            level = d.loc[recent_lows[-1], "low"]
            if d["low"].iloc[i] < level and level - d["low"].iloc[i] <= tol and d["close"].iloc[i] > level:
                sfps.append({"idx": i, "type": "bullish_sfp", "level": float(level)})
    return sfps


def premium_discount_zone(swing_low_price, swing_high_price, current_price):
    """Returns (zone:'premium'/'discount'/'equilibrium', pct_of_range,
    ote_low, ote_high) — OTE = 0.7-0.8 retracement zone from swing extremes.
    """
    rng = swing_high_price - swing_low_price
    if rng <= 0:
        return "unknown", np.nan, np.nan, np.nan
    pct = (current_price - swing_low_price) / rng
    if pct >= 0.7:
        zone = "premium"
    elif pct <= 0.3:
        zone = "discount"
    else:
        zone = "equilibrium"
    ote_low = swing_low_price + 0.7 * rng
    ote_high = swing_low_price + 0.8 * rng
    return zone, round(pct, 3), ote_low, ote_high


def confluence_score(price_level, order_block, fvgs, sfps, tolerance_pct=0.0015):
    """Counts how many structures sit within tolerance of price_level.
    order_block: dict or None. fvgs/sfps: lists (already filtered to
    relevant recent ones by the caller). Returns (score:int, matched:list).
    """
    matched = []
    tol = price_level * tolerance_pct
    if order_block and order_block["zone_bottom"] - tol <= price_level <= order_block["zone_top"] + tol:
        matched.append(order_block["type"])
    for fvg in fvgs:
        if fvg["bottom"] - tol <= price_level <= fvg["top"] + tol:
            matched.append(fvg["type"])
    for sfp in sfps:
        if abs(sfp["level"] - price_level) <= tol:
            matched.append(sfp["type"])
    return len(matched), matched


def smc_htf_context(htf_df, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Full HTF read at the LATEST completed bar. Returns dict or None if
    no valid strong MSB / zone currently active.
    """
    d = detect_swings(htf_df)
    atr_s = _atr(d)
    msbs = detect_msb(d, atr_s, strong_body_pct, strong_close_beyond_pct)
    if not msbs:
        return None
    last_msb = msbs[-1]
    if last_msb["strength"] != "strong":
        return {"has_zone": False, "reason": "Last HTF MSB is weak — skip per guide's rule", "last_msb": last_msb}

    ob = find_order_block(d, last_msb)
    fvgs = detect_fvg(d, atr_s)
    sfps = detect_sfp(d, atr_s)

    deepest_idx = last_msb["deepest_extreme_idx"]
    origin_idx = last_msb["origin_swing_idx"]
    if last_msb["direction"] == "bull":
        zone_extreme = d["low"].iloc[deepest_idx]
        zone_origin = d["high"].iloc[origin_idx]
        swing_low_price, swing_high_price = zone_extreme, zone_origin
    else:
        zone_extreme = d["high"].iloc[deepest_idx]
        zone_origin = d["low"].iloc[origin_idx]
        swing_low_price, swing_high_price = zone_origin, zone_extreme

    current_price = float(d["close"].iloc[-1])
    zone_label, pct, ote_low, ote_high = premium_discount_zone(
        min(swing_low_price, swing_high_price), max(swing_low_price, swing_high_price), current_price
    )

    recent_fvgs = [f for f in fvgs if f["idx"] >= deepest_idx]
    recent_sfps = [s for s in sfps if s["idx"] >= deepest_idx]
    score, matched = confluence_score(current_price, ob, recent_fvgs, recent_sfps)

    bias_ok = (last_msb["direction"] == "bull" and zone_label == "discount") or \
              (last_msb["direction"] == "bear" and zone_label == "premium")

    return {
        "has_zone": True,
        "direction": last_msb["direction"],
        "msb": last_msb,
        "order_block": ob,
        "zone_label": zone_label,
        "zone_pct": pct,
        "ote_low": ote_low, "ote_high": ote_high,
        "confluence_score": score,
        "confluence_matched": matched,
        "bias_ok": bias_ok,
        "current_price": current_price,
        "swing_low": min(swing_low_price, swing_high_price),
        "swing_high": max(swing_low_price, swing_high_price),
    }


def smc_ltf_trigger(ltf_df, htf_ctx, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Checks if price is currently inside the HTF zone AND the LTF shows
    a micro-MSB (or SFP) confirming the HTF direction. Returns dict or None.
    """
    if not htf_ctx or not htf_ctx.get("has_zone"):
        return None
    price = float(ltf_df["close"].iloc[-1])
    in_zone = htf_ctx["swing_low"] <= price <= htf_ctx["swing_high"]
    if not in_zone:
        return None

    d = detect_swings(ltf_df)
    atr_s = _atr(d)
    micro_msbs = detect_msb(d, atr_s, strong_body_pct, strong_close_beyond_pct)
    if not micro_msbs:
        return None
    last_micro = micro_msbs[-1]
    if last_micro["idx"] < len(d) - 6:
        return None
    if last_micro["direction"] != htf_ctx["direction"]:
        return None

    sfps = detect_sfp(d, atr_s)
    recent_sfp = [s for s in sfps if s["idx"] >= len(d) - 6]

    return {
        "confirmed": True,
        "micro_msb": last_micro,
        "sfp_present": len(recent_sfp) > 0,
        "entry_price": float(d["close"].iloc[-1]),
        "trigger_idx": last_micro["idx"],
    }


def _smc_precompute(df, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """One-time precompute of swings/MSB/FVG/SFP for the FULL series.

    Used by smc_backtest() so it can do an O(log n) 'as of bar i' lookup
    per bar instead of what it did before: calling smc_htf_context()/
    smc_ltf_trigger() (which each re-run detect_swings/detect_msb from
    scratch) on an ever-growing slice ltf_df.iloc[:i+1] for every candidate
    bar. That growing-slice recompute is O(n) per call and was being called
    up to once per bar, making the whole backtest O(n^2) - this is what
    made the backtest hang/never finish on a ~5000-bar LTF series.

    This precompute is NOT a behavior change: detect_swings' fractal check
    at index k only ever reads bars [k-left, k+right], and detect_msb
    processes bars strictly in increasing order using only already-
    confirmed swings, so the value at any prefix of the series is
    identical whether computed on that prefix alone or on the full
    series and then read as-of that point. Same principle as the
    features_fast()/_regime_from_row() fix applied to the S1-S4 backtest.
    """
    swung = detect_swings(df)
    atr_s = _atr(swung)
    msbs = detect_msb(swung, atr_s, strong_body_pct, strong_close_beyond_pct)
    fvgs = detect_fvg(swung, atr_s)
    sfps = detect_sfp(swung, atr_s)
    return {"swung": swung, "atr": atr_s, "msbs": msbs, "msb_idx": [m["idx"] for m in msbs], "fvgs": fvgs, "sfps": sfps}


def _smc_htf_context_asof(pre, asof_idx):
    """O(log n) equivalent of smc_htf_context(), reading _smc_precompute()'s
    output as of bar asof_idx instead of recomputing from scratch."""
    if asof_idx < 0:
        return None
    pos = bisect.bisect_right(pre["msb_idx"], asof_idx) - 1
    if pos < 0:
        return None
    last_msb = pre["msbs"][pos]
    if last_msb["strength"] != "strong":
        return {"has_zone": False, "reason": "Last HTF MSB is weak — skip per guide's rule", "last_msb": last_msb}

    d = pre["swung"]
    ob = find_order_block(d, last_msb)
    deepest_idx = last_msb["deepest_extreme_idx"]
    origin_idx = last_msb["origin_swing_idx"]
    if last_msb["direction"] == "bull":
        swing_low_price = d["low"].iloc[deepest_idx]
        swing_high_price = d["high"].iloc[origin_idx]
    else:
        swing_low_price = d["low"].iloc[origin_idx]
        swing_high_price = d["high"].iloc[deepest_idx]

    current_price = float(d["close"].iloc[asof_idx])
    zone_label, pct, ote_low, ote_high = premium_discount_zone(
        min(swing_low_price, swing_high_price), max(swing_low_price, swing_high_price), current_price
    )

    recent_fvgs = [f for f in pre["fvgs"] if deepest_idx <= f["idx"] <= asof_idx]
    recent_sfps = [s for s in pre["sfps"] if deepest_idx <= s["idx"] <= asof_idx]
    score, matched = confluence_score(current_price, ob, recent_fvgs, recent_sfps)

    bias_ok = (last_msb["direction"] == "bull" and zone_label == "discount") or \
              (last_msb["direction"] == "bear" and zone_label == "premium")

    return {
        "has_zone": True,
        "direction": last_msb["direction"],
        "msb": last_msb,
        "order_block": ob,
        "zone_label": zone_label,
        "zone_pct": pct,
        "ote_low": ote_low, "ote_high": ote_high,
        "confluence_score": score,
        "confluence_matched": matched,
        "bias_ok": bias_ok,
        "current_price": current_price,
        "swing_low": min(swing_low_price, swing_high_price),
        "swing_high": max(swing_low_price, swing_high_price),
    }


def _smc_ltf_trigger_asof(pre, asof_idx, htf_ctx):
    """O(log n) equivalent of smc_ltf_trigger(), reading _smc_precompute()'s
    output as of bar asof_idx instead of recomputing from scratch."""
    if not htf_ctx or not htf_ctx.get("has_zone"):
        return None
    d = pre["swung"]
    price = float(d["close"].iloc[asof_idx])
    if not (htf_ctx["swing_low"] <= price <= htf_ctx["swing_high"]):
        return None
    pos = bisect.bisect_right(pre["msb_idx"], asof_idx) - 1
    if pos < 0:
        return None
    last_micro = pre["msbs"][pos]
    if last_micro["idx"] < asof_idx - 5:
        return None
    if last_micro["direction"] != htf_ctx["direction"]:
        return None
    recent_sfp = [s for s in pre["sfps"] if asof_idx - 5 <= s["idx"] <= asof_idx]
    return {
        "confirmed": True,
        "micro_msb": last_micro,
        "sfp_present": len(recent_sfp) > 0,
        "entry_price": price,
        "trigger_idx": last_micro["idx"],
    }


def smc_signal(htf_df, ltf_df, min_confluence=2, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Returns a signal dict if a valid trade setup exists right now,
    else None. Encodes the guide's stop/target rules directly.
    """
    htf_ctx = smc_htf_context(htf_df, strong_body_pct, strong_close_beyond_pct)
    if not htf_ctx or not htf_ctx.get("has_zone") or not htf_ctx.get("bias_ok"):
        return None
    if htf_ctx["confluence_score"] < min_confluence:
        return None

    ltf_trig = smc_ltf_trigger(ltf_df, htf_ctx, strong_body_pct, strong_close_beyond_pct)
    if not ltf_trig:
        return None

    direction = htf_ctx["direction"]
    entry = ltf_trig["entry_price"]

    if direction == "bull":
        stop = htf_ctx["swing_low"] * 0.999
        risk_per_unit = entry - stop
        target = htf_ctx["swing_high"]
    else:
        stop = htf_ctx["swing_high"] * 1.001
        risk_per_unit = stop - entry
        target = htf_ctx["swing_low"]

    if risk_per_unit <= 0:
        return None
    rr = abs(target - entry) / risk_per_unit

    return {
        "direction": direction,
        "entry": round(entry, 6),
        "stop": round(stop, 6),
        "target": round(target, 6),
        "risk_reward": round(rr, 2),
        "confluence_score": htf_ctx["confluence_score"],
        "confluence_matched": htf_ctx["confluence_matched"],
        "zone_label": htf_ctx["zone_label"],
        "msb_strength": htf_ctx["msb"]["strength"],
        "sfp_confirmation": ltf_trig["sfp_present"],
        "note": "Confirm macro/news calendar manually before entry — not automated in this system.",
    }


def smc_backtest(htf_df, ltf_df, capital=100000, risk_pct=1.0, min_confluence=2, slip=0.0005,
                  strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Walks the LTF series bar-by-bar, re-evaluating HTF context every N
    bars (approximating a live re-scan), simulating entries per smc_signal
    logic. Applies: partial at 1R (half position, then stop moved to
    breakeven), final target at the opposing HTF swing (liquidity).
    Returns (trades_df, equity_curve_list).

    NOT present in the supplied patch (file was truncated mid-loop) —
    this loop body is Claude's completion of the behavior described in the
    function's own docstring/header comment. Review before trusting it.

    SIMPLIFICATION: slip is a fixed percentage placeholder applied to the
    entry price (default 0.05%), not a real spread/liquidity/session model.
    Do not treat backtest R-multiples as production-accurate without this
    caveat in mind — the UI surfaces this same warning next to the results.

    PERFORMANCE: uses _smc_precompute()/_smc_htf_context_asof()/
    _smc_ltf_trigger_asof() rather than calling smc_htf_context()/
    smc_ltf_trigger() on a growing ltf_df.iloc[:i+1] slice per bar - the
    growing-slice version re-ran detect_swings/detect_msb from scratch on
    every candidate bar (O(n) per call, called up to once per bar), making
    the whole backtest O(n^2) and causing it to hang/never finish on a
    full ~5000-bar LTF series. See _smc_precompute()'s docstring for why
    this is a pure performance fix with no behavior change.
    """
    equity = float(capital)
    rows = []
    equity_curve = [equity]
    htf_recompute_every = 16  # ~ once per HTF bar equivalent (4h/15m = 16)
    i = 60  # warmup for swing/ATR detection
    n = len(ltf_df)
    if n <= i + 1 or len(htf_df) < 60:
        return pd.DataFrame(rows), equity_curve

    htf_pre = _smc_precompute(htf_df, strong_body_pct, strong_close_beyond_pct)
    ltf_pre = _smc_precompute(ltf_df, strong_body_pct, strong_close_beyond_pct)
    htf_ctx_cache = None
    pos = None

    while i < n - 1:
        if pos is None:
            if htf_ctx_cache is None or i % htf_recompute_every == 0:
                htf_asof = int(htf_df.index.searchsorted(ltf_df.index[i], side="right")) - 1
                htf_ctx_cache = _smc_htf_context_asof(htf_pre, htf_asof) if htf_asof >= 60 else None

            sig = None
            if htf_ctx_cache and htf_ctx_cache.get("has_zone") and htf_ctx_cache.get("bias_ok") \
               and htf_ctx_cache["confluence_score"] >= min_confluence:
                ltf_trig = _smc_ltf_trigger_asof(ltf_pre, i, htf_ctx_cache)
                if ltf_trig:
                    direction = htf_ctx_cache["direction"]
                    raw_entry = float(ltf_df["close"].iloc[i])
                    entry = raw_entry * (1 + slip) if direction == "bull" else raw_entry * (1 - slip)
                    if direction == "bull":
                        stop = htf_ctx_cache["swing_low"] * 0.999
                        risk_per_unit = entry - stop
                        target = htf_ctx_cache["swing_high"]
                    else:
                        stop = htf_ctx_cache["swing_high"] * 1.001
                        risk_per_unit = stop - entry
                        target = htf_ctx_cache["swing_low"]
                    if risk_per_unit > 0 and abs(target - entry) / risk_per_unit >= 1.0:
                        sig = {
                            "direction": direction, "entry": entry, "stop": stop, "target": target,
                            "risk_per_unit": risk_per_unit, "entry_idx": i, "partial_taken": False,
                            "confluence_score": htf_ctx_cache["confluence_score"],
                            "msb_strength": htf_ctx_cache["msb"]["strength"],
                        }
            if sig:
                pos = sig
                htf_ctx_cache = None  # force a fresh HTF read before the next entry
        else:
            bar = ltf_df.iloc[i]
            direction = pos["direction"]
            one_r_level = pos["entry"] + pos["risk_per_unit"] if direction == "bull" else pos["entry"] - pos["risk_per_unit"]
            exit_now, exit_price, outcome = False, None, None

            if direction == "bull":
                if not pos["partial_taken"] and bar["high"] >= one_r_level:
                    pos["partial_taken"] = True
                    pos["stop"] = pos["entry"]  # move to breakeven
                if bar["low"] <= pos["stop"]:
                    exit_now, exit_price = True, pos["stop"]
                elif bar["high"] >= pos["target"]:
                    exit_now, exit_price = True, pos["target"]
            else:
                if not pos["partial_taken"] and bar["low"] <= one_r_level:
                    pos["partial_taken"] = True
                    pos["stop"] = pos["entry"]
                if bar["high"] >= pos["stop"]:
                    exit_now, exit_price = True, pos["stop"]
                elif bar["low"] <= pos["target"]:
                    exit_now, exit_price = True, pos["target"]

            if i == n - 2 and not exit_now:
                exit_now, exit_price, outcome = True, float(ltf_df["close"].iloc[i]), "TIMEOUT"

            if exit_now:
                final_r = (exit_price - pos["entry"]) / pos["risk_per_unit"] if direction == "bull" \
                    else (pos["entry"] - exit_price) / pos["risk_per_unit"]
                # Half the position was already realized at +1R if the partial
                # fired; the other half rides to the final exit (>=0R once the
                # stop is at breakeven).
                blended_r = 0.5 * 1.0 + 0.5 * final_r if pos["partial_taken"] else final_r
                if outcome is None:
                    outcome = "WIN" if blended_r > 0 else "LOSS"
                risk_cash = equity * (risk_pct / 100.0)
                equity += risk_cash * blended_r
                equity_curve.append(equity)
                rows.append({
                    "Entry Date": ltf_df.index[pos["entry_idx"]], "Exit Date": ltf_df.index[i],
                    "Direction": direction.upper(), "Entry": round(pos["entry"], 6),
                    "Stop": round(pos["stop"], 6), "Target": round(pos["target"], 6),
                    "Exit": round(exit_price, 6), "Partial at 1R": pos["partial_taken"],
                    "R": round(blended_r, 3), "Outcome": outcome,
                    "Confluence": pos["confluence_score"], "MSB Strength": pos["msb_strength"],
                    "Holding Bars": i - pos["entry_idx"],
                })
                pos = None
        i += 1

    return pd.DataFrame(rows), equity_curve


def scan_smc_pairs(pairs, market="Forex", min_confluence=2, strong_body_pct=0.6, strong_close_beyond_pct=0.10):
    """Live multi-pair SMC scan: fetches HTF(4h)+LTF(15min) data for each
    pair via Twelve Data and evaluates smc_signal(). One bad pair never
    blanks the rest (per-pair try/except, matching this app's existing
    scanner pattern). Returns a DataFrame of current setups (possibly
    empty). NOT present in the supplied patch - Claude's completion.
    """
    rows = []
    for pair in pairs:
        try:
            htf_df = td_market_history(pair, market, "4h", years=1)
            ltf_df = td_market_history(pair, market, "15min", years=1)
            if htf_df.empty or ltf_df.empty or len(htf_df) < 60 or len(ltf_df) < 60:
                continue
            sig = smc_signal(htf_df, ltf_df, min_confluence, strong_body_pct, strong_close_beyond_pct)
            if sig:
                rows.append({"Pair": pair, **sig})
        except Exception as e:
            rows.append({"Pair": pair, "direction": "ERROR", "entry": np.nan, "stop": np.nan,
                         "target": np.nan, "risk_reward": np.nan, "confluence_score": np.nan,
                         "confluence_matched": [], "zone_label": str(e), "msb_strength": "",
                         "sfp_confirmation": False, "note": ""})
    return pd.DataFrame(rows)


def add_smc_forward_candidates(candidates):
    """Persist SMC scanner signals into the EXISTING forward_tests table,
    tagged strategy='FX_SMC' - same table/schema as add_forward_candidates(),
    no new table created. NOT present in the supplied patch - Claude's
    completion, modeled directly on add_forward_candidates()'s pattern.
    """
    if candidates is None or len(candidates) == 0:
        return 0
    valid = candidates[candidates.get("direction", pd.Series(dtype=str)) != "ERROR"] if "direction" in candidates.columns else candidates
    if valid.empty:
        return 0
    con = _db(); added = 0
    try:
        today = str(date.today())
        for _, r in valid.iterrows():
            symbol = str(r.get("Pair", "")).upper()
            entry = float(r.get("entry", np.nan)); sl = float(r.get("stop", np.nan)); target = float(r.get("target", np.nan))
            if not symbol or not np.isfinite(entry) or entry <= 0 or not np.isfinite(sl) or not np.isfinite(target):
                continue
            exists = con.execute(
                """SELECT id FROM forward_tests WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1""",
                (symbol, "FX_SMC", today)
            ).fetchone()
            if exists:
                continue
            now = datetime.now().isoformat(timespec="seconds")
            # forward_tests' "score" column is 0-100 elsewhere (S1-S4); SMC has
            # no natural 0-100 score, so confluence_score (typically 2-5) is
            # scaled for rough display/sort convenience only - not comparable
            # to S1-S4 scores.
            display_score = float(min(100, r.get("confluence_score", 0) * 20))
            snapshot = {k: r.get(k, None) for k in r.index}
            cur = con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                now, symbol, "FX_SMC", display_score, str(r.get("zone_label", "")),
                entry, sl, target, "ACTIVE", entry, 0.0, 0.0, None, None, now,
                today, json.dumps(snapshot, default=str, allow_nan=True)
            ))
            fid = int(cur.lastrowid); added += 1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                fid, now, today, entry, entry, entry, 0.0, 0.0, 0.0, "ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    if added:
        maybe_backup_db()
    return added


# ========================= INDICATORS =========================

def ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def sma(s,n): return s.rolling(n,min_periods=n).mean()

def rsi(s,n=14):
    d=s.diff()
    up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=up/dn.replace(0,np.nan)
    return 100-100/(1+rs)

def _monthly_asof(d):
    m=d.resample("ME").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    # Build a current in-progress month from daily data; this is known as of each scan date.
    cur_key=d.index[-1].to_period("M")
    cur=d[d.index.to_period("M")==cur_key]
    if not cur.empty:
        m.loc[cur.index[-1].to_period("M").end_time.normalize(),["open","high","low","close","volume"]]=[
            cur.open.iloc[0],cur.high.max(),cur.low.min(),cur.close.iloc[-1],cur.volume.sum()
        ]
    return m

def _weekly_asof(d):
    return d.resample("W-FRI").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})

def features(d):
    x=d.copy()
    for n in [10,20,50,200,250]:
        x[f"ema{n}"]=ema(x.close,n)
    x["vol20"]=sma(x.volume,20)
    x["vol30"]=sma(x.volume,30)
    x["rsi14"]=rsi(x.close)
    x["relvol"]=x.volume/x.vol20

    tr=pd.concat([x.high-x.low,(x.high-x.close.shift()).abs(),
                  (x.low-x.close.shift()).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14).mean()

    w=_weekly_asof(x)
    w["rsi14"]=rsi(w.close,14)
    w["ema20"]=ema(w.close,20)
    w["ema50"]=ema(w.close,50)
    # As-of mapping: use the weekly bar containing today's date, not a future week.
    wkvals=[]
    for dt in x.index:
        wk=w[w.index <= dt]
        wkvals.append(wk.iloc[-1] if not wk.empty else pd.Series(dtype=float))
    x["wrsi14"]=[v.get("rsi14",np.nan) for v in wkvals]
    x["wema20"]=[v.get("ema20",np.nan) for v in wkvals]
    x["wema50"]=[v.get("ema50",np.nan) for v in wkvals]
    x["wclose"]=[v.get("close",np.nan) for v in wkvals]

    m=_monthly_asof(x)
    m["rsi14"]=rsi(m.close,14)
    m["ema10"]=ema(m.close,10)
    m["ema15"]=ema(m.close,15)
    m["ema20"]=ema(m.close,20)
    m["mom"]=m.close.pct_change()*100
    m["prev_close"]=m.close.shift(1)
    m["prev_high"]=m.high.shift(1)
    m["prev_low"]=m.low.shift(1)

    # Monthly max momentum over 20 months, as of the current month.
    m["mom20max"]=m.mom.rolling(20,min_periods=1).max()

    # Monthly EMA10/20 bullish cross on each month.
    cross=(m.ema10>m.ema20)&(m.ema10.shift(1)<=m.ema20.shift(1))
    m["cross_10_20"]=cross.astype(int)
    m["cross_count20"]=m.cross_10_20.rolling(20,min_periods=1).sum()

    # Daily rows mapped to current as-of month.
    vals=[]
    for dt in x.index:
        mm=m[m.index.to_period("M") <= dt.to_period("M")]
        vals.append(mm.iloc[-1] if not mm.empty else pd.Series(dtype=float))
    x["mclose"]=[v.get("close",np.nan) for v in vals]
    x["mopen"]=[v.get("open",np.nan) for v in vals]
    x["mhigh"]=[v.get("high",np.nan) for v in vals]
    x["mlow"]=[v.get("low",np.nan) for v in vals]
    x["mrsi14"]=[v.get("rsi14",np.nan) for v in vals]
    x["mema10"]=[v.get("ema10",np.nan) for v in vals]
    x["mema15"]=[v.get("ema15",np.nan) for v in vals]
    x["mema20"]=[v.get("ema20",np.nan) for v in vals]
    x["mmom"]=[v.get("mom",np.nan) for v in vals]
    x["mmax20"]= [v.get("mom20max",np.nan) for v in vals]
    x["mprevclose"]=[v.get("prev_close",np.nan) for v in vals]
    x["mprevhigh"]=[v.get("prev_high",np.nan) for v in vals]
    x["mprevlow"]=[v.get("prev_low",np.nan) for v in vals]
    x["m_cross_count20"]=[v.get("cross_count20",np.nan) for v in vals]
    x["m_cross_10_20"]=[v.get("cross_10_20",np.nan) for v in vals]
    return x

# ========================= STRATEGIES =========================

def _pct_change(s):
    return s.pct_change()*100

def _cross_up(a,b):
    return (a>b)&(a.shift(1)<=b.shift(1))

def _rolling_count(condition, window, offset=1):
    # Screener-style "count(window, offset where condition)": evaluate the
    # previous `window` observations, excluding the current bar.
    return condition.shift(offset).rolling(window, min_periods=1).sum()

def s4_base_conditions(x):
    """Every exact Strategy 4 condition EXCEPT the daily close<=1.03*EMA20
    proximity rule. Shared by strategy_signal(s=4) (which ANDs the exact 3%
    rule back in) and s4_ema20_extension_calibration(), which studies what
    the historically best-performing EMA20 distance actually is instead of
    assuming 3% without evidence."""
    monthly_bull_cross = (
        (x.mema10 > x.mema20) &
        (x.mema10.shift(1) <= x.mema20.shift(1))
    )
    monthly_bull_cross_count = (
        monthly_bull_cross.shift(1)
        .rolling(20, min_periods=20)
        .sum()
    )
    monthly_reclaim = (
        (x.mclose > x.mema10) &
        (x.mprevclose <= x.mema10)
    )
    return (
        (x.mmom >= 20) &
        (x.mrsi14 >= 50) &
        (x.mema10 >= x.mema20) &
        (x.vol30 >= 50000) &
        (x.close >= 20) &
        (
            (monthly_bull_cross_count >= 1) |
            monthly_reclaim
        )
    )


# ========================= S4 SEPA STRATEGY (replaces live S4) =========================
# Minervini "SEPA" (Specific Entry Point Analysis): fundamental template, trend
# template, and monthly/weekly/daily VCP-VCC entry timing. This REPLACES the old
# literal-translation S4 formula (s4_base_conditions() above) as the LIVE S4 rule
# via strategy_signal(x, s=4) below. s4_base_conditions() itself is untouched and
# keeps powering s4_ema20_extension_calibration(), a separate research tool.
#
# The old "S4 Recovery" pattern-study functions that used to live in this file
# (strategy4_recovery_features/signal, _s4_recovery_quality, study_s4_recovery,
# and their walk-forward variant) have been removed - SEPA fully replaces that
# research direction, nothing from it is reused here.

SEPA_CACHE_TTL_HOURS = 24

def _sepa_fundamentals_payload(symbol):
    """Fetch + cache quarterly earnings and statistics for the SEPA fundamental
    screen. Reuses the fundamentals_cache table already created by
    _ensure_research_tables()."""
    _ensure_research_tables()
    sym = str(symbol).upper().replace(".NS", "").replace(".BO", "")
    con = _db()
    try:
        row = con.execute(
            "SELECT fetched_at,payload FROM fundamentals_cache WHERE symbol=?", (f"SEPA_{sym}",)
        ).fetchone()
    finally:
        con.close()
    if row and _fresh(row[0], SEPA_CACHE_TTL_HOURS):
        try:
            return json.loads(row[1])
        except Exception:
            pass
    if not twelvedata_configured():
        return {}
    payload = {}
    for ep, params in [
        ("earnings", {"symbol": sym, "exchange": "XNSE"}),
        ("statistics", {"symbol": sym, "exchange": "XNSE"}),
        ("profile", {"symbol": sym, "exchange": "XNSE"}),
    ]:
        j = _td_get(ep, params)
        if j and "_error" not in j:
            payload[ep] = j
    con = _db()
    try:
        con.execute(
            "INSERT OR REPLACE INTO fundamentals_cache VALUES(?,?,?,?,?)",
            (f"SEPA_{sym}", datetime.now().isoformat(timespec="seconds"),
             json.dumps(payload, default=str), 0, "SEPA_RAW"),
        )
        con.commit()
    finally:
        con.close()
    return payload


def sepa_fundamental_screen(symbol, d=None, mcap_min_cr=100, mcap_max_cr=5000):
    """The Minervini fundamental template (Screen C, S4-specific). Returns
    per-point pass/fail/unverifiable, an overall score (0-100), and ELIGIBLE /
    WATCH / REJECT status. `d` is the daily OHLCV frame (price/volume/RSI/MA
    points come from features() rather than an external API).

    KNOWN DATA GAP: Twelve Data's quarterly revenue is not reliably populated
    for Indian small/microcaps, so "Sales QoQ growth" always reports
    "Unverifiable" here. Do not treat "Unverifiable" as a pass anywhere
    downstream - it is a genuine gap, not a soft pass.
    """
    payload = _sepa_fundamentals_payload(symbol)
    earnings = payload.get("earnings", {}) if isinstance(payload.get("earnings"), dict) else {}
    stats = payload.get("statistics", {}) if isinstance(payload.get("statistics"), dict) else {}
    prof = payload.get("profile", {}) if isinstance(payload.get("profile"), dict) else {}

    def num(src, *keys):
        for k in keys:
            v = src.get(k)
            try:
                if v is not None:
                    return float(v)
            except Exception:
                pass
        return np.nan

    points = {}

    quarterly = earnings.get("quarterly", []) if isinstance(earnings.get("quarterly"), list) else []
    if len(quarterly) >= 5:
        eps_latest = float(quarterly[0].get("eps_actual", np.nan))
        eps_prev_q = float(quarterly[1].get("eps_actual", np.nan))
        eps_prev_yr = float(quarterly[4].get("eps_actual", np.nan))
        eps_3y = [float(q.get("eps_actual", np.nan)) for q in quarterly[:13] if q.get("eps_actual") is not None]
        p1_pass = np.isfinite(eps_latest) and np.isfinite(eps_prev_q) and eps_prev_q > 0 and (eps_latest / eps_prev_q - 1) >= 0.25
        p2_pass = (eps_3y[-1] > 0 and (eps_3y[0] / eps_3y[-1] - 1) >= 0.20) if len(eps_3y) >= 8 else None
        p3_pass = np.isfinite(eps_latest) and np.isfinite(eps_prev_yr) and eps_prev_yr > 0 and eps_latest > eps_prev_yr
        points["EPS QoQ >=25%"] = p1_pass
        points["EPS 3Y CAGR >20%"] = p2_pass if p2_pass is not None else "Unverifiable"
        points["EPS YoY growth"] = p3_pass
    else:
        points["EPS QoQ >=25%"] = "Unverifiable"
        points["EPS 3Y CAGR >20%"] = "Unverifiable"
        points["EPS YoY growth"] = "Unverifiable"

    points["Sales QoQ growth"] = "Unverifiable"  # Twelve Data revenue coverage gap - see docstring above.

    mcap = num(stats, "market_capitalization") or num(prof, "market_capitalization")
    mcap_cr = mcap / 1e7 if np.isfinite(mcap) else np.nan
    points["Market cap band (100-5000 Cr)"] = (
        bool(mcap_min_cr <= mcap_cr <= mcap_max_cr) if np.isfinite(mcap_cr) else "Unverifiable"
    )
    points["Is microcap (<500 Cr)"] = bool(mcap_cr < 500) if np.isfinite(mcap_cr) else "Unverifiable"

    if d is not None and len(d) >= 210:
        x = features(d)
        z = x.iloc[-1]
        vol20 = float(z.vol20) if pd.notna(z.vol20) else np.nan
        points["Avg volume (1mo) > 50,000"] = bool(np.isfinite(vol20) and vol20 > 50_000)
        points["Price > 20"] = bool(z.close > 20)
        points["RSI(14) > 40"] = bool(pd.notna(z.rsi14) and z.rsi14 > 40)
        points["Price > 200 EMA"] = bool(pd.notna(z.ema200) and z.close > z.ema200)
        points["50 EMA > 200 EMA (timing)"] = bool(pd.notna(z.ema50) and pd.notna(z.ema200) and z.ema50 > z.ema200)
    else:
        for k in ["Avg volume (1mo) > 50,000", "Price > 20", "RSI(14) > 40",
                   "Price > 200 EMA", "50 EMA > 200 EMA (timing)"]:
            points[k] = "Unverifiable"

    hard_pass = [v for v in points.values() if v is True]
    hard_fail = [v for v in points.values() if v is False]
    verifiable_total = len(hard_pass) + len(hard_fail)
    score = int(round(100 * len(hard_pass) / verifiable_total)) if verifiable_total else 0
    status = "ELIGIBLE" if score >= 70 else "WATCH" if score >= 45 else "REJECT"

    return {
        "symbol": str(symbol).upper().replace(".NS", "").replace(".BO", ""),
        "score": score,
        "status": status,
        "market_cap_cr": round(mcap_cr, 1) if np.isfinite(mcap_cr) else None,
        "points": points,
    }


def strategy4_sepa_watchlist(x):
    """Monthly 10 EMA crosses above monthly 20 EMA (or monthly close reclaims
    monthly 10 EMA) on a strong month, with RSI/volume/price floors. Puts a
    stock on the watchlist - this is NOT the entry trigger; entry timing is
    strategy4_sepa_signal() below. This is what live S4 now calls (see
    strategy_signal(x, s=4))."""
    if x.empty:
        return pd.Series(False, index=x.index)

    monthly_bull_cross = (x.mema10 > x.mema20) & (x.mema10.shift(1) <= x.mema20.shift(1))
    monthly_bull_cross_count = monthly_bull_cross.shift(1).rolling(20, min_periods=20).sum()
    monthly_reclaim = (x.mclose > x.mema10) & (x.mprevclose <= x.mema10)

    return (
        (x.mmom >= 20) &
        (x.mrsi14 >= 50) &
        (x.mema10 >= x.mema20) &
        (x.vol30 >= 50000) &
        (x.close >= 20) &
        ((monthly_bull_cross_count >= 1) | monthly_reclaim)
    )


def _demand_candle(x):
    """Closes in the top part of its range, decent body, above-average volume -
    the confirmation candle that ends a contraction/base."""
    rng = (x.high - x.low).replace(0, np.nan)
    close_loc = (x.close - x.low) / rng
    body = (x.close - x.open).abs() / rng
    return (close_loc >= 0.65) & (body >= 0.35) & (x.close > x.open) & (x.relvol >= 1.15)


def _tight_contraction(x, lookback=10):
    """Small-bodied, narrowing-range candles right before the demand candle -
    the daily-chart footprint of a VCP/VCC base ('tightness')."""
    daily_range = (x.high - x.low) / x.close.replace(0, np.nan)
    avg_range = daily_range.rolling(lookback, min_periods=max(3, lookback // 2)).mean()
    prior_range = daily_range.shift(lookback).rolling(lookback, min_periods=max(3, lookback // 2)).mean()
    contraction_ratio = avg_range / prior_range.replace(0, np.nan)
    vol_ratio = x.volume.rolling(lookback, min_periods=max(3, lookback // 2)).mean() / x.vol20.replace(0, np.nan)
    return contraction_ratio, vol_ratio


def strategy4_sepa_features(d):
    """Builds scenario-detection features on top of features(d)."""
    x = features(d)
    if x.empty:
        return x

    contraction_ratio, vol_ratio = _tight_contraction(x)
    x["sepa_contraction_ratio"] = contraction_ratio
    x["sepa_base_vol_ratio"] = vol_ratio
    x["sepa_demand_candle"] = _demand_candle(x)

    # Scenario A: monthly has pulled back close to its own 10 EMA.
    x["sepa_monthly_near_ema10"] = ((x.mclose - x.mema10).abs() / x.mema10.replace(0, np.nan)) <= 0.06

    # Scenario B: monthly stayed extended -> weekly should be basing at its own
    # 20 EMA (tight, no breakdown candles) rather than at the 10.
    x["sepa_weekly_near_ema20"] = ((x.wclose - x.wema20).abs() / x.wema20.replace(0, np.nan)) <= 0.05
    x["sepa_weekly_holding"] = x.wclose >= x.wema20 * 0.95

    # Daily basing zone: Scenario A bases near daily 200 EMA, Scenario B near daily 50 EMA.
    x["sepa_near_daily_200"] = ((x.close - x.ema200).abs() / x.ema200.replace(0, np.nan)) <= 0.06
    x["sepa_near_daily_50"] = ((x.close - x.ema50).abs() / x.ema50.replace(0, np.nan)) <= 0.06

    # Long-term trend template (Minervini stack), required in both scenarios.
    x["sepa_trend_template"] = (
        (x.ema50 > x.ema200) &
        (x.ema200 > x.ema200.shift(80)) &  # ~4 months of daily bars = "200 sloping up"
        (x.close >= x.ema200 * 0.85)       # allow buying near/below 200
    )
    return x


def strategy4_sepa_signal(d):
    """Final S4 entry trigger: watchlist gate AND a valid VCC/demand-candle
    confirmation in the correct basing zone for whichever scenario applies.
    This is the precision entry-timing layer; strategy_signal(x, s=4) only
    evaluates the coarser strategy4_sepa_watchlist() gate."""
    x = strategy4_sepa_features(d)
    if x.empty:
        return pd.Series(False, index=getattr(d, "index", []))

    watchlisted = strategy4_sepa_watchlist(x)

    scenario_a = (
        x.sepa_monthly_near_ema10 &
        x.sepa_near_daily_200 &
        (x.sepa_contraction_ratio <= 0.75) &
        (x.sepa_base_vol_ratio <= 0.90) &
        x.sepa_demand_candle
    )
    scenario_b = (
        ~x.sepa_monthly_near_ema10 &
        x.sepa_weekly_near_ema20 &
        x.sepa_weekly_holding &
        x.sepa_near_daily_50 &
        (x.sepa_contraction_ratio <= 0.75) &
        (x.sepa_base_vol_ratio <= 0.90) &
        x.sepa_demand_candle
    )

    return watchlisted & x.sepa_trend_template & (scenario_a | scenario_b)


def _s4_sepa_quality(d):
    x = strategy4_sepa_features(d)
    if x.empty:
        return 0, {}
    z = x.iloc[-1]
    scenario = "A (monthly->10EMA / daily->200EMA)" if bool(z.sepa_monthly_near_ema10) else "B (weekly->20EMA / daily->50EMA)"

    pts = 0
    pts += 20 if pd.notna(z.mmom) and z.mmom >= 40 else 15 if pd.notna(z.mmom) and z.mmom >= 25 else 10 if pd.notna(z.mmom) and z.mmom >= 20 else 0
    pts += 15 if pd.notna(z.mrsi14) and z.mrsi14 >= 65 else 10 if pd.notna(z.mrsi14) and z.mrsi14 >= 55 else 5
    pts += 15 if bool(z.sepa_trend_template) else 0
    pts += 15 if pd.notna(z.sepa_contraction_ratio) and z.sepa_contraction_ratio <= 0.55 else 10 if pd.notna(z.sepa_contraction_ratio) and z.sepa_contraction_ratio <= 0.75 else 0
    pts += 10 if pd.notna(z.sepa_base_vol_ratio) and z.sepa_base_vol_ratio <= 0.65 else 6 if pd.notna(z.sepa_base_vol_ratio) and z.sepa_base_vol_ratio <= 0.90 else 0
    pts += 15 if bool(z.sepa_demand_candle) else 0
    pts += 10 if bool(z.sepa_near_daily_200) or bool(z.sepa_near_daily_50) else 0

    return int(min(100, pts)), {
        "Scenario": scenario,
        "Monthly Move %": round(float(z.mmom), 1) if pd.notna(z.mmom) else np.nan,
        "Monthly RSI": round(float(z.mrsi14), 1) if pd.notna(z.mrsi14) else np.nan,
        "Trend Template OK": bool(z.sepa_trend_template),
        "Contraction Ratio": round(float(z.sepa_contraction_ratio), 2) if pd.notna(z.sepa_contraction_ratio) else np.nan,
        "Base Vol Ratio": round(float(z.sepa_base_vol_ratio), 2) if pd.notna(z.sepa_base_vol_ratio) else np.nan,
        "Demand Candle": bool(z.sepa_demand_candle),
    }


def stock_dna(d, lookback_months=36):
    """The size of the stock's historical monthly up-legs, so position size
    scales with what the stock is actually capable of (a 20%-mover shouldn't
    be sized the same as a 300%-mover)."""
    x = _monthly_asof(d)
    if x is None or len(x) < 6:
        return {"legs_n": 0, "median_leg_pct": np.nan, "max_leg_pct": np.nan, "size_multiplier": 0.5}
    mom = x.close.pct_change().tail(lookback_months) * 100
    up_legs = mom[mom > 5]
    median_leg = float(up_legs.median()) if len(up_legs) else np.nan
    max_leg = float(up_legs.max()) if len(up_legs) else np.nan

    if not np.isfinite(median_leg):
        mult = 0.5
    elif median_leg >= 60:
        mult = 1.0
    elif median_leg >= 30:
        mult = 0.75
    elif median_leg >= 15:
        mult = 0.5
    else:
        mult = 0.25

    return {
        "legs_n": int(len(up_legs)),
        "median_leg_pct": round(median_leg, 1) if np.isfinite(median_leg) else None,
        "max_leg_pct": round(max_leg, 1) if np.isfinite(max_leg) else None,
        "size_multiplier": mult,
    }


def sepa_trailing_stop(d, setup_timeframe="monthly"):
    """One timeframe below the setup timeframe: monthly setup -> trail on daily
    50 EMA; weekly setup -> trail on daily 20 EMA. Returns current stop level
    and whether today's close has broken it."""
    x = features(d)
    if x.empty:
        return {"stop_level": None, "broken": False, "basis": setup_timeframe}
    z = x.iloc[-1]
    stop_level = float(z.ema50) if setup_timeframe == "monthly" else float(z.ema20)
    stop_level = stop_level if np.isfinite(stop_level) else np.nan
    broken = bool(np.isfinite(stop_level) and z.close < stop_level)
    return {"stop_level": round(stop_level, 2) if np.isfinite(stop_level) else None,
            "broken": broken, "basis": f"daily EMA below {setup_timeframe} setup"}


def sepa_breakeven_shift(entry_price, current_price, higher_low_price=None, trigger_pct=15.0):
    """Once open profit crosses trigger_pct, move stop to breakeven or the
    most recent higher low, whichever is higher."""
    if entry_price is None or current_price is None or entry_price <= 0:
        return None
    gain_pct = (current_price / entry_price - 1) * 100
    if gain_pct < trigger_pct:
        return None
    candidates = [entry_price]
    if higher_low_price is not None:
        candidates.append(higher_low_price)
    return max(candidates)


def scan_s4_sepa(data, fundamentals=None, min_score=60, max_stocks=None,
                  apply_fundamental_screen=False):
    """Full S4 pipeline: run clean_liquid_universe() first, then scan the
    result for SEPA entries. `data` should be {ticker: OHLCV df} already loaded
    for nse_liquid_universe()."""
    clean_data, safety_audit = clean_liquid_universe(data, fundamentals=fundamentals)

    rows = []
    items = list(clean_data.items())
    if max_stocks:
        items = items[:int(max_stocks)]
    for ticker, d in items:
        if d is None or len(d) < 260:
            continue
        try:
            sig = strategy4_sepa_signal(d).iloc[-1]
        except Exception:
            continue
        if not bool(sig):
            continue
        score, parts = _s4_sepa_quality(d)
        if score < min_score:
            continue
        dna = stock_dna(d)
        row = {
            "Ticker": str(ticker).replace(".NS", ""),
            "Score": score,
            "Entry": round(float(d.close.iloc[-1]), 2),
            "Size Multiplier": dna["size_multiplier"],
            "Median Leg %": dna["median_leg_pct"],
            **parts,
        }
        if apply_fundamental_screen:
            fs = sepa_fundamental_screen(ticker, d)
            row["Fundamental Score"] = fs["score"]
            row["Fundamental Status"] = fs["status"]
            row["Market Cap (Cr)"] = fs["market_cap_cr"]
        rows.append(row)

    results = pd.DataFrame(rows)
    if not results.empty:
        results = results.sort_values(["Score", "Median Leg %"], ascending=[False, False])
    return results, safety_audit


def strategy_signal(x,s):
    if x.empty:
        return pd.Series(False,index=x.index)

    daily_ret=_pct_change(x.close)

    if s==1:
        monthly_open_in_prev = (x.mopen <= x.mprevhigh) & (x.mopen >= x.mprevlow)
        monthly_close_in_prev = (x.mclose >= x.mprevlow) & (x.mclose <= x.mprevhigh)
        near_ema10 = ((x.mclose-x.mema10)/x.mema10 <= .30)
        return (
            (x.wrsi14 >= 50) &
            (x.mrsi14 >= 50) &
            (x.mclose >= x.mema15) &
            (x.close >= 15) &
            (x.vol20 >= 15000) &
            monthly_open_in_prev &
            monthly_close_in_prev &
            near_ema10 &
            (x.mmax20 >= 20)
        )

    if s==2:
        # ================================================================
        # STRATEGY 2 — direct translation of the user's scanner formula
        # ================================================================
        #
        # "count(20, 1 where ...)" is implemented as:
        # previous 20 completed daily bars, excluding today's bar.
        #
        # Cross definitions:
        #   EMA20 < EMA50 today AND EMA20 >= EMA50 yesterday
        #   EMA10 < EMA20 today AND EMA10 >= EMA20 yesterday
        #   EMA20 > EMA50 today AND EMA20 <= EMA50 yesterday
        #   EMA50 > EMA200 today AND EMA50 <= EMA200 yesterday

        ema20_below_50_cross = (
            (x.ema20 < x.ema50) &
            (x.ema20.shift(1) >= x.ema50.shift(1))
        )
        ema10_below_20_cross = (
            (x.ema10 < x.ema20) &
            (x.ema10.shift(1) >= x.ema20.shift(1))
        )

        ema20_above_50_cross = (
            (x.ema20 > x.ema50) &
            (x.ema20.shift(1) <= x.ema50.shift(1))
        )
        ema50_above_200_cross = (
            (x.ema50 > x.ema200) &
            (x.ema50.shift(1) <= x.ema200.shift(1))
        )

        # count(20,1 where condition): 20 bars immediately before today.
        bearish_20_50_count = (
            ema20_below_50_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )
        bearish_10_20_count = (
            ema10_below_20_cross.shift(1)
            .rolling(10, min_periods=10)
            .sum()
        )

        bullish_20_50_count = (
            ema20_above_50_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )
        bullish_50_200_count = (
            ema50_above_200_cross.shift(1)
            .rolling(20, min_periods=20)
            .sum()
        )

        # Current candle lies within the previous day's high-low range.
        inside_previous_day = (
            (x.open <= x.high.shift(1)) &
            (x.open >= x.low.shift(1)) &
            (x.close >= x.low.shift(1)) &
            (x.close <= x.high.shift(1))
        )

        # Returns of exactly 1 day ago and 2 days ago.
        ret_1d_ago = daily_ret.shift(1)
        ret_2d_ago = daily_ret.shift(2)

        return (
            # daily max(30, % change) >= 5
            (daily_ret.rolling(30, min_periods=30).max() >= 5) &

            # daily count(20,1 where EMA20 < EMA50 cross) < 1
            (bearish_20_50_count < 1) &

            # daily count(10,1 where EMA10 < EMA20 cross) < 1
            (bearish_10_20_count < 1) &

            # EMA50 >= EMA250
            (x.ema50 >= x.ema250) &

            # 20-day average volume >= 10000
            (x.vol20 >= 10000) &

            # Daily close >= 15
            (x.close >= 15) &

            # Monthly RSI(14) >= 55
            (x.mrsi14 >= 55) &

            # Weekly RSI(14) >= 50
            (x.wrsi14 >= 50) &

            # Current candle inside previous day's range
            inside_previous_day &

            # 1 day ago return <= 5 and >= -4
            (ret_1d_ago <= 5) &
            (ret_1d_ago >= -4) &

            # 2 days ago return <= 5 and >= -4
            (ret_2d_ago <= 5) &
            (ret_2d_ago >= -4) &

            # (daily close - daily EMA10) / daily EMA10 <= 0.04
            # NOTE: this is NOT abs(); a close below EMA10 satisfies it.
            (((x.close - x.ema10) / x.ema10) <= 0.04) &

            # Exactly one recent bullish crossover of either pair.
            (
                (bullish_20_50_count == 1) |
                (bullish_50_200_count == 1)
            )
        )

    if s==3:
        vwap=(x.close*x.volume).rolling(20).sum()/x.volume.rolling(20).sum()
        # The original screener expression used EMA(daily VWAP,20) * SMA(volume,20).
        vwap_ema=ema(vwap,20)
        liquidity=vwap_ema*x.vol20 >= 150_000_000
        near50=(x.close <= x.ema50*1.04)&(x.close >= x.ema50*.96)
        return (
            liquidity &
            (x.close >= x.ema200) &
            (x.wrsi14 >= 40) &
            near50
        )

    if s==4:
        # ================================================================
        # STRATEGY 4 — SEPA (Specific Entry Point Analysis) watchlist gate
        # ================================================================
        # LIVE S4 no longer runs the old literal-translation formula below
        # (monthly return>=20%, monthly RSI>=50, EMA10/20 cross or reclaim,
        # daily close<=1.03xEMA20). It now runs the Minervini SEPA watchlist
        # rule instead - see strategy4_sepa_watchlist() above. The old formula
        # is preserved verbatim in s4_base_conditions() purely so
        # s4_ema20_extension_calibration() (a separate research tool) keeps
        # working; it is deliberately NOT called from here anymore.
        return strategy4_sepa_watchlist(x)

    return pd.Series(False,index=x.index)

# ========================= EARLY WARNING RADAR =========================
# The scanner is binary: a stock either passes ALL rules of a strategy or it is
# invisible. That is correct for signal generation, but it means the first time
# you ever hear about a stock is the day it already triggered - which is exactly
# the "late entry" problem. This module answers the other question: which stocks
# are ABOUT to trigger, and which are coiled tightly enough that the move is
# likely to be sharp when they do.
#
# It changes nothing about S1-S4 qualification. It is a watchlist builder.

def strategy_condition_matrix(x, s):
    """Every individual condition of a strategy as its own boolean Series.

    ANDing these reproduces strategy_signal(x, s) exactly; keeping them separate
    is what lets the radar say "7 of 8 rules pass, the missing one is monthly
    RSI >= 50 and it is at 48.2".
    """
    if x.empty:
        return {}
    daily_ret = _pct_change(x.close)

    if s == 1:
        return {
            "Weekly RSI >= 50": x.wrsi14 >= 50,
            "Monthly RSI >= 50": x.mrsi14 >= 50,
            "Monthly close >= EMA15": x.mclose >= x.mema15,
            "Close >= 15": x.close >= 15,
            "Vol20 >= 15000": x.vol20 >= 15000,
            "Monthly open inside prev range": (x.mopen <= x.mprevhigh) & (x.mopen >= x.mprevlow),
            "Monthly close inside prev range": (x.mclose >= x.mprevlow) & (x.mclose <= x.mprevhigh),
            "Within 30% of monthly EMA10": ((x.mclose - x.mema10) / x.mema10) <= .30,
            "Monthly 20m max momentum >= 20": x.mmax20 >= 20,
        }

    if s == 2:
        ema20_below_50_cross = (x.ema20 < x.ema50) & (x.ema20.shift(1) >= x.ema50.shift(1))
        ema10_below_20_cross = (x.ema10 < x.ema20) & (x.ema10.shift(1) >= x.ema20.shift(1))
        ema20_above_50_cross = (x.ema20 > x.ema50) & (x.ema20.shift(1) <= x.ema50.shift(1))
        ema50_above_200_cross = (x.ema50 > x.ema200) & (x.ema50.shift(1) <= x.ema200.shift(1))
        bearish_20_50 = ema20_below_50_cross.shift(1).rolling(20, min_periods=20).sum()
        bearish_10_20 = ema10_below_20_cross.shift(1).rolling(10, min_periods=10).sum()
        bullish_20_50 = ema20_above_50_cross.shift(1).rolling(20, min_periods=20).sum()
        bullish_50_200 = ema50_above_200_cross.shift(1).rolling(20, min_periods=20).sum()
        ret_1d, ret_2d = daily_ret.shift(1), daily_ret.shift(2)
        return {
            "30d max daily move >= 5%": daily_ret.rolling(30, min_periods=30).max() >= 5,
            "No recent EMA20<50 cross": bearish_20_50 < 1,
            "No recent EMA10<20 cross": bearish_10_20 < 1,
            "EMA50 >= EMA250": x.ema50 >= x.ema250,
            "Vol20 >= 10000": x.vol20 >= 10000,
            "Close >= 15": x.close >= 15,
            "Monthly RSI >= 55": x.mrsi14 >= 55,
            "Weekly RSI >= 50": x.wrsi14 >= 50,
            "Inside previous day's range": (
                (x.open <= x.high.shift(1)) & (x.open >= x.low.shift(1)) &
                (x.close >= x.low.shift(1)) & (x.close <= x.high.shift(1))
            ),
            "1d-ago return within -4..5%": (ret_1d <= 5) & (ret_1d >= -4),
            "2d-ago return within -4..5%": (ret_2d <= 5) & (ret_2d >= -4),
            "Close within 4% above EMA10": ((x.close - x.ema10) / x.ema10) <= 0.04,
            "Exactly one bullish EMA cross": (bullish_20_50 == 1) | (bullish_50_200 == 1),
        }

    if s == 3:
        vwap = (x.close * x.volume).rolling(20).sum() / x.volume.rolling(20).sum()
        vwap_ema = ema(vwap, 20)
        return {
            "Liquidity >= 15 crore": vwap_ema * x.vol20 >= 150_000_000,
            "Close >= EMA200": x.close >= x.ema200,
            "Weekly RSI >= 40": x.wrsi14 >= 40,
            "Close within 4% of EMA50": (x.close <= x.ema50 * 1.04) & (x.close >= x.ema50 * .96),
        }

    if s == 4:
        # Mirrors strategy4_sepa_watchlist() exactly (live S4's coarser
        # watchlist gate) - the old fixed "Close <= 1.03 x EMA20" proximity
        # rule is gone from live S4, so it is not listed here either. The
        # tighter VCP/VCC entry-timing rules live in strategy4_sepa_signal(),
        # which is a separate precision layer the radar does not track.
        monthly_bull_cross = (x.mema10 > x.mema20) & (x.mema10.shift(1) <= x.mema20.shift(1))
        monthly_bull_cross_count = monthly_bull_cross.shift(1).rolling(20, min_periods=20).sum()
        monthly_reclaim = (x.mclose > x.mema10) & (x.mprevclose <= x.mema10)
        return {
            "Monthly return >= 20%": x.mmom >= 20,
            "Monthly RSI >= 50": x.mrsi14 >= 50,
            "Monthly EMA10 >= EMA20": x.mema10 >= x.mema20,
            "Vol30 >= 50000": x.vol30 >= 50000,
            "Close >= 20": x.close >= 20,
            "Recent monthly cross or reclaim": (monthly_bull_cross_count >= 1) | monthly_reclaim,
        }

    return {}


# How far a numeric gate may be from its threshold and still count as "nearly
# passing". Expressed as a fraction of the threshold, so it scales with the
# metric rather than assuming everything is a percentage.
NEAR_MISS_TOLERANCE = 0.06


def _near_miss_distance(name, x, i):
    """Signed distance to the threshold for the gates worth measuring, as a
    fraction (0.04 = the value must improve 4% to pass).

    Only gates whose "distance" is a meaningful, continuously-closing quantity
    are measured. A structural condition ("inside previous day's range") either
    holds or does not, and pretending it is 3% away would be noise, so it
    returns NaN and is reported as a structural miss instead.
    """
    def val(attr):
        try:
            v = float(x[attr].iloc[i])
            return v if np.isfinite(v) else np.nan
        except Exception:
            return np.nan

    def gap_up(value, threshold):
        # value must RISE to threshold
        if not np.isfinite(value) or not np.isfinite(threshold) or threshold == 0:
            return np.nan
        return max(0.0, (threshold - value) / abs(threshold))

    def gap_down(value, threshold):
        # value must FALL to threshold
        if not np.isfinite(value) or not np.isfinite(threshold) or threshold == 0:
            return np.nan
        return max(0.0, (value - threshold) / abs(threshold))

    table_up = {
        "Weekly RSI >= 50": ("wrsi14", 50), "Monthly RSI >= 50": ("mrsi14", 50),
        "Monthly RSI >= 55": ("mrsi14", 55), "Weekly RSI >= 40": ("wrsi14", 40),
        "Close >= 15": ("close", 15), "Close >= 20": ("close", 20),
        "Vol20 >= 15000": ("vol20", 15000), "Vol20 >= 10000": ("vol20", 10000),
        "Vol30 >= 50000": ("vol30", 50000),
        "Monthly return >= 20%": ("mmom", 20),
        "Monthly 20m max momentum >= 20": ("mmax20", 20),
    }
    if name in table_up:
        attr, thr = table_up[name]
        return gap_up(val(attr), thr)

    if name == "Monthly close >= EMA15":
        return gap_up(val("mclose"), val("mema15"))
    if name == "Monthly EMA10 >= EMA20":
        return gap_up(val("mema10"), val("mema20"))
    if name == "EMA50 >= EMA250":
        return gap_up(val("ema50"), val("ema250"))
    if name == "Close >= EMA200":
        return gap_up(val("close"), val("ema200"))
    if name == "Close <= 1.03 x EMA20":
        return gap_down(val("close"), 1.03 * val("ema20"))
    if name == "Close within 4% above EMA10":
        return gap_down(val("close"), 1.04 * val("ema10"))
    if name == "Within 30% of monthly EMA10":
        return gap_down(val("mclose"), 1.30 * val("mema10"))
    if name == "Close within 4% of EMA50":
        c, e = val("close"), val("ema50")
        if not np.isfinite(c) or not np.isfinite(e) or e == 0:
            return np.nan
        return gap_down(c, e * 1.04) if c > e else gap_up(c, e * .96)
    if name == "30d max daily move >= 5%":
        try:
            m = float(_pct_change(x.close).rolling(30, min_periods=30).max().iloc[i])
        except Exception:
            return np.nan
        return gap_up(m, 5)
    return np.nan


def compression_features(df, i=-1):
    """Volatility-contraction and accumulation readings for one bar.

    Large moves are preceded by compression far more often than by expansion, so
    these are the "before the move" part of the radar, independent of any
    strategy rule.
    """
    out = {"Squeeze %ile": np.nan, "NR7": False, "Inside Bars": 0,
           "Range Ratio": np.nan, "Vol Dry-Up": np.nan,
           "From 52w High %": np.nan, "Above 52w Low %": np.nan}
    if df is None or len(df) < 70:
        return out
    d = df.iloc[:len(df) + i + 1] if i < -1 else df
    d = d.tail(300)
    if len(d) < 70:
        return out
    high, low, close, vol = d.high, d.low, d.close, d.volume

    rng = (high - low) / close.replace(0, np.nan)
    r = rng.iloc[-1]
    hist = rng.tail(120).dropna()
    if np.isfinite(r) and len(hist) >= 30:
        # Where today's range sits in its own 120-day distribution. Low = coiled.
        out["Squeeze %ile"] = round(float((hist < r).mean() * 100), 1)
    last7 = (high - low).tail(7)
    out["NR7"] = bool(len(last7) == 7 and np.isfinite(last7.iloc[-1]) and last7.iloc[-1] == last7.min())

    # Consecutive bars fully inside the prior bar's range.
    inside = 0
    for k in range(len(d) - 1, 0, -1):
        if high.iloc[k] <= high.iloc[k - 1] and low.iloc[k] >= low.iloc[k - 1]:
            inside += 1
        else:
            break
    out["Inside Bars"] = int(inside)

    r5 = (high - low).tail(5).mean()
    r60 = (high - low).tail(60).mean()
    if np.isfinite(r5) and np.isfinite(r60) and r60 > 0:
        out["Range Ratio"] = round(float(r5 / r60), 3)

    v5 = vol.tail(5).mean()
    v50 = vol.tail(50).mean()
    if np.isfinite(v5) and np.isfinite(v50) and v50 > 0:
        # Below 1.0 = volume drying up into the base, the classic pre-breakout tell.
        out["Vol Dry-Up"] = round(float(v5 / v50), 3)

    win = close.tail(250)
    hi52, lo52, c = float(win.max()), float(win.min()), float(close.iloc[-1])
    if np.isfinite(hi52) and hi52 > 0:
        out["From 52w High %"] = round((c / hi52 - 1) * 100, 2)
    if np.isfinite(lo52) and lo52 > 0:
        out["Above 52w Low %"] = round((c / lo52 - 1) * 100, 2)
    return out


def _compression_score(comp):
    """0-100. Higher = tighter coil on lighter volume near the highs, i.e. the
    structure that most often precedes an expansion move."""
    score = 0.0
    pct = comp.get("Squeeze %ile")
    if np.isfinite(pct if pct is not None else np.nan):
        score += (100 - pct) * 0.35          # tighter range than usual
    rr = comp.get("Range Ratio")
    if rr is not None and np.isfinite(rr):
        score += float(np.clip((1.4 - rr) / 0.9, 0, 1)) * 20
    vd = comp.get("Vol Dry-Up")
    if vd is not None and np.isfinite(vd):
        score += float(np.clip((1.2 - vd) / 0.7, 0, 1)) * 20
    if comp.get("NR7"):
        score += 8
    score += min(int(comp.get("Inside Bars") or 0), 3) * 3
    fh = comp.get("From 52w High %")
    if fh is not None and np.isfinite(fh):
        # Coiling right under the highs beats coiling 40% below them.
        score += float(np.clip((25 + fh) / 25, 0, 1)) * 12
    return float(np.clip(score, 0, 100))


def early_warning_radar(data, strategies, regime, max_missing=2, min_readiness=0,
                        progress_cb=None, stats=None):
    """Stocks that are CLOSE to triggering a strategy, ranked by readiness.

    For every stock/strategy pair it counts how many of that strategy's rules
    currently pass, names the ones that do not, measures how far the numeric
    ones are from their thresholds, and combines that with the compression
    reading into a single Readiness score.

    `max_missing` = how many failing rules a stock may still have and appear.
    max_missing=0 reproduces the normal scanner's qualified list.

    Pass a dict as `stats` to receive skip counts. Without it a systematic
    feature-engine failure would produce a silently empty radar.
    """
    rows = []
    counts = stats if isinstance(stats, dict) else {}
    counts.setdefault("scanned", 0)
    counts.setdefault("too_short", 0)
    counts.setdefault("feature_error", 0)
    counts.setdefault("last_error", "")
    total = max(1, len(data))
    for n, (ticker, df) in enumerate(data.items()):
        if progress_cb and n % 25 == 0:
            try:
                progress_cb(n / total)
            except Exception:
                pass
        if df is None or len(df) < 260:
            counts["too_short"] += 1
            continue
        try:
            f = features_fast(str(ticker), df)
        except Exception as exc:
            counts["feature_error"] += 1
            counts["last_error"] = f"{ticker}: {exc}"
            continue
        if f is None or len(f) < 260:
            counts["too_short"] += 1
            continue
        counts["scanned"] += 1
        f = f.replace([np.inf, -np.inf], np.nan)
        comp = compression_features(df)
        comp_score = _compression_score(comp)

        for s in strategies:
            conds = strategy_condition_matrix(f, int(s))
            if not conds:
                continue
            passed, failed = [], []
            for name, series in conds.items():
                try:
                    ok = bool(series.iloc[-1])
                except Exception:
                    ok = False
                (passed if ok else failed).append(name)

            n_total = len(conds)
            n_missing = len(failed)
            if n_missing > max_missing:
                continue

            gaps = {name: _near_miss_distance(name, f, -1) for name in failed}
            measurable = [g for g in gaps.values() if np.isfinite(g)]
            worst_gap = max(measurable) if measurable else np.nan
            structural = [name for name, g in gaps.items() if not np.isfinite(g)]

            # Proximity: full marks when nothing is missing, decaying with both
            # the number of failing rules and how far the worst one is.
            if n_missing == 0:
                proximity = 100.0
            else:
                gap_term = 0.0 if not np.isfinite(worst_gap) else \
                    float(np.clip(1 - worst_gap / NEAR_MISS_TOLERANCE, 0, 1))
                # A structural miss cannot be measured, so it is scored as a
                # half-gap rather than silently treated as almost-passing.
                if structural:
                    gap_term = min(gap_term, 0.5) if np.isfinite(worst_gap) else 0.4
                proximity = float(np.clip((1 - n_missing / (max_missing + 1)) * 60 + gap_term * 40, 0, 100))

            z = f.iloc[-1]
            close = float(z.close) if np.isfinite(z.close) else np.nan
            ema20 = float(z.ema20) if np.isfinite(z.ema20) else np.nan
            atr = float(z.atr14) if np.isfinite(z.atr14) else np.nan

            regime_bonus = {"BULL": 8, "NEUTRAL": 0, "BEAR": -10}.get(str(regime).upper(), 0)
            readiness = float(np.clip(
                proximity * 0.55 + comp_score * 0.35 + regime_bonus + 5, 0, 100
            ))
            if readiness < min_readiness:
                continue

            rows.append({
                "Readiness": round(readiness, 1),
                "Ticker": str(ticker).replace(".NS", ""),
                "Strategy": f"S{int(s)}",
                "State": "🔥 TRIGGERED" if n_missing == 0 else (
                    "⚡ 1 RULE AWAY" if n_missing == 1 else "👀 2 RULES AWAY"),
                "Rules Passing": f"{n_total - n_missing}/{n_total}",
                "Missing Rules": ", ".join(failed) if failed else "—",
                "Worst Gap %": round(worst_gap * 100, 2) if np.isfinite(worst_gap) else np.nan,
                "Proximity": round(proximity, 1),
                "Compression": round(comp_score, 1),
                "Squeeze %ile": comp["Squeeze %ile"],
                "Range Ratio": comp["Range Ratio"],
                "Vol Dry-Up": comp["Vol Dry-Up"],
                "NR7": comp["NR7"],
                "Inside Bars": comp["Inside Bars"],
                "From 52w High %": comp["From 52w High %"],
                "Close": round(close, 2) if np.isfinite(close) else np.nan,
                "Dist to EMA20 %": round((close / ema20 - 1) * 100, 2)
                                   if np.isfinite(close) and np.isfinite(ema20) and ema20 else np.nan,
                "ATR %": round(atr / close * 100, 2)
                         if np.isfinite(atr) and np.isfinite(close) and close else np.nan,
                "RSI": round(float(z.rsi14), 1) if np.isfinite(z.rsi14) else np.nan,
                "RelVol": round(float(z.relvol), 2) if np.isfinite(z.relvol) else np.nan,
                "Regime": regime,
            })

    if progress_cb:
        try:
            progress_cb(1.0)
        except Exception:
            pass
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Readiness", "Compression"], ascending=[False, False]).reset_index(drop=True)


def radar_missing_rule_summary(radar_df):
    """Which single rule is blocking the most near-miss candidates.

    Useful as evidence: if 300 stocks are held back only by "Monthly RSI >= 55",
    that rule is the binding constraint of the whole universe right now, not a
    per-stock accident.
    """
    if radar_df is None or radar_df.empty:
        return pd.DataFrame(columns=["Strategy", "Missing Rule", "Stocks"])
    if "Missing Rules" not in radar_df.columns or "Strategy" not in radar_df.columns:
        return pd.DataFrame(columns=["Strategy", "Missing Rule", "Stocks"])
    rows = []
    for strategy, miss in zip(radar_df["Strategy"], radar_df["Missing Rules"]):
        if not isinstance(miss, str) or not miss or miss == "—":
            continue
        for name in [m.strip() for m in miss.split(",") if m.strip()]:
            rows.append({"Strategy": strategy, "Missing Rule": name})
    if not rows:
        return pd.DataFrame(columns=["Strategy", "Missing Rule", "Stocks"])
    g = (pd.DataFrame(rows).groupby(["Strategy", "Missing Rule"]).size()
         .reset_index(name="Stocks").sort_values("Stocks", ascending=False))
    return g.reset_index(drop=True)


# ========================= MARKET REGIME =========================

def regime_from_index(d):
    x=features(d).dropna()
    if len(x)<30: return "UNKNOWN",0
    z=x.iloc[-1]
    score=0
    score += 25 if z.close>z.ema200 else 0
    score += 20 if z.ema50>z.ema200 else 0
    score += 15 if z.ema200>x.ema200.iloc[-20] else 0
    score += 15 if z.rsi14>=55 else 0
    score += 10 if z.close>z.ema20 else 0
    score += 15 if z.relvol>=1 else 0
    if score>=75: return "STRONG BULL",score
    if score>=60: return "BULL",score
    if score>=45: return "RECOVERY / SIDEWAYS",score
    if score>=30: return "EARLY BEAR",score
    return "BEAR",score

# ========================= SMALL/MICRO SAFETY =========================

def safety(info,d):
    score=100; flags=[]
    avg_value=float((d.close*d.volume).tail(20).mean()) if d is not None and not d.empty else 0
    debt=info.get("debtToEquity")
    insider=info.get("heldPercentInsiders")
    if avg_value<2_000_000: score-=30; flags.append("Low traded value")
    if avg_value<500_000: score-=20; flags.append("Very low liquidity")
    if d is not None and len(d)>=30:
        r=d.close.pct_change().tail(30)
        if (r.abs()>.15).sum()>=3: score-=15; flags.append("Abnormal volatility")
    if isinstance(debt,(int,float)) and np.isfinite(debt) and debt>200:
        score-=15; flags.append("High debt/equity")
    if isinstance(insider,(int,float)) and np.isfinite(insider) and insider<.25:
        score-=5; flags.append("Low insider holding")
    score=max(0,min(100,score))
    status="ELIGIBLE" if score>=70 else ("CAUTION" if score>=50 else "REJECT")
    return score,status,flags

def _regime_from_row(f,i):
    """O(1) equivalent of regime_from_index(hist) — reads the already-computed
    features_fast() frame at row i instead of recomputing features() from scratch
    on a growing history slice for every signal (that recompute is O(len^2) per
    call because of the weekly/monthly as-of loops, and was being called once per
    signal per ticker per strategy inside the backtest — an O(n^3)-class hot path)."""
    if i<30 or i-20<0:
        return "UNKNOWN",0
    z=f.iloc[i]
    ema200_lag20=f.ema200.iloc[i-20]
    req=(z.close,z.ema200,z.ema50,z.rsi14,z.ema20,z.relvol,ema200_lag20)
    if any(pd.isna(v) for v in req):
        return "UNKNOWN",0
    score=0
    score += 25 if z.close>z.ema200 else 0
    score += 20 if z.ema50>z.ema200 else 0
    score += 15 if z.ema200>ema200_lag20 else 0
    score += 15 if z.rsi14>=55 else 0
    score += 10 if z.close>z.ema20 else 0
    score += 15 if z.relvol>=1 else 0
    if score>=75: return "STRONG BULL",score
    if score>=60: return "BULL",score
    if score>=45: return "RECOVERY / SIDEWAYS",score
    if score>=30: return "EARLY BEAR",score
    return "BEAR",score

def _safety_fast_series(df):
    """Vectorized once-per-ticker precompute of the rolling stats safety() reads,
    so the backtest hot loop can look them up in O(1) per signal instead of
    re-slicing/re-computing tail(20)/tail(30) windows from scratch per signal."""
    avg_value=(df.close*df.volume).rolling(20,min_periods=1).mean()
    abnormal=(df.close.pct_change().abs()>.15).rolling(30,min_periods=1).sum()
    return avg_value,abnormal

def _safety_from_row(avg_value,abnormal,i):
    """O(1) equivalent of safety({}, hist) for the backtest (info is always {}
    there, so the debt/insider branches never fire)."""
    score=100; flags=[]
    av=avg_value.iloc[i]
    if pd.notna(av):
        if av<2_000_000: score-=30; flags.append("Low traded value")
        if av<500_000: score-=20; flags.append("Very low liquidity")
    ab=abnormal.iloc[i]
    if pd.notna(ab) and ab>=3:
        score-=15; flags.append("Abnormal volatility")
    score=max(0,min(100,score))
    status="ELIGIBLE" if score>=70 else ("CAUTION" if score>=50 else "REJECT")
    return score,status,flags


# ========================= CUSTOM STRATEGY DSL =========================
# Whitelist-only rule language — never eval()/exec(). Each non-blank, non-
# comment line must be "<COLUMN> <op> <RHS>" where COLUMN is one of the
# known features_fast() columns and RHS is a number, another known column,
# or "NUMBER * COLUMN" (e.g. "VOLUME > 1.5 * VOL20"). Lines are AND-combined.

CUSTOM_DSL_COLUMNS = {
    "open","high","low","close","volume",
    "ema10","ema20","ema50","ema200","ema250","vol20","vol30","rsi14","relvol","atr14",
    "wrsi14","wema20","wema50","wclose",
    "mclose","mopen","mhigh","mlow","mrsi14","mema10","mema15","mema20","mmom","mmax20",
    "mprevclose","mprevhigh","mprevlow","m_cross_count20","m_cross_10_20",
}
CUSTOM_DSL_OPS = {
    ">": lambda a,b: a>b, ">=": lambda a,b: a>=b,
    "<": lambda a,b: a<b, "<=": lambda a,b: a<=b,
    "==": lambda a,b: a==b, "!=": lambda a,b: a!=b,
}
_CUSTOM_DSL_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(.+?)\s*$")
_CUSTOM_DSL_MUL_RE_NC = re.compile(r"^([0-9]*\.?[0-9]+)\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)$")
_CUSTOM_DSL_MUL_RE_CN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\*\s*([0-9]*\.?[0-9]+)$")

def parse_custom_strategy(text):
    """Parse the DSL into a validated condition list. Returns (conditions, errors);
    conditions is empty and errors non-empty when any line fails to validate —
    callers must refuse to run a strategy with any error, not silently drop lines."""
    conditions, errors = [], []
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _CUSTOM_DSL_LINE_RE.match(line)
        if not m:
            errors.append(f"Line {lineno}: could not parse '{raw}'. Expected '<COLUMN> <op> <value>', e.g. 'RSI14 > 55'.")
            continue
        left_raw, op, rhs = m.group(1), m.group(2), m.group(3).strip()
        left = left_raw.lower()
        if left not in CUSTOM_DSL_COLUMNS:
            errors.append(f"Line {lineno}: unknown column '{left_raw}'. Known columns: {', '.join(sorted(CUSTOM_DSL_COLUMNS))}.")
            continue
        try:
            conditions.append({"left":left,"op":op,"rhs_kind":"number","rhs_value":float(rhs),"text":line})
            continue
        except ValueError:
            pass
        mm = _CUSTOM_DSL_MUL_RE_NC.match(rhs)
        if mm:
            mult,col = float(mm.group(1)), mm.group(2).lower()
        else:
            mm = _CUSTOM_DSL_MUL_RE_CN.match(rhs)
            mult,col = (float(mm.group(2)), mm.group(1).lower()) if mm else (None,None)
        if mm:
            if col not in CUSTOM_DSL_COLUMNS:
                errors.append(f"Line {lineno}: unknown column '{col}' on the right-hand side of '{raw}'.")
                continue
            conditions.append({"left":left,"op":op,"rhs_kind":"multiplier","rhs_value":(mult,col),"text":line})
            continue
        if rhs.lower() in CUSTOM_DSL_COLUMNS:
            conditions.append({"left":left,"op":op,"rhs_kind":"column","rhs_value":rhs.lower(),"text":line})
            continue
        errors.append(f"Line {lineno}: right-hand side '{rhs}' is not a number, a known column, or 'NUMBER * COLUMN'.")
    return conditions, errors

def custom_strategy_signal(f, conditions):
    """Vectorized AND of all parsed conditions against a features_fast() frame."""
    if f.empty or not conditions:
        return pd.Series(False, index=f.index)
    sig = pd.Series(True, index=f.index)
    for c in conditions:
        left = f[c["left"]]
        if c["rhs_kind"] == "number":
            right = c["rhs_value"]
        elif c["rhs_kind"] == "column":
            right = f[c["rhs_value"]]
        else:
            mult, col = c["rhs_value"]
            right = f[col] * mult
        sig = sig & CUSTOM_DSL_OPS[c["op"]](left, right).fillna(False)
    return sig


# ========================= HTF DEMAND + FOOTPRINT =========================

def _zone_score(x, lookback, tolerance=0.035):
    """Approximate demand/support quality from historical swing lows.
    This is a research heuristic, not a claim of institutional order-flow data."""
    if len(x) < lookback + 10:
        return 0, {"fresh": False, "reaction": 0, "tests": 0}
    recent = x.tail(lookback).copy()
    low = float(recent.low.min())
    price = float(x.close.iloc[-1])
    distance = abs(price / low - 1)
    near = distance <= tolerance
    # Strong departure from the lowest area.
    reaction = (float(recent.close.max()) / low - 1) if low > 0 else 0
    tests = int(((recent.low <= low * (1 + tolerance)).sum()))
    fresh = tests <= 2
    points = 0
    if near: points += 5
    if reaction >= .20: points += 4
    elif reaction >= .10: points += 2
    if fresh: points += 2
    elif tests <= 4: points += 1
    return min(points, 11), {"fresh": fresh, "reaction": reaction, "tests": tests, "distance": distance}

def htf_confluence(x):
    """20-point higher-timeframe support/demand score."""
    # Quarterly approximation from rolling 63 trading days.
    q = _zone_score(x, 252, .06)[0]
    m = _zone_score(x, 126, .045)[0]
    w = _zone_score(x, 60, .035)[0]
    # Cap the combined score at 20.
    total = min(20, q * 0.75 + m * 0.75 + w * 0.5)
    return int(round(total))

def footprint_score(x):
    """20-point price/volume footprint heuristic using only information known at the scan date."""
    if len(x) < 60:
        return 0
    z = x.iloc[-1]
    score = 0

    # Base/compression: lower recent range than earlier range.
    recent_range = ((x.high - x.low) / x.close).tail(10).mean()
    prior_range = ((x.high - x.low) / x.close).tail(40).head(30).mean()
    if pd.notna(recent_range) and pd.notna(prior_range) and recent_range < prior_range * .8:
        score += 4

    # Volume contraction in the base.
    v_recent = x.volume.tail(10).mean()
    v_prior = x.volume.tail(40).head(30).mean()
    if pd.notna(v_recent) and pd.notna(v_prior) and v_recent < v_prior * .9:
        score += 3

    # Expansion on the current move.
    if pd.notna(z.relvol) and z.relvol >= 1.5:
        score += 4
    elif pd.notna(z.relvol) and z.relvol >= 1.2:
        score += 2

    # Close near the high of the day.
    day_range = float(z.high - z.low)
    if day_range > 0:
        close_location = (float(z.close) - float(z.low)) / day_range
        if close_location >= .75:
            score += 3
        elif close_location >= .60:
            score += 1

    # Controlled distance from EMA20, avoiding extreme extension.
    extension = float(z.close / z.ema20 - 1) if pd.notna(z.ema20) else np.nan
    if np.isfinite(extension) and 0 <= extension <= .04:
        score += 3

    # Relative-strength proxy versus own 50-day trend.
    if pd.notna(z.ema50) and z.close > z.ema50:
        score += 3

    return int(min(20, score))

def strategy_quality_score(x, s):
    """30-point strategy-specific quality score. Does not apply other strategies."""
    z = x.iloc[-1]
    p = 0
    if s == 1:
        p += 10 if z.wrsi14 >= 60 else 7 if z.wrsi14 >= 55 else 4 if z.wrsi14 >= 50 else 0
        p += 10 if z.mrsi14 >= 60 else 7 if z.mrsi14 >= 55 else 4 if z.mrsi14 >= 50 else 0
        p += 10 if z.mclose >= z.mema15 else 0
    elif s == 2:
        p += 10 if z.ema20 > z.ema50 else 0
        p += 10 if z.ema50 > z.ema200 else 0
        p += 10 if z.relvol >= 1.2 else 5 if z.relvol >= 1 else 0
    elif s == 3:
        dist = abs(z.close / z.ema50 - 1)
        p += 10 if dist <= .015 else 7 if dist <= .025 else 4 if dist <= .04 else 0
        p += 10 if z.close > z.ema200 else 0
        p += 10 if z.wrsi14 >= 55 else 6 if z.wrsi14 >= 45 else 0
    elif s == 4:
        p += 10 if z.mmom >= 30 else 7 if z.mmom >= 25 else 4 if z.mmom >= 20 else 0
        p += 10 if z.mema10 > z.mema20 else 0
        p += 10 if z.close <= z.ema20 * 1.02 else 5 if z.close <= z.ema20 * 1.03 else 0
    return int(min(30, p))

def final_setup_score(x, s, regime, safety_score):
    """100-point ranking score. Most components rank quality rather than hard-reject."""
    z = x.iloc[-1]
    strategy = strategy_quality_score(x, s)       # 30
    htf = htf_confluence(x)                       # 20
    footprint = footprint_score(x)                # 20

    trend = 0
    trend += 4 if z.close > z.ema50 else 0
    trend += 3 if z.close > z.ema200 else 0
    trend += 3 if z.rsi14 >= 50 else 0             # 10

    entry = 0
    ext = z.close / z.ema20 - 1 if pd.notna(z.ema20) else np.nan
    if np.isfinite(ext):
        entry = 10 if 0 <= ext <= .025 else 7 if ext <= .04 else 3 if ext <= .07 else 0

    rel = 5 if (pd.notna(z.ema50) and z.close > z.ema50) else 0

    market = 5 if regime == "STRONG BULL" else 4 if regime == "BULL" else 2 if regime == "RECOVERY / SIDEWAYS" else 0
    safety_points = 5 if safety_score >= 90 else 4 if safety_score >= 80 else 3 if safety_score >= 70 else 0

    total = strategy + htf + footprint + trend + entry + rel + market + safety_points
    return int(max(0, min(100, total))), {
        "Strategy": strategy,
        "HTF Demand": htf,
        "Footprint": footprint,
        "Trend": trend,
        "Entry Quality": entry,
        "Relative Strength": rel,
        "Market Regime": market,
        "Safety": safety_points
    }

# ========================= SCORE =========================

def setup_score(x, s, regime, safety_score):
    """Strategy-specific quality score. This does NOT add other strategy rules."""
    z = x.iloc[-1]
    score = 0

    # Market regime support: 15
    score += 15 if regime == "STRONG BULL" else 12 if regime == "BULL" else 7 if regime == "RECOVERY / SIDEWAYS" else 2

    # MTF alignment: 25
    score += 5 if z.close > z.ema50 else 0
    score += 5 if z.close > z.ema200 else 0
    score += 5 if z.wrsi14 >= 50 else 0
    score += 5 if z.mrsi14 >= 50 else 0
    score += 5 if z.mema10 >= z.mema20 else 0

    # Technical quality: 25
    score += 5 if z.rsi14 >= 50 else 0
    score += 5 if z.relvol >= 1.0 else 0
    score += 5 if z.relvol >= 1.5 else 0
    score += 5 if z.close >= z.ema20 else 0
    score += 5 if z.close >= z.ema50 else 0

    # Safety: 15
    score += 15 if safety_score >= 90 else 12 if safety_score >= 80 else 8 if safety_score >= 70 else 0

    # Strategy-specific signal quality: 20.
    # These are conditions belonging to the selected strategy only.
    if s == 1:
        score += 10 if z.wrsi14 >= 55 else 5 if z.wrsi14 >= 50 else 0
        score += 10 if z.mrsi14 >= 55 else 5 if z.mrsi14 >= 50 else 0
    elif s == 2:
        score += 10 if z.ema20 > z.ema50 else 0
        score += 10 if z.ema50 > z.ema200 else 0
    elif s == 3:
        dist = abs(z.close / z.ema50 - 1)
        score += 10 if dist <= .02 else 5 if dist <= .04 else 0
        score += 10 if z.close > z.ema200 else 0
    elif s == 4:
        score += 10 if z.mmom >= 25 else 5 if z.mmom >= 20 else 0
        score += 10 if z.mema10 > z.mema20 else 0

    return int(max(0, min(100, score)))

# ========================= FUNDAMENTAL SCORING =========================

def val(info,*keys):
    for k in keys:
        v=info.get(k)
        if isinstance(v,(int,float)) and np.isfinite(v): return float(v)
    return np.nan

def model_a(info):
    checks={
        "Market Cap > 5000Cr": val(info,"marketCap")>5000e7,
        "EPS > 15": val(info,"trailingEps")>15,
        "ROE > 15%": val(info,"returnOnEquity")>.15,
        "Debt/Equity < 0.5": val(info,"debtToEquity")<50,
        "P/FCF > 0": val(info,"priceToFreeCashFlow")>0,
        "Net margin > 10%": val(info,"profitMargins")>.10,
        "P/E < 25": val(info,"trailingPE")<25,
        "Current ratio > 1.5": val(info,"currentRatio")>1.5,
        "Dividend yield > 1%": val(info,"dividendYield")>.01,
        "Operating margin > 15%": val(info,"operatingMargins")>.15,
        "Promoter/insider > 40%": val(info,"heldPercentInsiders")>.40,
    }
    unavailable=[]
    for label,key in [
        ("P/FCF","priceToFreeCashFlow"),("Current ratio","currentRatio"),
        ("Promoter holding","heldPercentInsiders")]:
        if not np.isfinite(val(info,key)): unavailable.append(label)
    return checks,unavailable

def model_b(info):
    checks={
        "Market Cap 200-20000Cr": 200e7<val(info,"marketCap")<20000e7,
        "Quarterly sales growth >10%": val(info,"revenueGrowth")>.10,
        "Quarterly profit growth >10%": val(info,"earningsGrowth")>.10,
        "ROE >15%": val(info,"returnOnEquity")>.15,
    }
    unavailable=[]
    if not np.isfinite(val(info,"piotroskiScore")): unavailable.append("Piotroski score")
    return checks,unavailable


# ========================= FINAL FAST EXECUTION + LEARNING =========================
# Final architecture principle:
#   - Build expensive features once per symbol.
#   - Keep historical scans vectorized.
#   - Use WebSocket only for live 1-minute updates.
#   - Persist learning observations so the model improves from completed trades.
#
# The strategy rules themselves are intentionally unchanged.

FEATURE_CACHE_VERSION = "FINAL_ASOF_1"

def _feature_cache_key(symbol, df):
    if df is None or df.empty:
        return None
    last = pd.Timestamp(df.index[-1])
    return f"{FEATURE_CACHE_VERSION}:{str(symbol).upper()}:{last.isoformat()}:{len(df)}"

@st.cache_data(ttl=86400, show_spinner=False)
def features_cached(symbol, df):
    """Expensive feature calculation is cached by symbol + last candle + length."""
    return features(df)

def ensure_learning_tables():
    con = _db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS learning_observations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                market TEXT,
                symbol TEXT,
                strategy TEXT,
                signal_time TEXT,
                score REAL,
                regime TEXT,
                htf REAL,
                footprint REAL,
                strategy_score REAL,
                entry_quality REAL,
                relative_strength REAL,
                safety_score REAL,
                entry REAL,
                exit_price REAL,
                result_r REAL,
                outcome TEXT,
                holding_minutes REAL,
                source TEXT
            )
        """)
        # Backward-compatible migration: older deployments created a narrower
        # learning_observations table. Never require a destructive DB reset.
        cols={r[1] for r in con.execute("PRAGMA table_info(learning_observations)").fetchall()}
        for col,typ in {
            "learned_score":"REAL", "holding_bars":"INTEGER",
            "entry":"REAL", "exit_price":"REAL", "result_r":"REAL",
            "source":"TEXT"
        }.items():
            if col not in cols:
                con.execute(f"ALTER TABLE learning_observations ADD COLUMN {col} {typ}")

        con.execute("""
            CREATE TABLE IF NOT EXISTS model_weights(
                market TEXT NOT NULL,
                strategy TEXT NOT NULL,
                component TEXT NOT NULL,
                weight REAL NOT NULL,
                samples INTEGER NOT NULL DEFAULT 0,
                avg_r REAL,
                win_rate REAL,
                updated_at TEXT,
                PRIMARY KEY(market,strategy,component)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS scan_state(
                market TEXT PRIMARY KEY,
                last_scan TEXT,
                universe_size INTEGER DEFAULT 0,
                elapsed_seconds REAL DEFAULT 0
            )
        """)
        con.commit()
    finally:
        con.close()

ensure_learning_tables()

def _record_learning_trade(market, row, source="forward"):
    """Persist one completed trade without changing the trading rules."""
    try:
        con = _db()
        con.execute("""
            INSERT INTO learning_observations(
                created_at,market,symbol,strategy,signal_time,score,regime,
                htf,footprint,strategy_score,entry_quality,relative_strength,
                safety_score,entry,exit_price,result_r,outcome,holding_minutes,source
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            datetime.now().isoformat(timespec="seconds"),
            market,
            str(row.get("symbol", row.get("Ticker", ""))),
            str(row.get("strategy", row.get("Strategy", ""))),
            str(row.get("signal_time", row.get("Entry Date", ""))),
            float(row.get("score", row.get("Score", np.nan))),
            str(row.get("regime", row.get("Regime", ""))),
            float(row.get("htf", row.get("HTF", row.get("HTF Demand", np.nan)))),
            float(row.get("footprint", row.get("Footprint", np.nan))),
            float(row.get("strategy_score", row.get("Strategy Score", np.nan))),
            float(row.get("entry_quality", row.get("Entry Quality", np.nan))),
            float(row.get("relative_strength", row.get("Relative Strength", np.nan))),
            float(row.get("safety_score", row.get("Safety", row.get("Safety Score", np.nan)))),
            float(row.get("entry", row.get("Entry", np.nan))),
            float(row.get("exit_price", row.get("Exit", np.nan))),
            float(row.get("result_r", row.get("R", np.nan))),
            str(row.get("outcome", row.get("Outcome", ""))),
            float(row.get("holding_minutes", np.nan)),
            source
        ))
        con.commit()
        maybe_backup_db()
    except Exception:
        # Learning must never break scanning/forward monitoring.
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass

def learning_snapshot(market="INDIA"):
    ensure_learning_tables()
    con = _db()
    try:
        q = pd.read_sql_query("""
            SELECT * FROM learning_observations
            WHERE market=?
            ORDER BY id DESC
        """, con, params=(market,))
    finally:
        con.close()
    # learned_score/holding_bars are legacy columns added via ALTER TABLE
    # migration (ensure_learning_tables) and never populated by any INSERT
    # (_learn_from_backtest only writes the original column set). When every
    # value in a SQL column is NULL, pandas has nothing to infer a numeric
    # dtype from, so the column stays dtype=object holding literal Python
    # None instead of NaN - and st.dataframe() renders that as the literal
    # text "None" (this is what showed up in the Market Learning tab's
    # "Persistent Learning Database" table). Coercing explicitly avoids that
    # regardless of whether every row happens to be NULL.
    for _col in ("learned_score", "holding_bars"):
        if _col in q.columns:
            q[_col] = pd.to_numeric(q[_col], errors="coerce")
    return q

def adaptive_component_weights(market="INDIA", strategy=None):
    """
    Data-driven weights from completed observations.
    This does not alter raw strategy qualification.
    Components with insufficient evidence retain neutral weights.
    """
    q = learning_snapshot(market)
    if q.empty:
        return pd.DataFrame(columns=["Strategy","Component","Weight","Samples","Avg R","Win %"])

    if strategy is not None:
        q = q[q.strategy == f"S{strategy}"]
    if q.empty:
        return pd.DataFrame(columns=["Strategy","Component","Weight","Samples","Avg R","Win %"])

    components = [
        ("score", "Score"), ("htf", "HTF"), ("footprint", "Footprint"),
        ("strategy_score", "Strategy Score"), ("entry_quality", "Entry Quality"),
        ("relative_strength", "Relative Strength"), ("safety_score", "Safety")
    ]
    rows = []
    for s, sg in q.groupby("strategy"):
        base = sg.result_r.mean()
        for col, label in components:
            if col not in sg:
                continue
            med = sg[col].median()
            hi = sg[sg[col] >= med]
            lo = sg[sg[col] < med]
            if len(hi) < 5 or len(lo) < 5:
                weight = 1.0
            else:
                edge = float(hi.result_r.mean() - lo.result_r.mean())
                weight = float(np.clip(1.0 + edge * 0.25, 0.70, 1.35))
            rows.append({
                "Strategy": s, "Component": label, "Weight": round(weight, 3),
                "Samples": len(sg), "Avg R": round(float(base), 3),
                "Win %": round(float((sg.result_r > 0).mean() * 100), 1)
            })
    return pd.DataFrame(rows)

def adaptive_candidate_score(base_score, market="INDIA", strategy="S1", parts=None):
    """
    Learning overlay only. Raw strategy rules remain authoritative.
    With <20 observations, return the original score.
    """
    q = learning_snapshot(market)
    if q.empty or len(q) < 20 or parts is None:
        return float(base_score)

    q = q[q.strategy == strategy]
    if len(q) < 20:
        return float(base_score)

    weights = adaptive_component_weights(market, int(strategy[-1]))
    if weights.empty:
        return float(base_score)

    vals = {
        "Score": float(base_score),
        "HTF": float(parts.get("HTF Demand", 0)),
        "Footprint": float(parts.get("Footprint", 0)),
        "Strategy Score": float(parts.get("Strategy", 0)),
        "Entry Quality": float(parts.get("Entry Quality", 0)),
        "Relative Strength": float(parts.get("Relative Strength", 0)),
        "Safety": float(parts.get("Safety", 0)),
    }
    total = 0.0
    wsum = 0.0
    for _, r in weights.iterrows():
        comp = r["Component"]
        if comp in vals:
            w = float(r["Weight"])
            total += vals[comp] * w
            wsum += w
    if not wsum:
        return float(base_score)
    # Blend gently so the learned overlay cannot overpower the deterministic score.
    learned = total / wsum
    return float(np.clip(base_score * 0.70 + learned * 0.30, 0, 100))

def _fast_historical_candidates(data, strategies):
    """Vectorized candidate discovery: features once, then boolean signals."""
    rows = []
    for ticker, df in data.items():
        if df is None or len(df) < 260:
            continue
        try:
            f = features_cached(str(ticker), df.sort_index())
            f = f.replace([np.inf, -np.inf], np.nan)
            for s in strategies:
                sig = strategy_signal(f, s)
                idx = np.flatnonzero(sig.fillna(False).to_numpy())
                for i in idx:
                    rows.append((ticker, s, i))
        except Exception:
            continue
    return rows

def run_fast_backtest(data, strategies, capital=1000000, risk=0.01, sl=0.07, rr=3.0):
    """
    Faster research backtest:
      * features are calculated once per symbol;
      * signal dates are discovered vectorially;
      * only actual candidate dates enter the trade loop.
    """
    rows = []
    for ticker, df in data.items():
        if df is None or len(df) < 300:
            continue
        try:
            df = df.sort_index()
            x = features_cached(str(ticker), df).replace([np.inf, -np.inf], np.nan)
            for s in strategies:
                sig = strategy_signal(x, s).fillna(False).to_numpy()
                signal_idx = np.flatnonzero(sig)
                for i in signal_idx:
                    if i >= len(x) - 2:
                        continue
                    ei = i + 1
                    entry = float(x.close.iloc[ei])
                    stop = entry * (1 - sl)
                    one_r = entry - stop
                    qty = max(1, int(capital * risk / one_r))
                    target = entry + rr * one_r
                    ex = None
                    ep = None
                    reason = "End"
                    for j in range(ei, len(x)):
                        lo = float(x.low.iloc[j]); hi = float(x.high.iloc[j])
                        if lo <= stop:
                            ex, ep, reason = j, stop, "SL"
                            break
                        if hi >= target:
                            ex, ep, reason = j, target, f"{rr}R"
                            break
                    if ex is None:
                        ex = len(x) - 1
                        ep = float(x.close.iloc[-1])
                    pnl = (ep - entry) * qty
                    rows.append({
                        "Entry Date": x.index[ei].date(),
                        "Exit Date": x.index[ex].date(),
                        "Ticker": str(ticker).replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Entry": entry,
                        "Exit": ep,
                        "Return %": (ep / entry - 1) * 100,
                        "R": pnl / (one_r * qty),
                        "PnL ₹": pnl,
                        "Holding Days": (x.index[ex] - x.index[ei]).days,
                        "Reason": reason
                    })
        except Exception:
            continue
    return pd.DataFrame(rows)

def save_scan_state(market, universe_size, elapsed):
    con = _db()
    try:
        con.execute("""
            INSERT OR REPLACE INTO scan_state(market,last_scan,universe_size,elapsed_seconds)
            VALUES(?,?,?,?)
        """, (market, datetime.now().isoformat(timespec="seconds"),
              int(universe_size), float(elapsed)))
        con.commit()
    finally:
        con.close()



# ========================= LONG-LIVED FAST ENGINE =========================
ENGINE_VERSION = "FINAL-2_ASOF_CACHE"

def ensure_engine_tables():
    con = _db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS feature_snapshots(
                symbol TEXT PRIMARY KEY,
                last_dt TEXT NOT NULL,
                n_rows INTEGER NOT NULL,
                payload BLOB NOT NULL,
                engine_version TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS signal_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_dt TEXT NOT NULL,
                score REAL,
                learned_score REAL,
                status TEXT DEFAULT 'CANDIDATE',
                created_at TEXT NOT NULL,
                UNIQUE(market,symbol,strategy,signal_dt)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS learning_observations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                market TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                signal_dt TEXT NOT NULL,
                score REAL,
                learned_score REAL,
                result_r REAL,
                outcome TEXT,
                holding_bars INTEGER,
                regime TEXT,
                htf REAL,
                footprint REAL,
                strategy_score REAL,
                entry_quality REAL,
                relative_strength REAL,
                safety_score REAL,
                source TEXT
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_market_strategy
            ON learning_observations(market,strategy)
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics(
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        con.commit()
    finally:
        con.close()

ensure_engine_tables()

def _metric_set(key, value):
    con = _db()
    try:
        con.execute(
            "INSERT OR REPLACE INTO system_metrics(key,value,updated_at) VALUES(?,?,?)",
            (key, json.dumps(value), datetime.now().isoformat(timespec="seconds"))
        )
        con.commit()
    finally:
        con.close()

def _metric_get(key, default=None):
    con = _db()
    try:
        row = con.execute("SELECT value FROM system_metrics WHERE key=?", (key,)).fetchone()
    finally:
        con.close()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return row[0]

def _save_feature_snapshot(symbol, df):
    # Keep the feature store compact: one DataFrame per symbol.
    if df is None or df.empty:
        return
    con = _db()
    try:
        # pd.to_pickle does not support bytes in all versions, so use a bytes buffer.
        buf = io.BytesIO()
        df.to_pickle(buf)
        con.execute("""
            INSERT OR REPLACE INTO feature_snapshots
            (symbol,last_dt,n_rows,payload,engine_version)
            VALUES(?,?,?,?,?)
        """, (
            str(symbol).upper().replace(".NS",""),
            pd.Timestamp(df.index[-1]).isoformat(),
            len(df),
            sqlite3.Binary(buf.getvalue()),
            ENGINE_VERSION
        ))
        con.commit()
    finally:
        con.close()

def _load_feature_snapshot(symbol):
    con = _db()
    try:
        row = con.execute(
            "SELECT payload FROM feature_snapshots WHERE symbol=? AND engine_version=?",
            (str(symbol).upper().replace(".NS",""), ENGINE_VERSION)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    try:
        return pd.read_pickle(io.BytesIO(row[0]))
    except Exception:
        return None

def _frame_ends_on_open_session(df):
    """True when the frame's last row is today's candle while the cash session
    is still trading, i.e. a bar that has not closed yet."""
    if df is None or len(df) == 0:
        return False
    try:
        return pd.Timestamp(df.index[-1]).date() >= date.today() and nse_market_is_open()
    except Exception:
        return False


def _frame_fingerprint(df):
    """Identity of a price frame for cache validation: last date is NOT enough.

    The persisted feature snapshot used to be reused whenever the last DATE
    matched. That silently returned stale features in two real cases: a candle
    revised by the exchange after it was first stored, and today's still-forming
    intraday bar, whose close changes every time the scanner runs. Including the
    row count and the last close makes both invalidate correctly.
    """
    if df is None or len(df) == 0:
        return None
    try:
        last_close = float(df["close"].iloc[-1])
    except Exception:
        last_close = float("nan")
    return (pd.Timestamp(df.index[-1]).isoformat(), int(len(df)), round(last_close, 6))


def _snapshot_matches(snapshot, df):
    a = _frame_fingerprint(snapshot)
    b = _frame_fingerprint(df)
    return a is not None and b is not None and a == b


@st.cache_data(ttl=86400,show_spinner=False)
def features_fast(symbol, df):
    """Strict as-of feature engine. Historical rows never see future days inside
    their current week/month. This is the core anti-lookahead safeguard."""
    key=_load_feature_snapshot(symbol)
    if key is not None and not key.empty and _snapshot_matches(key, df):
        return key
    d=df.sort_index().copy()
    x=d.copy()
    for n in [10,20,50,200,250]:
        x[f"ema{n}"]=ema(x.close,n)
    x["vol20"]=sma(x.volume,20); x["vol30"]=sma(x.volume,30); x["rsi14"]=rsi(x.close); x["relvol"]=x.volume/x.vol20
    tr=pd.concat([x.high-x.low,(x.high-x.close.shift()).abs(),(x.low-x.close.shift()).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.rolling(14).mean()

    # Weekly as-of state: one cheap loop per week, not one loop per day.
    wk_key=x.index.to_period("W-FRI")
    wk_rows=[]
    for period, g in x.groupby(wk_key, sort=True):
        g=g.sort_index(); close=g.close.iloc[-1]
        wk_rows.append((period, g.open.iloc[0], g.high.max(), g.low.min(), close, g.volume.sum()))
    wk=pd.DataFrame(wk_rows, columns=["period","open","high","low","close","volume"]).set_index("period")
    wk["rsi14"]=rsi(wk.close,14); wk["ema20"]=ema(wk.close,20); wk["ema50"]=ema(wk.close,50)
    wk_map={p:row for p,row in wk.iterrows()}
    x["wrsi14"]=[wk_map.get(p,{}).get("rsi14",np.nan) for p in wk_key]
    x["wema20"]=[wk_map.get(p,{}).get("ema20",np.nan) for p in wk_key]
    x["wema50"]=[wk_map.get(p,{}).get("ema50",np.nan) for p in wk_key]
    x["wclose"]=[wk_map.get(p,{}).get("close",np.nan) for p in wk_key]

    # Monthly as-of state. Each daily row uses the current month's partial OHLCV.
    mo_key=x.index.to_period("M")
    mo_rows=[]
    for period,g in x.groupby(mo_key,sort=True):
        g=g.sort_index(); mo_rows.append((period,g.open.iloc[0],g.high.max(),g.low.min(),g.close.iloc[-1],g.volume.sum()))
    mo=pd.DataFrame(mo_rows,columns=["period","open","high","low","close","volume"]).set_index("period")
    mo["rsi14"]=rsi(mo.close,14); mo["ema10"]=ema(mo.close,10); mo["ema15"]=ema(mo.close,15); mo["ema20"]=ema(mo.close,20)
    mo["mom"]=mo.close.pct_change()*100; mo["prev_close"]=mo.close.shift(1); mo["prev_high"]=mo.high.shift(1); mo["prev_low"]=mo.low.shift(1)
    mo["mom20max"]=mo.mom.rolling(20,min_periods=1).max()
    cross=(mo.ema10>mo.ema20)&(mo.ema10.shift(1)<=mo.ema20.shift(1)); mo["cross_10_20"]=cross.astype(int); mo["cross_count20"]=mo.cross_10_20.rolling(20,min_periods=1).sum()
    mo_map={p:row for p,row in mo.iterrows()}
    fields={"mclose":"close","mopen":"open","mhigh":"high","mlow":"low","mrsi14":"rsi14","mema10":"ema10","mema15":"ema15","mema20":"ema20","mmom":"mom","mmax20":"mom20max","mprevclose":"prev_close","mprevhigh":"prev_high","mprevlow":"prev_low","m_cross_count20":"cross_count20","m_cross_10_20":"cross_10_20"}
    for out,src in fields.items():
        x[out]=[mo_map.get(p,{}).get(src,np.nan) for p in mo_key]
    x=x.replace([np.inf,-np.inf],np.nan)
    # Never persist features derived from a still-forming intraday bar: the
    # snapshot store is shared with the backtest/research paths, which must only
    # ever see completed sessions.
    if not _frame_ends_on_open_session(x):
        try:_save_feature_snapshot(symbol,x)
        except Exception:pass
    return x

# ========================= RAW STRATEGY LEARNING ARCHITECTURE — Phase 9 =========================
# Phase 1 (raw signal capture, no >=85 gate) + Phase 2 (feature fingerprint) of the
# research architecture redesign. Phases 3-6 (pattern discovery, similarity engine, a
# new marking model, Mentor agents) build ON TOP of the data this produces and are not
# attempted here - this needs to run long enough to accumulate a meaningful sample
# first (months, not days).
#
# ADDITIVE, NOT A REPLACEMENT: the existing run_local_backtest()/_professional_bt()
# (with its >=85 threshold gate) is completely untouched - it still works exactly as
# before. This adds a SEPARATE raw-capture path (run_raw_signal_backtest) writing to
# a NEW table (raw_signal_fingerprints), so nothing about the existing >=85 backtest
# or scanner changes until this data is deliberately acted on later.
#
# THE GATE THIS BYPASSES (deliberately, only in this parallel path): the existing
# _professional_bt() does `if score<int(threshold):continue` before ever simulating a
# signal - discarding it before it's ever recorded, so the learning data can never
# discover that a lower-scored setup might actually outperform. run_raw_signal_backtest()
# below has NO such gate.
#
# PERFORMANCE FIX APPLIED (found while integrating, not present in the original
# design): the original draft of this loop called regime_from_index(hist) and
# safety({}, hist) per signal, recomputing the ENTIRE technical feature set
# (features()/features_slow(), including weekly/monthly resampling) from scratch on a
# growing history slice for EVERY signal in EVERY strategy across the ENTIRE universe.
# This is the exact O(n^2)-class hot path already found and fixed twice elsewhere in
# this codebase (the original S1-S4 backtest loop, and the SMC backtest) - and would
# have been WORSE here, since removing the score gate means simulating far more
# signals per ticker with no early pruning. Fixed by reusing the same O(1) functions
# the existing >=85 backtest already uses: _regime_from_row(f,i) for regime, and
# _safety_fast_series(df) computed ONCE per ticker + _safety_from_row(avg_value,
# abnormal,i) per signal for safety - see bench_raw_signal_perf.py (scratch dir) for a
# measured before/after comparison. Note the original design draft's score/parts line,
# `_row_score(f, i, s, regime, safe)`, referenced a function that does not exist in
# some older versions of this codebase's history - it DOES exist in the current
# app.py (added by this same earlier O(n^2) fix elsewhere) and is used unchanged here.
#
# WHAT'S COMPUTED NOW vs DEFERRED (unchanged from the original design, being honest
# about scope): trend direction, MA distances, ATR/volatility, RelVol, volume
# expansion, candle body/wick structure, breakout/retest, pullback depth, swing
# distance, RSI, a simple MACD (not in features_fast(), added here), distance from
# recent high/low, gap %, support/resistance distance (swing proxy), retracement %
# + duration for S4, rejection/reclaim candle heuristics, trade geometry, safety
# score/flags. DEFERRED (need data sources not wired in yet - stubbed NULL, not
# faked): Nifty/Bank Nifty trend, market breadth, sector trend/regime, earnings
# proximity, valuation/debt/growth history.

def ensure_raw_fingerprint_table():
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS raw_signal_fingerprints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER, created_at TEXT,
            ticker TEXT, strategy TEXT, signal_date TEXT, entry_date TEXT, exit_date TEXT,
            score REAL, outcome TEXT, entry REAL, stop REAL, target REAL, exit_price REAL,
            return_pct REAL, r_multiple REAL, holding_bars INTEGER, mfe_pct REAL, mae_pct REAL,

            -- price / chart structure
            trend_direction TEXT, dist_ema20_atr REAL, dist_ema50_atr REAL, dist_ema200_atr REAL,
            atr_pct REAL, relvol REAL, relvol_trend REAL, candle_body_pct REAL,
            candle_upper_wick_pct REAL, candle_lower_wick_pct REAL, breakout_20d INTEGER,
            breakout_50d INTEGER, pullback_depth_pct REAL, dist_recent_high_atr REAL,
            dist_recent_low_atr REAL, gap_pct REAL, dist_support_atr REAL, dist_resistance_atr REAL,
            rsi14 REAL, macd_hist REAL,

            -- retracement (S4-relevant, computed for all strategies where applicable)
            retracement_pct REAL, retracement_duration_bars INTEGER, retracement_volume_ratio REAL,
            rejection_candle INTEGER, reclaim_candle INTEGER,

            -- market conditions (deferred fields NULL until Phase 2b)
            market_regime TEXT, nifty_trend TEXT, market_breadth REAL, sector_trend TEXT,

            -- trade geometry
            stop_distance_pct REAL, target_distance_pct REAL, expected_rr REAL, atr_adjusted_stop REAL,

            -- safety / fundamental context (what's already available)
            safety_score REAL, safety_flags TEXT,

            -- deterministic score components (kept for comparison against new model later)
            score_htf REAL, score_footprint REAL, score_entry_quality REAL, score_relative_strength REAL,

            source TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS raw_signal_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT,
            start_date TEXT, end_date TEXT, universe_size INTEGER, signals_captured INTEGER,
            elapsed_seconds REAL, status TEXT
        )""")
        con.commit()
    finally:
        con.close()

ensure_raw_fingerprint_table()


def _simple_swings(df, left=3, right=3):
    """Lightweight fractal swing detection for retracement/support-resistance
    proxies. Only needs to look backward from index i (as-of correct)."""
    highs = df["high"].values; lows = df["low"].values
    n = len(df)
    sh, sl = [], []
    for i in range(left, n - right):
        if highs[i] == highs[i-left:i+right+1].max():
            sh.append(i)
        if lows[i] == lows[i-left:i+right+1].min():
            sl.append(i)
    return sh, sl


def _retracement_features(df, i):
    """Computes retracement % from the most recent swing leg, using only
    data up to and including index i (as-of correct, no look-ahead).
    Returns dict — values are None if not enough swing history yet.
    """
    hist = df.iloc[:i+1]
    if len(hist) < 20:
        return {"retracement_pct": None, "retracement_duration_bars": None, "retracement_volume_ratio": None,
                "rejection_candle": 0, "reclaim_candle": 0}

    window = hist.iloc[-120:] if len(hist) > 120 else hist
    sh, sl = _simple_swings(window)
    if not sh or not sl:
        return {"retracement_pct": None, "retracement_duration_bars": None, "retracement_volume_ratio": None,
                "rejection_candle": 0, "reclaim_candle": 0}

    offset = len(hist) - len(window)
    last_high_idx = sh[-1] + offset
    last_low_idx = sl[-1] + offset

    # Determine which came more recently to establish leg direction
    if last_high_idx > last_low_idx:
        leg_low = float(hist["low"].iloc[last_low_idx]); leg_high = float(hist["high"].iloc[last_high_idx])
        current = float(hist["close"].iloc[-1])
        rng = leg_high - leg_low
        retr_pct = ((leg_high - current) / rng * 100) if rng > 0 else None
        duration = len(hist) - 1 - last_high_idx
    else:
        leg_low = float(hist["low"].iloc[last_low_idx]); leg_high = float(hist["high"].iloc[last_high_idx])
        current = float(hist["close"].iloc[-1])
        rng = leg_high - leg_low
        retr_pct = ((current - leg_low) / rng * 100) if rng > 0 else None
        duration = len(hist) - 1 - last_low_idx

    vol_ratio = None
    if duration and duration > 0 and len(hist) > duration * 2:
        recent_vol = hist["volume"].iloc[-duration:].mean()
        prior_vol = hist["volume"].iloc[-duration*2:-duration].mean()
        vol_ratio = float(recent_vol / prior_vol) if prior_vol and prior_vol > 0 else None

    last_bar = hist.iloc[-1]
    bar_range = max(last_bar["high"] - last_bar["low"], 1e-9)
    close_pos = (last_bar["close"] - last_bar["low"]) / bar_range
    rejection = int(close_pos < 0.3)  # closed near the low of its range
    reclaim = int(close_pos > 0.7)    # closed near the high of its range

    return {
        "retracement_pct": round(retr_pct, 2) if retr_pct is not None else None,
        "retracement_duration_bars": int(duration) if duration is not None else None,
        "retracement_volume_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
        "rejection_candle": rejection, "reclaim_candle": reclaim,
    }


def _support_resistance_distance(df, i, atr_val):
    """Distance (in ATR units) to the nearest swing high (resistance) and
    swing low (support) above/below current price, as-of index i."""
    hist = df.iloc[max(0, i-120):i+1]
    if len(hist) < 20 or not atr_val or atr_val <= 0:
        return None, None
    sh, sl = _simple_swings(hist)
    current = float(hist["close"].iloc[-1])
    res_levels = [float(hist["high"].iloc[j]) for j in sh if float(hist["high"].iloc[j]) > current]
    sup_levels = [float(hist["low"].iloc[j]) for j in sl if float(hist["low"].iloc[j]) < current]
    dist_res = (min(res_levels) - current) / atr_val if res_levels else None
    dist_sup = (current - max(sup_levels)) / atr_val if sup_levels else None
    return dist_res, dist_sup


def _simple_macd_hist(close_series):
    """Standard 12/26/9 MACD histogram — not currently in features_fast(),
    added here since the research architecture flags it as a needed feature."""
    ema12 = close_series.ewm(span=12, adjust=False).mean()
    ema26 = close_series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return float((macd_line - signal_line).iloc[-1])


def compute_signal_fingerprint(df, f, i, entry, stop, target, regime, safe, safety_flags, parts):
    """df: raw OHLCV. f: features_fast() output (has ema/rsi/atr/relvol etc).
    i: signal bar index. Everything here uses ONLY data up to and including
    index i — no look-ahead. Returns a flat dict ready for DB insertion.
    """
    row = f.iloc[i]
    close = float(row["close"]); atr = float(row.get("atr14", np.nan))

    ema20, ema50, ema200 = row.get("ema20", np.nan), row.get("ema50", np.nan), row.get("ema200", np.nan)
    if pd.notna(ema20) and pd.notna(ema50) and pd.notna(ema200):
        if close > ema20 > ema50 > ema200:
            trend = "strong_up"
        elif close > ema50 > ema200:
            trend = "up"
        elif close < ema20 < ema50 < ema200:
            trend = "strong_down"
        elif close < ema50 < ema200:
            trend = "down"
        else:
            trend = "mixed"
    else:
        trend = "unknown"

    atr_safe = atr if (pd.notna(atr) and atr > 0) else np.nan
    dist_ema20 = (close - ema20) / atr_safe if pd.notna(atr_safe) and pd.notna(ema20) else None
    dist_ema50 = (close - ema50) / atr_safe if pd.notna(atr_safe) and pd.notna(ema50) else None
    dist_ema200 = (close - ema200) / atr_safe if pd.notna(atr_safe) and pd.notna(ema200) else None

    relvol = float(row.get("relvol", np.nan)) if pd.notna(row.get("relvol", np.nan)) else None
    relvol_series = f["relvol"].iloc[max(0, i-20):i+1]
    relvol_trend = float(relvol_series.iloc[-1] - relvol_series.mean()) if len(relvol_series) > 5 and relvol_series.notna().any() else None

    bar_range = max(float(row["high"]) - float(row["low"]), 1e-9)
    body = abs(float(row["close"]) - float(row["open"]))
    upper_wick = float(row["high"]) - max(float(row["close"]), float(row["open"]))
    lower_wick = min(float(row["close"]), float(row["open"])) - float(row["low"])

    high20 = df["high"].iloc[max(0, i-20):i].max() if i > 0 else np.nan
    high50 = df["high"].iloc[max(0, i-50):i].max() if i > 0 else np.nan
    low20 = df["low"].iloc[max(0, i-20):i].min() if i > 0 else np.nan
    breakout_20 = int(pd.notna(high20) and close > high20)
    breakout_50 = int(pd.notna(high50) and close > high50)
    pullback_depth = ((high20 - close) / high20 * 100) if pd.notna(high20) and high20 > 0 else None

    dist_recent_high = (high20 - close) / atr_safe if pd.notna(atr_safe) and pd.notna(high20) else None
    dist_recent_low = (close - low20) / atr_safe if pd.notna(atr_safe) and pd.notna(low20) else None

    prev_close = float(df["close"].iloc[i-1]) if i > 0 else None
    gap_pct = ((float(row["open"]) - prev_close) / prev_close * 100) if prev_close else None

    dist_res, dist_sup = _support_resistance_distance(df, i, atr_safe)
    retr = _retracement_features(df, i)

    macd_hist = None
    try:
        macd_hist = _simple_macd_hist(df["close"].iloc[:i+1])
    except Exception:
        pass

    stop_dist_pct = abs(entry - stop) / entry * 100 if entry else None
    target_dist_pct = abs(target - entry) / entry * 100 if entry else None
    expected_rr = abs(target - entry) / abs(entry - stop) if entry and stop and entry != stop else None
    atr_adj_stop = abs(entry - stop) / atr_safe if pd.notna(atr_safe) and atr_safe > 0 else None

    return {
        "trend_direction": trend,
        "dist_ema20_atr": round(dist_ema20, 3) if dist_ema20 is not None else None,
        "dist_ema50_atr": round(dist_ema50, 3) if dist_ema50 is not None else None,
        "dist_ema200_atr": round(dist_ema200, 3) if dist_ema200 is not None else None,
        "atr_pct": round(atr_safe / close * 100, 3) if pd.notna(atr_safe) and close else None,
        "relvol": round(relvol, 3) if relvol is not None else None,
        "relvol_trend": round(relvol_trend, 3) if relvol_trend is not None else None,
        "candle_body_pct": round(body / bar_range * 100, 2),
        "candle_upper_wick_pct": round(upper_wick / bar_range * 100, 2),
        "candle_lower_wick_pct": round(lower_wick / bar_range * 100, 2),
        "breakout_20d": breakout_20, "breakout_50d": breakout_50,
        "pullback_depth_pct": round(pullback_depth, 2) if pullback_depth is not None else None,
        "dist_recent_high_atr": round(dist_recent_high, 3) if dist_recent_high is not None else None,
        "dist_recent_low_atr": round(dist_recent_low, 3) if dist_recent_low is not None else None,
        "gap_pct": round(gap_pct, 3) if gap_pct is not None else None,
        "dist_support_atr": round(dist_sup, 3) if dist_sup is not None else None,
        "dist_resistance_atr": round(dist_res, 3) if dist_res is not None else None,
        "rsi14": round(float(row.get("rsi14", np.nan)), 2) if pd.notna(row.get("rsi14", np.nan)) else None,
        "macd_hist": round(macd_hist, 4) if macd_hist is not None else None,

        "retracement_pct": retr["retracement_pct"],
        "retracement_duration_bars": retr["retracement_duration_bars"],
        "retracement_volume_ratio": retr["retracement_volume_ratio"],
        "rejection_candle": retr["rejection_candle"], "reclaim_candle": retr["reclaim_candle"],

        "market_regime": regime, "nifty_trend": None, "market_breadth": None, "sector_trend": None,  # Phase 2b

        "stop_distance_pct": round(stop_dist_pct, 3) if stop_dist_pct is not None else None,
        "target_distance_pct": round(target_dist_pct, 3) if target_dist_pct is not None else None,
        "expected_rr": round(expected_rr, 3) if expected_rr is not None else None,
        "atr_adjusted_stop": round(atr_adj_stop, 3) if atr_adj_stop is not None else None,

        "safety_score": safe, "safety_flags": ", ".join(safety_flags) if safety_flags else "",

        "score_htf": parts.get("HTF Demand", 0), "score_footprint": parts.get("Footprint", 0),
        "score_entry_quality": parts.get("Entry Quality", 0), "score_relative_strength": parts.get("Relative Strength", 0),
    }


def run_raw_signal_backtest(data, strategies, start, end, progress_cb=None):
    """Near-identical to _professional_bt(), EXCEPT: no score threshold gate —
    every legitimate S1-S4 signal is simulated and its full fingerprint
    recorded, regardless of score. This is what lets later research discover
    whether score actually predicts outcome, instead of only ever seeing
    pre-filtered survivors.

    data: dict of {ticker: df} exactly as the existing local backtest loop
    expects (e.g. from load_local_backtest_data()/build_fast_data_cache()).
    Returns a DataFrame of everything captured (also persisted to DB).
    """
    rows = []
    tickers = list(data.keys())
    for n, ticker in enumerate(tickers):
        try:
            df = data[ticker]
            if df is None or df.empty or len(df) < 260:
                continue
            df = df.sort_index()
            f = features_fast(str(ticker), df).replace([np.inf, -np.inf], np.nan)
            if f.empty:
                continue

            # Same O(1) precompute the existing >=85 backtest uses (see
            # _professional_bt) instead of recomputing regime_from_index()/
            # safety({}, hist) from scratch per signal - the fix this phase
            # needed most, since removing the score gate means many more
            # signals get simulated per ticker with no early pruning.
            avg_value, abnormal = _safety_fast_series(df)

            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                for i in np.flatnonzero(sig):
                    dt = pd.Timestamp(f.index[i])
                    if dt < start or dt > end or i >= len(df) - 1:
                        continue
                    regime, _ = _regime_from_row(f, i)
                    safe, _, safety_flags = _safety_from_row(avg_value, abnormal, i)
                    score, parts = _row_score(f, i, s, regime, safe)
                    # NO GATE HERE — this is the entire point of Phase 1.

                    entry_i = i + 1
                    entry = float(df.close.iloc[entry_i])
                    if not np.isfinite(entry) or entry <= 0:
                        continue
                    stop = entry * 0.93
                    target = entry + 3 * (entry - stop)

                    last = min(len(df) - 1, entry_i + 60)
                    outcome = "TIMEOUT"; exit_price = float(df.close.iloc[last]); held = last - entry_i
                    max_high = entry; min_low = entry
                    for j in range(entry_i, last + 1):
                        bar = df.iloc[j]
                        max_high = max(max_high, float(bar.high)); min_low = min(min_low, float(bar.low))
                        if bar.low <= stop:
                            outcome, exit_price, held = "LOSS", stop, j - entry_i; break
                        if bar.high >= target:
                            outcome, exit_price, held = "WIN", target, j - entry_i; break

                    gross_pct = (exit_price / entry - 1) * 100
                    return_pct = gross_pct - BT_COST_PCT
                    risk = entry - stop
                    r_mult = return_pct / ((risk / entry) * 100) if risk > 0 else 0
                    mfe = (max_high / entry - 1) * 100; mae = (min_low / entry - 1) * 100

                    fingerprint = compute_signal_fingerprint(df, f, i, entry, stop, target, regime, safe, safety_flags, parts)

                    rows.append({
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "ticker": str(ticker).replace(".NS", ""), "strategy": f"S{s}",
                        "signal_date": str(dt.date()), "entry_date": str(df.index[entry_i].date()),
                        "exit_date": str(df.index[entry_i + held].date()),
                        "score": float(score), "outcome": outcome, "entry": round(entry, 2),
                        "stop": round(stop, 2), "target": round(target, 2), "exit_price": round(exit_price, 2),
                        "return_pct": round(return_pct, 2), "r_multiple": round(float(r_mult), 2),
                        "holding_bars": int(held), "mfe_pct": round(mfe, 2), "mae_pct": round(mae, 2),
                        "source": "raw_phase1",
                        **fingerprint,
                    })
        except Exception:
            continue
        finally:
            if progress_cb:
                progress_cb(n + 1, len(tickers), str(ticker))

    result = pd.DataFrame(rows)
    _persist_raw_fingerprints(result, start, end, len(tickers))
    return result


def _persist_raw_fingerprints(result, start, end, universe_size):
    if result.empty:
        return
    con = _db()
    try:
        cur = con.execute(
            """INSERT INTO raw_signal_runs(created_at,market,start_date,end_date,universe_size,signals_captured,elapsed_seconds,status)
               VALUES(?,?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"), "INDIA", str(start), str(end),
             universe_size, len(result), 0.0, "COMPLETED")
        )
        run_id = cur.lastrowid
        cols = list(result.columns)
        db_cols = [c for c in cols if c not in ("created_at",)]  # created_at handled per-row already present
        placeholders = ",".join(["?"] * (len(db_cols) + 1))
        col_list = ",".join(["run_id"] + db_cols)
        rows = [tuple([run_id] + [r.get(c) for c in db_cols]) for _, r in result.iterrows()]
        con.executemany(f"INSERT INTO raw_signal_fingerprints({col_list}) VALUES({placeholders})", rows)
        con.commit()
    finally:
        con.close()


# ========================= STOP-LOSS CALIBRATION STUDY =========================
# ADDITIVE, EVIDENCE-ONLY — NEVER changes what the live system does. The scanner's LIVE
# stop-loss, the existing >=85 gated backtest (_professional_bt), forward-test tracking,
# and run_raw_signal_backtest() above all keep using the fixed entry*0.93 (7%) stop
# completely untouched. This is a SEPARATE study that backtests several CANDIDATE stop-loss
# schemes against the SAME real historical S1-S4 signals and reports real win%/avg-R
# evidence broken out by strategy AND market regime (never one blended number — the whole
# point is "how much SL is good depends on the stock chart and market conditions").
#
# LONG-ONLY CONFIRMED: every S1-S4 condition in strategy_signal() is a bullish/long setup
# (no short branch exists anywhere in that function) — every scheme below places its stop
# BELOW entry accordingly.
#
# SAME O(1) PATTERN AS run_raw_signal_backtest() ABOVE, deliberately copied rather than
# reinvented: features_fast()/_safety_fast_series() run ONCE per ticker; _regime_from_row()/
# _safety_from_row() are O(1) per-signal lookups. This loop never calls regime_from_index()/
# safety() — those recompute the full feature set from scratch per call and have already
# caused an O(n^2) hang bug three times in this codebase's history (original S1-S4 backtest,
# SMC backtest, and once already in run_raw_signal_backtest() itself before its fix).
#
# SAME 3R TARGET FOR EVERY SCHEME (explicit design choice): each scheme changes the stop
# distance, so to keep R-multiples comparable ACROSS schemes and isolate the effect of stop
# PLACEMENT (rather than conflating it with a different reward:risk ratio), every scheme
# still uses target = entry + 3*(entry-stop) computed from ITS OWN stop distance — the same
# 3R convention run_raw_signal_backtest() and s4_ema20_extension_calibration() already use.
#
# COST OF REPEATING THE FORWARD WALK PER SCHEME: the expensive part (per-ticker feature
# computation) happens once; only the cheap forward-bar walk (O(bars-until-exit), max 60
# bars here) repeats once per scheme (5) per signal — acceptable and NOT the O(n^2) pattern
# above, which was about re-deriving the entire feature matrix, not walking forward bars.

SL_CALIBRATION_MIN_BUCKET_SAMPLES = 15  # same threshold/spirit as S4_CALIBRATION_MIN_BUCKET_SAMPLES


def sl_scheme_fixed_pct_7(entry, atr_abs, structure_stop_price):
    """CURRENT LIVE BASELINE (entry*0.93, i.e. fixed 7% SL) — included deliberately so
    this study can show whether any candidate scheme actually beats the status quo,
    rather than assuming the status quo needs replacing."""
    return entry * 0.93


def sl_scheme_atr_mult_1_5(entry, atr_abs, structure_stop_price):
    if atr_abs is None or not np.isfinite(atr_abs) or atr_abs <= 0:
        return None
    return entry - 1.5 * atr_abs


def sl_scheme_atr_mult_2_0(entry, atr_abs, structure_stop_price):
    if atr_abs is None or not np.isfinite(atr_abs) or atr_abs <= 0:
        return None
    return entry - 2.0 * atr_abs


def sl_scheme_atr_mult_2_5(entry, atr_abs, structure_stop_price):
    if atr_abs is None or not np.isfinite(atr_abs) or atr_abs <= 0:
        return None
    return entry - 2.5 * atr_abs


def sl_scheme_structure_swing_low(entry, atr_abs, structure_stop_price):
    """Stop placed just below the nearest support/swing-low level at signal time
    (structure_stop_price, derived from the same swing-detection logic that produces
    the dist_support_atr fingerprint field — see _support_resistance_distance()).
    Returns None (scheme UNAVAILABLE for this signal) when no nearby support level was
    found, rather than fabricating one."""
    if structure_stop_price is None or not np.isfinite(structure_stop_price) or structure_stop_price <= 0:
        return None
    if structure_stop_price >= entry:
        return None  # support at/above entry isn't a usable stop for a long
    return structure_stop_price


SL_CALIBRATION_SCHEMES = {
    "fixed_pct_7": sl_scheme_fixed_pct_7,
    "atr_mult_1_5": sl_scheme_atr_mult_1_5,
    "atr_mult_2_0": sl_scheme_atr_mult_2_0,
    "atr_mult_2_5": sl_scheme_atr_mult_2_5,
    "structure_swing_low": sl_scheme_structure_swing_low,
}


def run_sl_calibration_study(data, strategies, start, end, progress_cb=None):
    """Backtests every candidate SL scheme in SL_CALIBRATION_SCHEMES against the SAME
    real historical S1-S4 signals and SAME forward bars, isolating the effect of stop
    PLACEMENT alone. Structured like run_raw_signal_backtest(): per-ticker feature
    computation happens ONCE, regime/safety are O(1) row lookups per signal, and each
    scheme independently walks forward from the same entry bar.

    data: dict of {ticker: df} exactly as run_raw_signal_backtest()/the existing
    backtest loop expect. Returns a DataFrame of one row per (ticker, strategy, signal,
    scheme) trade — also persisted (aggregated) to sl_calibration_results/_runs.
    """
    rows = []
    tickers = list(data.keys())
    ticker = None
    for n, ticker in enumerate(tickers):
        try:
            df = data[ticker]
            if df is None or df.empty or len(df) < 260:
                continue
            df = df.sort_index()
            f = features_fast(str(ticker), df).replace([np.inf, -np.inf], np.nan)
            if f.empty:
                continue

            # Once per ticker — NOT per scheme, NOT per signal. See header comment.
            avg_value, abnormal = _safety_fast_series(df)

            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                for i in np.flatnonzero(sig):
                    dt = pd.Timestamp(f.index[i])
                    if dt < start or dt > end or i >= len(df) - 1:
                        continue
                    regime, _ = _regime_from_row(f, i)          # O(1) — never regime_from_index()
                    safe, _, _ = _safety_from_row(avg_value, abnormal, i)  # O(1) — never safety()

                    entry_i = i + 1
                    entry = float(df.close.iloc[entry_i])
                    if not np.isfinite(entry) or entry <= 0:
                        continue

                    atr = float(f.iloc[i].get("atr14", np.nan))
                    atr_abs = atr if (np.isfinite(atr) and atr > 0) else None

                    _, dist_sup = _support_resistance_distance(df, i, atr_abs)
                    structure_stop_price = (
                        entry - dist_sup * atr_abs
                        if (dist_sup is not None and atr_abs is not None) else None
                    )

                    last = min(len(df) - 1, entry_i + 60)

                    for scheme_name, scheme_fn in SL_CALIBRATION_SCHEMES.items():
                        stop = scheme_fn(entry, atr_abs, structure_stop_price)
                        if stop is None or not np.isfinite(stop) or stop <= 0 or stop >= entry:
                            continue  # scheme unavailable for this signal — skip, never fabricate

                        # SAME 3R convention for every scheme — see header comment.
                        target = entry + 3 * (entry - stop)

                        outcome = "TIMEOUT"; exit_price = float(df.close.iloc[last]); held = last - entry_i
                        for j in range(entry_i, last + 1):
                            bar = df.iloc[j]
                            if bar.low <= stop:
                                outcome, exit_price, held = "LOSS", stop, j - entry_i; break
                            if bar.high >= target:
                                outcome, exit_price, held = "WIN", target, j - entry_i; break

                        risk = entry - stop
                        r_mult = (exit_price - entry) / risk if risk > 0 else 0.0

                        rows.append({
                            "ticker": str(ticker).replace(".NS", ""), "strategy": f"S{s}",
                            "signal_date": str(dt.date()), "market_regime": regime,
                            "safety_score": safe, "scheme": scheme_name,
                            "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
                            "outcome": outcome, "r_multiple": round(float(r_mult), 3),
                            "holding_bars": int(held),
                        })
        except Exception:
            continue
        finally:
            if progress_cb:
                progress_cb(n + 1, len(tickers), str(ticker))

    result = pd.DataFrame(rows)
    _persist_sl_calibration(result, start, end, len(tickers))
    return result


def _sl_calibration_aggregate(result):
    """One row per (strategy, market_regime, scheme) — the shape persisted to
    sl_calibration_results and used by both the DB writer and the UI report."""
    cols = ["strategy", "market_regime", "scheme", "trades", "win_pct", "avg_r", "avg_holding_bars"]
    if result.empty:
        return pd.DataFrame(columns=cols)
    g = result.groupby(["strategy", "market_regime", "scheme"]).agg(
        trades=("r_multiple", "count"),
        win_pct=("outcome", lambda x: float((x == "WIN").mean() * 100)),
        avg_r=("r_multiple", "mean"),
        avg_holding_bars=("holding_bars", "mean"),
    ).reset_index()
    g["win_pct"] = g.win_pct.round(1)
    g["avg_r"] = g.avg_r.round(3)
    g["avg_holding_bars"] = g.avg_holding_bars.round(1)
    return g


def sl_calibration_report(result):
    """UI-facing version of _sl_calibration_aggregate(): renames for display and flags
    under-sampled buckets rather than omitting them (same philosophy as
    s4_extension_bucket_report() — small-N buckets are noise, not evidence, but they are
    still shown so nobody mistakes silence for a clean result)."""
    g = _sl_calibration_aggregate(result)
    if g.empty:
        return g
    g = g.rename(columns={
        "strategy": "Strategy", "market_regime": "Regime", "scheme": "Scheme",
        "trades": "Trades", "win_pct": "Win %", "avg_r": "Avg R", "avg_holding_bars": "Avg Holding Bars",
    })
    g[f"Reliable (>={SL_CALIBRATION_MIN_BUCKET_SAMPLES} samples)"] = g.Trades >= SL_CALIBRATION_MIN_BUCKET_SAMPLES
    return g.sort_values(["Strategy", "Regime", "Avg R"], ascending=[True, True, False]).reset_index(drop=True)


def ensure_sl_calibration_tables():
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS sl_calibration_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT,
            start_date TEXT, end_date TEXT, universe_size INTEGER, trades_captured INTEGER,
            status TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS sl_calibration_results(
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER,
            strategy TEXT, market_regime TEXT, scheme TEXT,
            trades INTEGER, win_pct REAL, avg_r REAL, avg_holding_bars REAL
        )""")
        con.commit()
    finally:
        con.close()

ensure_sl_calibration_tables()


def _persist_sl_calibration(result, start, end, universe_size):
    if result.empty:
        return
    agg = _sl_calibration_aggregate(result)
    con = _db()
    try:
        cur = con.execute(
            """INSERT INTO sl_calibration_runs(created_at,market,start_date,end_date,universe_size,trades_captured,status)
               VALUES(?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"), "INDIA", str(start), str(end),
             universe_size, len(result), "COMPLETED")
        )
        run_id = cur.lastrowid
        db_rows = [
            (run_id, r.strategy, r.market_regime, r.scheme, int(r.trades), float(r.win_pct),
             float(r.avg_r), float(r.avg_holding_bars))
            for r in agg.itertuples()
        ]
        con.executemany(
            """INSERT INTO sl_calibration_results(run_id,strategy,market_regime,scheme,trades,win_pct,avg_r,avg_holding_bars)
               VALUES(?,?,?,?,?,?,?,?)""", db_rows
        )
        con.commit()
    finally:
        con.close()


RAW_SIGNAL_NUMERIC_FEATURES = [
    "score", "score_htf", "score_footprint", "score_entry_quality", "score_relative_strength",
    "dist_ema20_atr", "dist_ema50_atr", "dist_ema200_atr", "atr_pct",
    "relvol", "relvol_trend", "candle_body_pct", "candle_upper_wick_pct", "candle_lower_wick_pct",
    "breakout_20d", "breakout_50d", "pullback_depth_pct",
    "dist_recent_high_atr", "dist_recent_low_atr", "gap_pct",
    "dist_support_atr", "dist_resistance_atr", "rsi14", "macd_hist",
    "retracement_pct", "retracement_duration_bars", "retracement_volume_ratio",
    "rejection_candle", "reclaim_candle",
    "stop_distance_pct", "target_distance_pct", "expected_rr", "atr_adjusted_stop",
    "safety_score",
]

RAW_SIGNAL_SCORE_COMPONENTS = [
    "score_htf", "score_footprint", "score_entry_quality", "score_relative_strength", "safety_score",
]


def _feature_gap_table(wins_df, losses_df, feature_cols, min_n=5):
    """Plain descriptive win-vs-loss comparison for each feature column:
    |win avg - loss avg| in pooled-std-dev units, biggest gap first. Not a
    significance test - just a size-of-difference ranking so the columns
    worth a second look surface at the top instead of an alphabetical dump.
    """
    rows = []
    for col in feature_cols:
        if col not in wins_df.columns or col not in losses_df.columns:
            continue
        w = pd.to_numeric(wins_df[col], errors="coerce").dropna()
        l = pd.to_numeric(losses_df[col], errors="coerce").dropna()
        if len(w) < min_n or len(l) < min_n:
            continue
        win_mean, loss_mean = float(w.mean()), float(l.mean())
        spread = float(pd.concat([w, l]).std())
        gap_std = abs(win_mean - loss_mean) / spread if spread > 0 else 0.0
        rows.append({
            "Feature": col, "Win Avg": round(win_mean, 3), "Loss Avg": round(loss_mean, 3),
            "Gap": round(win_mean - loss_mean, 3), "Gap (in std devs)": round(gap_std, 2),
            "N (win/loss)": f"{len(w)}/{len(l)}",
        })
    if not rows:
        return pd.DataFrame(columns=["Feature", "Win Avg", "Loss Avg", "Gap", "Gap (in std devs)", "N (win/loss)"])
    return pd.DataFrame(rows).sort_values("Gap (in std devs)", ascending=False).reset_index(drop=True)


def _component_read_label(gap_std):
    """Turns a plain descriptive gap size into a suggestion, in the same
    spirit/wording as the AI System Coach's component-weight commentary
    ("weight near 1.0 -> candidate to deprioritize"). Informational only -
    never changes S1-S4 scoring; the developer decides what to do with it."""
    g = abs(gap_std)
    if g >= 0.5:
        return "Strong read — clearly separates winners from losers here"
    if g >= 0.2:
        return "Weak read — some difference, treat as secondary"
    return "No measurable difference — candidate to de-weight or drop for this strategy"


def build_fast_data_cache(tickers, start, end, max_workers=5):
    """
    First run: populate Dhan history.
    Later runs: fetch only missing ranges and read locally.
    Concurrency is bounded to respect Dhan Data API limits while avoiding
    serial per-symbol waits. Dhan documents Data APIs at 5 req/sec and
    100,000/day; this engine uses a conservative worker pool. 
    """
    if not dhan_configured():
        raise RuntimeError("Dhan credentials are not configured")
    tickers = list(dict.fromkeys(tickers))
    results, errors = {}, []

    def worker(symbol):
        try:
            update_dhan_symbol(symbol, start, end)
            con = _db()
            try:
                d = _read_cache(
                    con, str(symbol).upper().replace(".NS",""), start, end
                )
            finally:
                con.close()
            return symbol, d, None
        except Exception as e:
            return symbol, pd.DataFrame(), str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(worker, s): s for s in tickers}
        for fut in as_completed(futures):
            symbol, d, err = fut.result()
            if err:
                errors.append(f"{symbol}: {err}")
            elif not d.empty:
                results[symbol] = d

    if errors:
        _metric_set("last_dhan_errors", errors[:50])
    _metric_set("last_cache_symbols", len(results))
    return results

def _row_score(f, i, strategy, regime, safety_score):
    """
    Fast historical score from the precomputed feature matrix.
    Used by the learning/backtest engine so it doesn't rebuild features
    for every historical date.
    """
    if i < 0 or i >= len(f):
        return 0, {}
    hist = f.iloc[:i+1]
    return final_setup_score(hist, strategy, regime, safety_score)

def _fast_trade_outcome(df, entry_i, stop, target, max_bars=250):
    future = df.iloc[entry_i+1:entry_i+1+max_bars]
    if future.empty:
        return "OPEN", float(df.close.iloc[entry_i]), len(future)

    for n, (_, bar) in enumerate(future.iterrows(), start=1):
        # Conservative: if both stop and target are touched in one bar,
        # count the stop first.
        if float(bar.low) <= stop:
            return "LOSS", float(stop), n
        if float(bar.high) >= target:
            return "WIN", float(target), n
    return "OPEN", float(future.close.iloc[-1]), len(future)


# ================= PROFESSIONAL LOCAL WALK-FORWARD BACKTEST =================
# Backtesting is deliberately separated from Dhan. The backtest engine never
# calls an API. Dhan is used only by the explicit dataset-builder stage.
BT_CACHE_DIR=Path("backtest_cache")
BT_CACHE_DIR.mkdir(exist_ok=True)
BT_WARMUP_DAYS=900  # enough history for EMA250 + weekly/monthly features
BT_COST_PCT=0.23   # conservative round-trip cost assumption (%)

def _bt_required_data_start(start_date):
    return pd.Timestamp(start_date).date() - timedelta(days=BT_WARMUP_DAYS)

def _ensure_backtest_tables():
    con=_db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS backtest_runs(
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, market TEXT,
            period TEXT, start_date TEXT, end_date TEXT, threshold REAL,
            universe_size INTEGER, trades INTEGER, elapsed_seconds REAL, status TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS backtest_trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, created_at TEXT,
            ticker TEXT, strategy TEXT, signal_date TEXT, entry_date TEXT, exit_date TEXT,
            score REAL, gate85 INTEGER, outcome TEXT, entry REAL, stop REAL, target REAL,
            exit_price REAL, return_pct REAL, r_multiple REAL, pnl_pct REAL, holding_bars INTEGER,
            mfe_pct REAL, mae_pct REAL, strategy_score REAL, htf REAL, footprint REAL,
            trend REAL, entry_quality REAL, relative_strength REAL, market_regime TEXT, safety REAL,
            source TEXT
        )""")
        con.commit()
    finally:
        con.close()

_ensure_backtest_tables()

def _persist_backtest(bt, period, start_date, end_date, threshold, universe_size, elapsed, status="COMPLETED"):
    _ensure_backtest_tables()
    con=_db()
    try:
        cur=con.execute("""INSERT INTO backtest_runs(created_at,market,period,start_date,end_date,threshold,universe_size,trades,elapsed_seconds,status)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (datetime.now().isoformat(timespec="seconds"),"INDIA",period,str(start_date),str(end_date),float(threshold),int(universe_size),int(len(bt) if bt is not None else 0),float(elapsed),status))
        run_id=cur.lastrowid
        if bt is not None and not bt.empty:
            rows=[]
            for _,r in bt.iterrows():
                rows.append((run_id,datetime.now().isoformat(timespec="seconds"),str(r.get("Ticker","")),str(r.get("Strategy","")),str(r.get("Date","")),str(r.get("Entry Date",r.get("Date",""))),str(r.get("Exit Date","")),
                    float(r.get("Score",0)),int(float(r.get("Score",0))>=85),str(r.get("Outcome","")),float(r.get("Entry",np.nan)),float(r.get("SL",np.nan)),float(r.get("Target",np.nan)),float(r.get("Exit",np.nan)),float(r.get("Return %",np.nan)),float(r.get("R",np.nan)),float(r.get("Return %",np.nan)),int(r.get("Holding Bars",0)),float(r.get("MFE %",np.nan)),float(r.get("MAE %",np.nan)),float(r.get("Strategy Score",np.nan)),float(r.get("HTF",np.nan)),float(r.get("Footprint",np.nan)),float(r.get("Trend",np.nan)),float(r.get("Entry Quality",np.nan)),float(r.get("Relative Strength",np.nan)),str(r.get("Regime","")),float(r.get("Safety",np.nan)),"backtest"))
            con.executemany("""INSERT INTO backtest_trades(run_id,created_at,ticker,strategy,signal_date,entry_date,exit_date,score,gate85,outcome,entry,stop,target,exit_price,return_pct,r_multiple,pnl_pct,holding_bars,mfe_pct,mae_pct,strategy_score,htf,footprint,trend,entry_quality,relative_strength,market_regime,safety,source)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",rows)
        con.commit()
        return run_id
    finally:
        con.close()

def _load_latest_backtest():
    _ensure_backtest_tables()
    con=_db()
    try:
        run=con.execute("SELECT * FROM backtest_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        if not run:return pd.DataFrame(),None
        rid=run[0]
        bt=pd.read_sql_query("SELECT ticker AS Ticker,strategy AS Strategy,signal_date AS Date,entry_date AS \"Entry Date\",exit_date AS \"Exit Date\",score AS Score,gate85 AS \"≥85 Gate\",outcome AS Outcome,entry AS Entry,stop AS SL,target AS Target,exit_price AS Exit,return_pct AS \"Return %\",r_multiple AS R,holding_bars AS \"Holding Bars\",mfe_pct AS \"MFE %\",mae_pct AS \"MAE %\",strategy_score AS \"Strategy Score\",htf AS HTF,footprint AS Footprint,trend AS Trend,entry_quality AS \"Entry Quality\",relative_strength AS \"Relative Strength\",market_regime AS Regime,safety AS Safety FROM backtest_trades WHERE run_id=? ORDER BY score DESC",con,params=(rid,))
        return bt,run
    finally:
        con.close()

def _bt_file(symbol):
    return BT_CACHE_DIR/(str(symbol).upper().replace('.NS','').replace('/','_')+'.pkl')

def load_local_market_dataset(tickers,start_date,end_date,min_bars=160):
    """LOCAL-ONLY reader for scanner/research. Never calls Dhan."""
    out={}
    con=_db()
    try:
        for t in tickers:
            s=str(t).upper().replace(".NS","")
            d=_read_cache(con,s,start_date,end_date)
            if d is not None and len(d)>=min_bars: out[t]=d
    finally:
        con.close()
    return out


def build_local_backtest_dataset(tickers,start_date,end_date):
    """Compatibility wrapper. Never creates a second market-data cache."""
    data=load_local_market_dataset(tickers,start_date,end_date,min_bars=260)
    return len(data), [str(t).replace(".NS","") for t in tickers if t not in data]

def sync_missing_backtest_data(tickers,start_date,end_date,max_workers=5,refresh_tail_days=LATEST_SYNC_TAIL_DAYS):
    """Explicit acquisition stage only. Backtest itself never calls this.

    The tail refresh re-requests the newest already-stored days so an exchange
    revision, or a candle first written while its session was still open, is
    corrected instead of being trusted permanently.
    """
    data_start=_bt_required_data_start(start_date)
    return download_prices(tuple(tickers),data_start,end_date,max_workers=max_workers,
                           refresh_tail_days=refresh_tail_days)


def sync_latest_sessions(tickers, tail_days=LATEST_SYNC_TAIL_DAYS, max_workers=5, progress_cb=None):
    """Fast top-up of only the most recent sessions for an already-built cache.

    The full "SYNC ONLY MISSING DATA" job walks a 1000-day window for every
    symbol, which is why it was easy to skip before scanning - and skipping it
    is exactly how the scanner ended up ranking stale closes. This asks Dhan
    only for the last `tail_days` calendar days per symbol, so bringing 500
    stocks up to the latest completed session is a short job that can be run
    from the Scanner tab itself.

    Returns a summary dict; never raises for individual symbol failures.
    """
    symbols = [str(t).upper().replace(".NS", "") for t in tickers]
    symbols = list(dict.fromkeys([s for s in symbols if s]))
    if not symbols:
        return {"symbols": 0, "updated": 0, "latest": None, "errors": [], "advanced": 0}

    end = last_expected_nse_session()
    start = end - timedelta(days=int(tail_days))

    con = _db()
    try:
        qmarks = ",".join(["?"] * len(symbols))
        pre = {r[0]: r[1] for r in con.execute(
            f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol",
            symbols).fetchall()}
    finally:
        con.close()

    errors = []
    updated = 0
    workers = max(1, min(int(max_workers), 5))
    done = 0

    def worker(symbol):
        try:
            # tail refresh, so a candle stored mid-session is corrected once the
            # real close is published rather than being trusted forever.
            return symbol, update_dhan_symbol(symbol, start, end, refresh_tail_days=int(tail_days)), None
        except Exception as exc:
            return symbol, 0, str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, s) for s in symbols]
        for fut in as_completed(futures):
            symbol, saved, err = fut.result()
            if err:
                errors.append(f"{symbol}: {err}")
            elif saved:
                updated += 1
            done += 1
            if progress_cb:
                try:
                    progress_cb(done / len(symbols))
                except Exception:
                    pass

    global _DHAN_LAST_DATA_ERRORS
    if errors:
        _DHAN_LAST_DATA_ERRORS = (_DHAN_LAST_DATA_ERRORS + errors)[-100:]

    con = _db()
    try:
        post = {r[0]: r[1] for r in con.execute(
            f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol",
            symbols).fetchall()}
    finally:
        con.close()

    newest = max((v for v in post.values() if v), default=None)
    advanced = sum(1 for s in symbols if post.get(s) and pre.get(s) != post.get(s))
    if newest and advanced:
        _log_sync_freshness(newest, advanced)

    return {"symbols": len(symbols), "updated": updated, "latest": newest,
            "errors": errors[:20], "advanced": advanced,
            "no_data": len(_DHAN_LAST_NO_DATA)}


def dhan_history_floor_table():
    """Every symbol Dhan has confirmed has no candles before a given date.

    These are recently listed stocks, not broken downloads: the sync asks for
    ~1900 calendar days and their listing is more recent than that. Surfacing
    them as information rather than as red build errors is the whole point of
    the DH-907 handling in update_dhan_symbol().
    """
    con = _db()
    try:
        df = pd.read_sql_query(
            """SELECT symbol, earliest_available, probed_from, checked_at
               FROM dhan_history_floor ORDER BY earliest_available DESC, symbol""", con)
    finally:
        con.close()
    return df


def compute_and_store_sync_diagnostics(tickers):
    """For every symbol below the 260-bar backtest-readiness threshold, work
    out WHY and persist it to sync_diagnostics (upserted per symbol) so the
    Data Manager can show an actionable list instead of a silent gap.

    Distinguishes three root causes:
      - not present in the Dhan instrument master at all (symbol mismatch,
        e.g. index reconstitution renamed/added/removed a constituent)
      - a real Dhan API error recorded on the last sync attempt
      - a successful download that simply doesn't have 260 bars yet
        (e.g. a recently listed stock), or zero bars (never synced)
    Never raises: a failure to reach the instrument master itself (e.g. no
    network/credentials) is reported as a reason, not swallowed.
    """
    symbols = sorted({str(t).upper().replace(".NS", "") for t in tickers}) if tickers else []
    if not symbols:
        return pd.DataFrame(columns=["symbol", "bar_count", "reason"])

    con = _db()
    try:
        qmarks = ",".join(["?"] * len(symbols))
        rows = con.execute(
            f"SELECT symbol,COUNT(*) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol", symbols
        ).fetchall()
    finally:
        con.close()
    bar_counts = {r[0]: r[1] for r in rows}
    for s in symbols:
        bar_counts.setdefault(s, 0)

    below = [s for s in symbols if bar_counts[s] < 260]
    if not below:
        return pd.DataFrame(columns=["symbol", "bar_count", "reason"])

    mapping = None
    map_error = None
    try:
        mapping = dhan_map()
    except Exception as exc:
        map_error = str(exc)

    err_by_symbol = {}
    for e in _DHAN_LAST_DATA_ERRORS:
        if ":" in e:
            sym, msg = e.split(":", 1)
            err_by_symbol[str(sym).strip().upper().replace(".NS", "")] = msg.strip()

    # Symbols Dhan has already confirmed (DH-907) have no history before their
    # first stored candle. That is a listing date, not a fault, and it is the
    # single most common reason a Nifty-500 name sits below 260 bars.
    con = _db()
    try:
        floor_rows = con.execute(
            f"SELECT symbol,earliest_available FROM dhan_history_floor WHERE symbol IN ({qmarks})",
            symbols).fetchall()
    finally:
        con.close()
    floor_by_symbol = {r[0]: r[1] for r in floor_rows if r[1]}

    out = []
    checked_at = datetime.now().isoformat(timespec="seconds")
    for s in below:
        bc = bar_counts[s]
        if mapping is not None and s not in mapping:
            reason = "Not found in Dhan instrument master — likely a symbol mismatch (index reconstitution: addition/removal/rename)"
        elif s in floor_by_symbol and bc > 0:
            reason = (f"Dhan history begins {floor_by_symbol[s]} — nothing exists before that "
                      f"(recently listed); only {bc} bar(s) available, not an API failure")
        elif s in err_by_symbol:
            reason = f"Dhan API error on last sync: {err_by_symbol[s]}"
        elif mapping is None:
            reason = f"Could not verify Dhan instrument-master mapping ({map_error})" if map_error else "Instrument-master mapping unavailable"
        elif bc == 0:
            reason = "No candles downloaded yet — symbol not synced"
        else:
            reason = f"Only {bc} trading bar(s) available in Dhan history (likely a recently listed stock)"
        out.append({"symbol": s, "bar_count": bc, "reason": reason})

    con = _db()
    try:
        for row in out:
            con.execute(
                """INSERT INTO sync_diagnostics(symbol,checked_at,bar_count,reason)
                   VALUES(?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET checked_at=excluded.checked_at,
                       bar_count=excluded.bar_count, reason=excluded.reason""",
                (row["symbol"], checked_at, row["bar_count"], row["reason"]),
            )
        con.commit()
    finally:
        con.close()
    return pd.DataFrame(out).sort_values("bar_count").reset_index(drop=True)


def _log_sync_freshness(most_recent_date_pulled, symbols_updated):
    """One-line log entry: a sync pulled a new most-recent trading day's
    candle for at least one symbol. Lets the app owner observe, over real
    trading sessions, how soon after close Dhan's data actually becomes
    available."""
    con = _db()
    try:
        con.execute(
            "INSERT INTO sync_freshness_log(synced_at,most_recent_date_pulled,symbols_updated) VALUES(?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), str(most_recent_date_pulled), int(symbols_updated)),
        )
        con.commit()
    finally:
        con.close()


def local_backtest_status(tickers,start_date,end_date):
    """Single-batch readiness query against the persistent SQLite candle store."""
    data_start=_bt_required_data_start(start_date)
    symbols=[str(t).upper().replace(".NS","") for t in tickers]
    if not symbols:
        return pd.DataFrame(columns=["Ticker","Bars","Ready","Start","End"])
    con=_db()
    try:
        qmarks=",".join(["?"]*len(symbols))
        params=symbols+[pd.Timestamp(data_start).strftime("%Y-%m-%d"),
                        pd.Timestamp(end_date).strftime("%Y-%m-%d")]
        q=pd.read_sql_query(
            f"""SELECT symbol,COUNT(*) AS Bars,MIN(dt) AS Start,MAX(dt) AS End
                FROM candles
                WHERE symbol IN ({qmarks}) AND dt>=? AND dt<=?
                GROUP BY symbol""",
            con,params=params
        )
    finally:
        con.close()
    by={str(r.symbol).upper():r for r in q.itertuples()}
    rows=[]
    for t,s in zip(tickers,symbols):
        r=by.get(s)
        n=int(r.Bars) if r is not None else 0
        rows.append({
            "Ticker":str(t).replace(".NS",""),
            "Bars":n,
            "Ready":bool(n>=260),
            "Start":pd.to_datetime(r.Start).date() if r is not None else None,
            "End":pd.to_datetime(r.End).date() if r is not None else None
        })
    return pd.DataFrame(rows)

def load_local_backtest_data(tickers,start_date,end_date):
    """Direct, batch SQLite read. Backtest never uses a second market-data cache."""
    data_start=_bt_required_data_start(start_date)
    symbols=[str(t).upper().replace(".NS","") for t in tickers]
    if not symbols:return {}
    con=_db()
    try:
        qmarks=",".join(["?"]*len(symbols))
        q=pd.read_sql_query(
            f"""SELECT symbol,dt,open,high,low,close,volume FROM candles
                WHERE symbol IN ({qmarks}) AND dt>=? AND dt<=?
                ORDER BY symbol,dt""",
            con,params=symbols+[pd.Timestamp(data_start).strftime("%Y-%m-%d"),
                                pd.Timestamp(end_date).strftime("%Y-%m-%d")]
        )
    finally:con.close()
    out={}
    if q.empty:return out
    for s,g in q.groupby("symbol",sort=False):
        d=g.drop(columns=["symbol"]).copy(); d.dt=pd.to_datetime(d.dt); d=d.set_index("dt"); d.index.name="date"
        if len(d)>=260:
            original=next((t for t in tickers if str(t).upper().replace(".NS","")==str(s).upper()),s)
            out[original]=d
    return out

def _professional_bt(data,strategies,threshold,start_date,end_date):
    """Local-only walk-forward replay with rich learning fields."""
    rows=[];start=pd.Timestamp(start_date);end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if len(df)<260:continue
        try:
            df=df.sort_index();f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty:continue
            avg_value,abnormal=_safety_fast_series(df)
            for s in strategies:
                sig=strategy_signal(f,s).fillna(False).to_numpy()
                for i in np.flatnonzero(sig):
                    dt=pd.Timestamp(f.index[i])
                    if dt<start or dt>end or i>=len(df)-1:continue
                    regime,_=_regime_from_row(f,i)
                    safe,_,_=_safety_from_row(avg_value,abnormal,i)
                    score,parts=_row_score(f,i,s,regime,safe)
                    if score<int(threshold):continue
                    entry_i=i+1; entry=float(df.close.iloc[entry_i])
                    if not np.isfinite(entry) or entry<=0:continue
                    stop=entry*.93;target=entry+3*(entry-stop);risk=entry-stop
                    last=min(len(df)-1,entry_i+60);outcome='TIMEOUT';exit_price=float(df.close.iloc[last]);held=last-entry_i
                    max_high=entry;min_low=entry
                    for j in range(entry_i,last+1):
                        bar=df.iloc[j];max_high=max(max_high,float(bar.high));min_low=min(min_low,float(bar.low))
                        if bar.low<=stop:
                            outcome='LOSS';exit_price=stop;held=j-entry_i;break
                        if bar.high>=target:
                            outcome='WIN';exit_price=target;held=j-entry_i;break
                    gross_pct=(exit_price/entry-1)*100
                    return_pct=gross_pct-BT_COST_PCT
                    r_mult=return_pct/((risk/entry)*100) if risk>0 else 0
                    mfe=(max_high/entry-1)*100;mae=(min_low/entry-1)*100
                    rows.append({
                        'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),'Strategy':f'S{s}',
                        'Entry Date':df.index[entry_i].date(),'Exit Date':df.index[entry_i+held].date(),
                        'Score':int(score),'≥85 Gate':bool(score>=85),'Entry':round(entry,2),'SL':round(stop,2),'Target':round(target,2),
                        'Exit':round(exit_price,2),'Outcome':outcome,'Return %':round(return_pct,2),'R':round(float(r_mult),2),
                        'Holding Bars':int(held),'MFE %':round(mfe,2),'MAE %':round(mae,2),
                        'Strategy Score':parts.get('Strategy',0),'HTF':parts.get('HTF Demand',0),'Footprint':parts.get('Footprint',0),
                        'Trend':parts.get('Trend',0),'Entry Quality':parts.get('Entry Quality',0),'Relative Strength':parts.get('Relative Strength',0),
                        'Regime':regime,'Safety':safe
                    })
        except Exception:
            continue
    return pd.DataFrame(rows)

def _custom_strategy_backtest(data,conditions,start_date,end_date,sl_pct=0.07,target_r=3.0,threshold=0):
    """Local-only walk-forward replay of a validated Custom Strategy DSL rule
    set. Same architecture/columns as _professional_bt (S1-S4) so the result
    feeds _learn_from_backtest() unmodified, tagged strategy='CUSTOM'."""
    rows=[];start=pd.Timestamp(start_date);end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if len(df)<260:continue
        try:
            df=df.sort_index();f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty:continue
            avg_value,abnormal=_safety_fast_series(df)
            sig=custom_strategy_signal(f,conditions).fillna(False).to_numpy()
            for i in np.flatnonzero(sig):
                dt=pd.Timestamp(f.index[i])
                if dt<start or dt>end or i>=len(df)-1:continue
                regime,_=_regime_from_row(f,i)
                safe,_,_=_safety_from_row(avg_value,abnormal,i)
                score,parts=_row_score(f,i,"CUSTOM",regime,safe)
                if score<int(threshold):continue
                entry_i=i+1; entry=float(df.close.iloc[entry_i])
                if not np.isfinite(entry) or entry<=0:continue
                stop=entry*(1-sl_pct);target=entry+target_r*(entry-stop);risk=entry-stop
                last=min(len(df)-1,entry_i+60);outcome='TIMEOUT';exit_price=float(df.close.iloc[last]);held=last-entry_i
                max_high=entry;min_low=entry
                for j in range(entry_i,last+1):
                    bar=df.iloc[j];max_high=max(max_high,float(bar.high));min_low=min(min_low,float(bar.low))
                    if bar.low<=stop:
                        outcome='LOSS';exit_price=stop;held=j-entry_i;break
                    if bar.high>=target:
                        outcome='WIN';exit_price=target;held=j-entry_i;break
                gross_pct=(exit_price/entry-1)*100
                return_pct=gross_pct-BT_COST_PCT
                r_mult=return_pct/((risk/entry)*100) if risk>0 else 0
                mfe=(max_high/entry-1)*100;mae=(min_low/entry-1)*100
                rows.append({
                    'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),'Strategy':'CUSTOM',
                    'Entry Date':df.index[entry_i].date(),'Exit Date':df.index[entry_i+held].date(),
                    'Score':int(score),'≥85 Gate':bool(score>=85),'Entry':round(entry,2),'SL':round(stop,2),'Target':round(target,2),
                    'Exit':round(exit_price,2),'Outcome':outcome,'Return %':round(return_pct,2),'R':round(float(r_mult),2),
                    'Holding Bars':int(held),'MFE %':round(mfe,2),'MAE %':round(mae,2),
                    'Strategy Score':parts.get('Strategy',0),'HTF':parts.get('HTF Demand',0),'Footprint':parts.get('Footprint',0),
                    'Trend':parts.get('Trend',0),'Entry Quality':parts.get('Entry Quality',0),'Relative Strength':parts.get('Relative Strength',0),
                    'Regime':regime,'Safety':safe
                })
        except Exception:
            continue
    return pd.DataFrame(rows)

def run_local_backtest(tickers,start_date,end_date,threshold=85):
    # HARD GUARANTEE: this function contains no Dhan/data-download call.
    # It runs on whatever LOCAL historical data is currently available.
    # Missing symbols are reported by the UI and never trigger a Dhan request.
    status=local_backtest_status(tickers,start_date,end_date)
    if status.empty:
        raise RuntimeError('NO_LOCAL_DATA')
    data=load_local_backtest_data(tickers,start_date,end_date)
    if not data:
        raise RuntimeError('NO_LOCAL_DATA')
    return _professional_bt(data,[1,2,3,4],threshold,start_date,end_date)

def _bt_period(period):
    days={'6 Months':183,'1 Year':365,'2 Years':730,'3 Years':1095}
    end=last_expected_nse_session(); return end-timedelta(days=days[period]),end

def _fast_score_learning_backtest(data, strategies, threshold=85):
    rows = []
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=2)

    for ticker, df in data.items():
        if df is None or len(df) < 320:
            continue
        try:
            df = df.sort_index()
            f = features_fast(str(ticker), df)
            if f.empty:
                continue

            # Market regime is evaluated once at each candidate using only data
            # known up to the candidate date. To keep execution sharp, use an
            # O(1) lookup on the already-computed feature frame instead of
            # recomputing features()/safety() from scratch per signal.
            avg_value, abnormal = _safety_fast_series(df)
            for s in strategies:
                sig = strategy_signal(f, s).fillna(False).to_numpy()
                idxs = np.flatnonzero(sig)

                for i in idxs:
                    dt = pd.Timestamp(f.index[i])
                    if dt < start or i >= len(f)-1:
                        continue

                    regime, _ = _regime_from_row(f, i)
                    safe, _, _ = _safety_from_row(avg_value, abnormal, i)
                    score, parts = _row_score(f, i, s, regime, safe)

                    # IMPORTANT: keep every complete-rule historical signal for learning.
                    # The threshold is a forward-test gate/ranking filter, not a historical
                    # data filter. This prevents survivorship-by-score in our research set.
                    entry_i = i + 1
                    entry = float(df.close.iloc[entry_i])
                    stop = entry * 0.93
                    target = entry + 3 * (entry-stop)

                    outcome, exit_price, holding = _fast_trade_outcome(
                        df, entry_i, stop, target
                    )
                    result_r = (exit_price-entry) / (entry-stop)

                    rows.append({
                        "Date": dt.date(),
                        "Ticker": str(ticker).replace(".NS",""),
                        "Strategy": f"S{s}",
                        "Score": score,
                        "≥85 Gate": bool(score >= threshold),
                        "Entry": round(entry,2),
                        "SL": round(stop,2),
                        "Target": round(target,2),
                        "Outcome": outcome,
                        "R": round(float(result_r),2),
                        "Holding Bars": holding,
                        "Strategy Score": parts["Strategy"],
                        "HTF": parts["HTF Demand"],
                        "Footprint": parts["Footprint"],
                        "Entry Quality": parts["Entry Quality"],
                        "Relative Strength": parts["Relative Strength"],
                        "Regime": regime,
                        "Safety": safe
                    })
        except Exception:
            continue

    return pd.DataFrame(rows)

def _learn_from_backtest(bt):
    """Persist completed backtest observations for long-term learning."""
    if bt is None or bt.empty:return 0
    ensure_learning_tables();n=0;con=_db()
    try:
        for _,r in bt.iterrows():
            try:
                before=con.total_changes
                con.execute("""INSERT INTO learning_observations(
                    created_at,market,symbol,strategy,signal_time,score,regime,htf,footprint,
                    strategy_score,entry_quality,relative_strength,safety_score,entry,exit_price,
                    result_r,outcome,holding_minutes,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    datetime.now().isoformat(timespec='seconds'),'INDIA',str(r.get('Ticker','')),str(r.get('Strategy','')),
                    str(r.get('Date','')),float(r.get('Score',np.nan)),str(r.get('Regime','')),float(r.get('HTF',np.nan)),
                    float(r.get('Footprint',np.nan)),float(r.get('Strategy Score',np.nan)),float(r.get('Entry Quality',np.nan)),
                    float(r.get('Relative Strength',np.nan)),float(r.get('Safety',np.nan)),float(r.get('Entry',np.nan)),
                    float(r.get('Exit',np.nan)),float(r.get('R',np.nan)),str(r.get('Outcome','')),
                    float(r.get('Holding Bars',0))*390.0,'backtest'))
                n += 1 if con.total_changes>before else 0
            except Exception:continue
        con.commit()
    finally:con.close()
    if n:
        maybe_backup_db()
    return n

def adaptive_edge_table(market="INDIA"):
    q = learning_snapshot(market)
    if q.empty:
        return pd.DataFrame()

    # Empirical-Bayes style shrinkage toward 50% / 0R for small samples.
    rows = []
    for (strategy, band), g in q.assign(
        ScoreBand=pd.cut(
            q.score, bins=[-np.inf,84,89,94,np.inf],
            labels=["<85","85-89","90-94","95-100"]
        )
    ).groupby(["strategy","ScoreBand"], observed=True):
        n = len(g)
        wins = int((g.result_r > 0).sum())
        alpha, beta = 2.0, 2.0
        shrunk_win = (wins + alpha) / (n + alpha + beta)
        shrink_r = (g.result_r.mean() * n) / max(n + 10, 1)
        rows.append({
            "Strategy": strategy,
            "Score Band": str(band),
            "Samples": n,
            "Win % (shrunk)": round(shrunk_win*100,1),
            "Avg R (shrunk)": round(shrink_r,3)
        })
    return pd.DataFrame(rows).sort_values(
        ["Strategy","Score Band"]
    )

def current_candidate_edge(market, strategy, score):
    q = adaptive_edge_table(market)
    if q.empty:
        return 0.0, "NO LEARNING DATA"

    band = "85-89" if 85 <= score <= 89 else "90-94" if score <= 94 else "95-100" if score >= 95 else "<85"
    row = q[(q.Strategy == strategy) & (q["Score Band"] == band)]
    if row.empty or int(row.iloc[0]["Samples"]) < 20:
        return 0.0, "INSUFFICIENT SAMPLE"
    r = float(row.iloc[0]["Avg R (shrunk)"])
    conf = "HIGH" if int(row.iloc[0]["Samples"]) >= 100 else "MEDIUM"
    return r, conf

def fallback_win_probability(market, strategy, score):
    """Score-band historical win rate (adaptive_edge_table), used as the
    Win Probability % estimate whenever the ML classifier isn't trained yet."""
    q = adaptive_edge_table(market)
    if q.empty:
        return np.nan
    band = "85-89" if 85 <= score <= 89 else "90-94" if score <= 94 else "95-100" if score >= 95 else "<85"
    row = q[(q.Strategy == strategy) & (q["Score Band"] == band)]
    if row.empty or int(row.iloc[0]["Samples"]) < 20:
        return np.nan
    return float(row.iloc[0]["Win % (shrunk)"])


# ========================= AI SYSTEM COACH (LLM) — Phase 6 =========================
# On-demand LLM analysis of the marking system as a WHOLE (backtest performance,
# forward-test resolution, component correlations, adaptive edge table) — not one
# trade. Distinct from the existing rule-based "🎓 Strategy Coach" tab (decision-tree/
# regime-breakdown, no LLM call); this one is titled "AI System Coach (LLM)" in the
# UI specifically to avoid confusion between the two.
#
# COST CONTROL: one batched API call per run, sending only AGGREGATED stats (never
# raw trade rows) — small payload regardless of how many trades exist. Runs only on
# a button click, never automatically on every scan.
#
# Model note: the original design called for "claude-sonnet-4-6" (a real, valid,
# one-generation-behind model). Using "claude-sonnet-5" instead — the current model
# in the same mid-cost "Sonnet" tier the design intended (not the upmarket "Opus"
# tier), and cheaper per-token than 4.6.

ANTHROPIC_COACH_MODEL = "claude-sonnet-5"


def _anthropic_configured():
    # Mirrors twelvedata_configured()/_github_configured()'s established
    # pattern in this file: st.secrets.__contains__ raises
    # StreamlitSecretNotFoundError (not just a missing-key False) when no
    # secrets.toml exists at all - a bare `"X" not in st.secrets`/`st.secrets[...]`
    # crashes the whole app in that state, so every access here goes through
    # a try/except, never a bare lookup.
    try:
        return bool(_secret("ANTHROPIC_API_KEY"))
    except Exception:
        return False


def _anthropic_key():
    try:
        return _secret("ANTHROPIC_API_KEY")
    except Exception:
        return None


def _table_exists(con, name):
    r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return r is not None


def ensure_coach_table():
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS coach_reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            total_backtest_trades INTEGER,
            total_forward_closed INTEGER,
            report_text TEXT,
            verdict TEXT
        )""")
        con.commit()
    finally:
        con.close()

ensure_coach_table()


def build_coach_payload():
    """Compiles a compact JSON-able summary of everything the Coach needs:
    edge table, component weights, backtest performance, forward-test
    resolution stats (including fundamental/SMC strategies if present).
    Returns (payload:dict, has_enough_data:bool).
    """
    payload = {}

    # --- Backtest performance per strategy ---
    con = _db()
    try:
        bt_summary = pd.read_sql_query(
            "SELECT * FROM backtest_trades", con
        ) if _table_exists(con, "backtest_trades") else pd.DataFrame()
    except Exception:
        bt_summary = pd.DataFrame()
    finally:
        con.close()

    # NOTE: backtest_trades is the RAW sqlite table (lowercase columns:
    # strategy, r_multiple) - not the "Strategy"/"R" display-renamed columns
    # used elsewhere in the UI. The original patch draft checked for
    # "Strategy" here, which never matches this table and would have silently
    # produced an empty backtest_performance every single run.
    if not bt_summary.empty and "strategy" in bt_summary.columns:
        perf_rows = []
        for strat, g in bt_summary.groupby("strategy"):
            has_r = "r_multiple" in g.columns
            perf_rows.append({
                "strategy": strat, "trades": len(g),
                "win_pct": round(float((g.r_multiple > 0).mean() * 100), 1) if has_r else None,
                "avg_r": round(float(g.r_multiple.mean()), 3) if has_r else None,
            })
        payload["backtest_performance"] = perf_rows
    else:
        payload["backtest_performance"] = []

    # --- Adaptive edge table (score-band level win%/avg R) ---
    edge = adaptive_edge_table("INDIA")
    payload["edge_by_score_band"] = edge.to_dict(orient="records") if not edge.empty else []

    # --- Component-level correlation with R ---
    comp = adaptive_component_weights("INDIA")
    payload["component_weights"] = comp.to_dict(orient="records") if not comp.empty else []

    # --- Forward test resolution (the real-world check) ---
    con = _db()
    try:
        ft = pd.read_sql_query("SELECT * FROM forward_tests", con)
    finally:
        con.close()

    closed = ft[ft.status.isin(["CLOSED", "TARGET", "STOP", "EXIT", "EXPIRED"])] if not ft.empty else pd.DataFrame()
    active = ft[ft.status == "ACTIVE"] if not ft.empty else pd.DataFrame()

    fwd_rows = []
    if not closed.empty:
        for strat, g in closed.groupby("strategy"):
            fwd_rows.append({
                "strategy": strat, "closed_trades": len(g),
                "win_pct": round(float((g.result_r > 0).mean() * 100), 1) if g.result_r.notna().any() else None,
                "avg_r": round(float(g.result_r.dropna().mean()), 3) if g.result_r.notna().any() else None,
            })
    payload["forward_test_closed"] = fwd_rows
    payload["forward_test_active_count"] = int(len(active))
    payload["forward_test_closed_count"] = int(len(closed))

    total_bt = len(bt_summary)
    total_fwd_closed = len(closed)
    has_enough = total_bt >= 20 or total_fwd_closed >= 10

    payload["totals"] = {"backtest_trades": total_bt, "forward_closed": total_fwd_closed}
    return payload, has_enough


def run_strategy_coach():
    """Sends the aggregated payload to Claude, gets back a written analysis.
    Returns (report_text:str, error:str or None).
    """
    if not _anthropic_configured():
        return None, "ANTHROPIC_API_KEY not set in Streamlit secrets."

    payload, has_enough = build_coach_payload()
    if not has_enough:
        return None, (
            f"Not enough data yet for a reliable analysis "
            f"({payload['totals']['backtest_trades']} backtest trades, "
            f"{payload['totals']['forward_closed']} closed forward tests). "
            f"Run more backtests or let more forward tests resolve first."
        )

    system_prompt = """You are a quantitative trading systems analyst reviewing a solo trader's
algorithmic research framework. You will receive aggregated statistics (NOT raw trade data) about:
- backtest_performance: win rate / avg R per strategy (S1-S4 = stock strategies, FUNDA/FUNDB =
  fundamental screens, FX_SMC = forex/crypto price action strategy)
- edge_by_score_band: empirical win rate and avg R-multiple by setup-score band, per strategy
  (uses Bayesian shrinkage toward 50%/0R for small samples already)
- component_weights: whether each scoring component (HTF, Footprint, Entry Quality, Relative
  Strength, Safety) shows a real difference in outcome between its high vs low values
- forward_test_closed / forward_test_active_count: REAL live-market outcomes, the most
  trustworthy signal since it isn't backtest-fitted

Your job: give an honest, statistically grounded verdict on whether the marking/scoring system
is working, and concrete recommendations to improve accuracy. Rules:
1. ALWAYS state sample sizes next to any claim. Never treat n<20 as reliable evidence.
2. If backtest and forward-test results diverge meaningfully, flag this explicitly — it usually
   means curve-fitting or regime drift, and is the single most important thing to surface.
3. For components with weight near 1.0 and high sample size, say plainly that they show no
   measurable edge and are candidates to deprioritize or drop from scoring.
4. Do not recommend specific numeric parameter changes unless the sample size genuinely
   supports it — say "not enough data yet" rather than guessing.
5. Structure your response with these headers: OVERALL VERDICT, WHAT'S WORKING, WHAT'S NOT
   WORKING, SPECIFIC RECOMMENDATIONS (numbered, priority order), CONFIDENCE CAVEATS.
6. Keep it concise and actionable — this is read by the developer, not published.
"""

    user_content = "Here is the current aggregated system data:\n\n" + json.dumps(payload, indent=2, default=str)

    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        report = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not report:
            return None, "Claude API returned an empty response."
        return report, None
    except anthropic.AuthenticationError as e:
        return None, f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return None, f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return None, f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return None, f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def save_coach_report(report_text):
    payload, _ = build_coach_payload()
    verdict_line = ""
    lines = report_text.splitlines()
    for idx, line in enumerate(lines):
        if "OVERALL VERDICT" in line.upper():
            rest = lines[idx+1:idx+3]
            verdict_line = " ".join(rest).strip()[:300]
            break
    con = _db()
    try:
        con.execute(
            """INSERT INTO coach_reports(created_at, total_backtest_trades, total_forward_closed, report_text, verdict)
               VALUES(?,?,?,?,?)""",
            (datetime.now().isoformat(timespec="seconds"),
             payload["totals"]["backtest_trades"], payload["totals"]["forward_closed"],
             report_text, verdict_line)
        )
        con.commit()
    finally:
        con.close()


# ========================= 5-AGENT AI TRADE DEBATE PANEL — Phase 8 =========================
# Analyzes individual TRADE CANDIDATES from the scanner's forward-test queue (different
# job from the AI System Coach above, which analyzes the whole system). Meant to run
# after a scan, on the filtered shortlist that already qualifies for forward testing,
# before capital is committed.
#
# COST CONTROL: NOT 5 agents x N candidates. Four agents each get ALL shortlisted
# candidates in ONE message, returning a JSON array of verdicts; the Judge gets all
# four verdict-arrays plus the original data in one final call. Total = 5 API calls
# per panel run regardless of shortlist size (capped at 15 candidates below).
#
# JSON ROBUSTNESS: the installed anthropic SDK (checked in this environment, not
# guessed) exposes `output_config={"format": {"type": "json_schema", "schema": ...}}`
# on messages.create() (see anthropic.types.output_config_param /
# json_output_format_param), so every agent call below constrains its response to a
# JSON array matching an explicit schema. Fence-stripping + json.loads() is still kept
# as a defensive second layer (harmless when the schema already produced clean JSON,
# a real safety net if some future SDK/account combination doesn't honor the schema) -
# no live-credentialed run of this exact call has been possible in this sandbox, so
# both layers stay in rather than betting everything on the unverified end-to-end path.

_AGENT_VERDICT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "verdict": {"type": "string"},
            "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "flag": {"type": "boolean"},
        },
        "required": ["ticker", "verdict", "confidence", "flag"],
        "additionalProperties": False,
    },
}

_JUDGE_VERDICT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "rank": {"type": "integer"},
            "reasoning": {"type": "string"},
            "overall_confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        },
        "required": ["ticker", "rank", "reasoning", "overall_confidence"],
        "additionalProperties": False,
    },
}


def build_debate_shortlist(scan_result_df, max_candidates=15):
    """Filters scan results down to a cost-bounded shortlist: drops
    INSUFFICIENT SAMPLE learning confidence when better options exist,
    sorts by Learned Rank, caps at max_candidates.
    """
    if scan_result_df is None or scan_result_df.empty:
        return pd.DataFrame()

    df = scan_result_df.copy()
    good_conf = df[df.get("Learning Confidence", "") != "INSUFFICIENT SAMPLE"]
    pool = good_conf if len(good_conf) >= 3 else df  # fallback if too few confident ones

    sort_col = "Learned Rank" if "Learned Rank" in pool.columns else "Score"
    return pool.sort_values(sort_col, ascending=False).head(max_candidates).reset_index(drop=True)


def _candidates_to_payload(shortlist_df):
    cols = ["Ticker", "Strategy", "Score", "Adaptive Score", "Learned Rank", "Historical Edge R",
            "Learning Confidence", "Entry", "SL 7%", "Target 3R", "RSI", "RelVol",
            "HTF Score", "Footprint Score", "Entry Quality", "Relative Strength",
            "Safety Score", "Safety Flags", "Regime"]
    available = [c for c in cols if c in shortlist_df.columns]
    return shortlist_df[available].to_dict(orient="records")


def _call_agent(system_prompt, candidates_payload, max_tokens=2500):
    """Sends one candidates_payload (list of dicts) to Claude with the given
    system_prompt, expecting back a JSON array of {ticker, verdict,
    confidence, flag} objects — one per candidate. Returns (list, error).
    """
    if not _anthropic_configured():
        return [], "ANTHROPIC_API_KEY not set in Streamlit secrets."

    user_content = (
        "Analyze EVERY candidate below and return a JSON array, one object per "
        "candidate, each with exactly these keys: \"ticker\", \"verdict\" (2-3 "
        "sentences), \"confidence\" (LOW/MEDIUM/HIGH), \"flag\" (true if this is a "
        "serious concern, false otherwise).\n\n"
        + json.dumps(candidates_payload, indent=2, default=str)
    )
    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _AGENT_VERDICT_SCHEMA}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return [], "Agent did not return a JSON array."
        return parsed, None
    except json.JSONDecodeError as e:
        return [], f"Could not parse agent response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return [], f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return [], f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return [], f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return [], f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"


def agent_technical_analyst(candidates_payload):
    system = """You are a Technical Analyst reviewing deterministic strategy setups from an
Indian equities trading system. Each candidate already PASSED all mandatory rules of its
strategy (S1-S4) — your job is not to re-qualify them, but to assess RELATIVE setup quality
using the component scores provided: HTF Score (higher-timeframe demand), Footprint Score,
Entry Quality, Relative Strength, RSI, RelVol. Identify which candidates have genuinely clean,
well-supported setups versus which merely cleared the minimum bar. Be specific about which
component(s) drive your view for each candidate."""
    return _call_agent(system, candidates_payload)


def agent_statistical_skeptic(candidates_payload):
    system = """You are a Statistical Skeptic reviewing trade candidates from a system that
tracks empirical win rates with Bayesian shrinkage. Each candidate includes: Score, Learned
Rank (blends score + historical edge), Historical Edge R (shrunk average R-multiple for this
strategy/score-band), and Learning Confidence (HIGH = 100+ samples, MEDIUM = 20-99, INSUFFICIENT
SAMPLE = under 20). Your ONLY job: flag any candidate whose apparent edge you don't trust yet
due to small sample size, and separately note any candidate where the historical edge is both
strong AND well-sampled (genuinely trustworthy). Be blunt about which numbers are noise."""
    return _call_agent(system, candidates_payload)


def agent_risk_capital(candidates_payload, capital=None, max_slots=None, risk_pct=None):
    context = ""
    if capital and max_slots:
        context = (f"\n\nTrader's context: total capital ₹{capital:,.0f}, max {max_slots} "
                    f"concurrent positions, risking {risk_pct or 1.0}% of capital per trade. "
                    f"Each candidate's SL 7% and Target 3R fields define its risk unit.")
    system = ("""You are a Risk & Capital Agent. Given a trader's available capital and maximum
concurrent position count, assess whether taking ALL of these candidates together would create
excessive concentration — same sector, correlated stocks, or too many positions for the stated
capital to size properly. Flag any candidate that should be deprioritized purely for portfolio
construction reasons, even if its setup looks technically fine on its own."""
              + context)
    return _call_agent(system, candidates_payload)


def agent_devils_advocate(candidates_payload):
    system = """You are the Devil's Advocate / Bear Case agent. Your job is to argue AGAINST
each candidate, specifically — not generic caution, but the single most likely way this specific
setup fails: regime risk, crowded trade, weak relative strength despite a passing score, thin
liquidity (low RelVol), safety flags present, or anything else in the data that a purely bullish
read would gloss over. If a candidate genuinely has no strong bear case, say so plainly rather
than inventing one — false negatives here are as costly as missed risks."""
    return _call_agent(system, candidates_payload)


def agent_judge(candidates_payload, tech_verdicts, skeptic_verdicts, risk_verdicts, bear_verdicts, target_count=5):
    if not _anthropic_configured():
        return [], "ANTHROPIC_API_KEY not set in Streamlit secrets."

    system = f"""You are the Judge/Synthesizer. You will receive the original candidate data plus
four independent agent verdicts per candidate: Technical Analyst, Statistical Skeptic, Risk/Capital
Agent, and Devil's Advocate. Resolve disagreements using judgment, weighting the Statistical
Skeptic's confidence flags heavily (don't rank a candidate highly if its edge is statistically
unreliable, regardless of how clean the setup looks technically). Output a JSON array of the TOP
{target_count} candidates (fewer if fewer than {target_count} are genuinely defensible — never pad
the list with weak picks), each object with keys: "ticker", "rank" (1 = best), "reasoning" (2-3
sentences synthesizing the four views), "overall_confidence" (LOW/MEDIUM/HIGH)."""

    user_content = json.dumps({
        "candidates": candidates_payload,
        "technical_analyst_verdicts": tech_verdicts,
        "statistical_skeptic_verdicts": skeptic_verdicts,
        "risk_capital_verdicts": risk_verdicts,
        "devils_advocate_verdicts": bear_verdicts,
    }, indent=2, default=str)

    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _JUDGE_VERDICT_SCHEMA}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return [], "Judge did not return a JSON array."
        return parsed, None
    except json.JSONDecodeError as e:
        return [], f"Could not parse Judge response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return [], f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return [], f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return [], f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return [], f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"


def run_trade_debate_panel(scan_result_df, capital=None, max_slots=None, risk_pct=None, target_count=5, max_candidates=15):
    """Full pipeline: shortlist -> 4 parallel-in-spirit agent calls -> Judge.
    Returns dict with keys: shortlist_df, tech, skeptic, risk, bear (each a
    list of verdict dicts), final (Judge's ranked list), errors (list of any
    agent errors encountered — non-fatal, panel continues with what it has).
    """
    shortlist = build_debate_shortlist(scan_result_df, max_candidates=max_candidates)
    if shortlist.empty:
        return {"error": "No candidates available to analyze. Run a scan first."}

    payload = _candidates_to_payload(shortlist)
    errors = []

    tech, e1 = agent_technical_analyst(payload)
    if e1: errors.append(f"Technical Analyst: {e1}")

    skeptic, e2 = agent_statistical_skeptic(payload)
    if e2: errors.append(f"Statistical Skeptic: {e2}")

    risk, e3 = agent_risk_capital(payload, capital, max_slots, risk_pct)
    if e3: errors.append(f"Risk/Capital Agent: {e3}")

    bear, e4 = agent_devils_advocate(payload)
    if e4: errors.append(f"Devil's Advocate: {e4}")

    final, e5 = agent_judge(payload, tech, skeptic, risk, bear, target_count=target_count)
    if e5: errors.append(f"Judge: {e5}")

    return {
        "shortlist_df": shortlist,
        "tech": tech, "skeptic": skeptic, "risk": risk, "bear": bear,
        "final": final, "errors": errors,
    }


# ========================= 5-AGENT SYSTEM LEARNING PANEL =========================
# A THIRD, distinct thing from both the rule-based "🎓 Strategy Coach" tab (decision-tree
# extraction, no LLM) and the single-bot "🧑‍🏫 AI System Coach (LLM)" section above (Phase 6,
# one written analysis). This panel reuses Phase 6/8's exact SDK/model/structured-output
# pattern but analyzes the WHOLE SYSTEM (not individual trade candidates like Phase 8, and
# not with a single bot like Phase 6) with 5 specialized agents whose disagreements are
# meant to surface, synthesized by a Judge at the end.
#
# UNLIKE PHASE 8: there is no per-candidate list to batch over here - this is ONE
# system-wide aggregated payload, so each of the 4 analysts gets ONE message and returns
# ONE structured finding object (not a JSON array). _call_learning_panel_agent() below is
# _call_agent()'s pattern adapted for an object response instead of an array.
#
# COST CONTROL: exactly 5 API calls per run (4 analysts + 1 Judge), same as Phase 8's total,
# regardless of how much underlying data exists - only aggregated stats are sent.
#
# DATA SOURCES (all reused, none recomputed from scratch):
#   (a) build_coach_payload() - the exact same payload the single-bot AI System Coach uses.
#   (b) the winners-vs-losers/marking-read data (_feature_gap_table/RAW_SIGNAL_NUMERIC_FEATURES/
#       RAW_SIGNAL_SCORE_COMPONENTS), computed here from a raw_signal_result DataFrame the
#       caller passes in (the UI passes st.session_state.get("raw_signal_result") - kept out
#       of this function's signature so it stays plain-Python testable without a Streamlit
#       context). Absent/too-small data is reported in the payload, never treated as failure.
#   (c) Part A's sl_calibration_results table, queried directly here.

_LEARNING_PANEL_FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "finding": {"type": "string"},
        "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "evidence_summary": {"type": "string"},
    },
    "required": ["finding", "confidence", "evidence_summary"],
    "additionalProperties": False,
}

_LEARNING_PANEL_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                    "recommendation": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["priority", "recommendation", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["recommendations"],
    "additionalProperties": False,
}


def build_learning_panel_payload(raw_signal_result=None):
    """Aggregates everything the System Learning Panel needs into one JSON-able
    payload. Returns (payload:dict, has_enough_data:bool) - same convention as
    build_coach_payload(), which this reuses rather than recomputing.

    raw_signal_result: the Raw Strategy Learning DataFrame (st.session_state
    ["raw_signal_result"] in the UI), or None/empty if that section hasn't been
    run yet - handled gracefully, never raises.
    """
    coach_payload, coach_has_enough = build_coach_payload()
    payload = {"system": coach_payload}

    # --- (b) Winners-vs-losers marking-read, if Raw Signal Capture has been run ---
    if raw_signal_result is not None and not raw_signal_result.empty:
        wl = raw_signal_result[raw_signal_result["outcome"].isin(["WIN", "LOSS"])]
        wins_df = wl[wl["outcome"] == "WIN"]
        losses_df = wl[wl["outcome"] == "LOSS"]
        if len(wins_df) >= 10 and len(losses_df) >= 10:
            overall_gap = _feature_gap_table(wins_df, losses_df, RAW_SIGNAL_NUMERIC_FEATURES)
            per_strategy = {}
            for strat in sorted(wl["strategy"].dropna().unique()):
                s_wins = wins_df[wins_df["strategy"] == strat]
                s_losses = losses_df[losses_df["strategy"] == strat]
                if len(s_wins) >= 10 and len(s_losses) >= 10:
                    comp_df = _feature_gap_table(s_wins, s_losses, RAW_SIGNAL_SCORE_COMPONENTS, min_n=5)
                    per_strategy[str(strat)] = comp_df.to_dict(orient="records")
            payload["marking_read"] = {
                "available": True,
                "wins": int(len(wins_df)), "losses": int(len(losses_df)),
                "overall_feature_gaps": overall_gap.to_dict(orient="records"),
                "per_strategy_component_gaps": per_strategy,
            }
        else:
            payload["marking_read"] = {
                "available": False,
                "reason": f"Only {len(wins_df)} win(s)/{len(losses_df)} loss(es) captured so far — "
                          f"need at least ~10 of each before a winners-vs-losers read means anything.",
            }
    else:
        payload["marking_read"] = {
            "available": False,
            "reason": "Raw Signal Capture has not been run yet in this session — no winners-vs-losers marking-read data available.",
        }

    # --- (c) Part A: SL calibration evidence, queried directly ---
    con = _db()
    try:
        sl_cal = pd.read_sql_query(
            "SELECT strategy, market_regime, scheme, trades, win_pct, avg_r, avg_holding_bars FROM sl_calibration_results",
            con,
        ) if _table_exists(con, "sl_calibration_results") else pd.DataFrame()
    except Exception:
        sl_cal = pd.DataFrame()
    finally:
        con.close()

    if not sl_cal.empty:
        sl_cal = sl_cal.copy()
        sl_cal["reliable"] = sl_cal["trades"] >= SL_CALIBRATION_MIN_BUCKET_SAMPLES
        payload["sl_calibration"] = {
            "available": True,
            "min_reliable_samples": SL_CALIBRATION_MIN_BUCKET_SAMPLES,
            "buckets": sl_cal.to_dict(orient="records"),
        }
    else:
        payload["sl_calibration"] = {
            "available": False,
            "reason": "The Stop-Loss Calibration Study has not been run yet — no scheme evidence available.",
        }

    payload["totals"] = {
        "backtest_trades": coach_payload["totals"]["backtest_trades"],
        "forward_closed": coach_payload["totals"]["forward_closed"],
        "marking_read_available": payload["marking_read"]["available"],
        "sl_calibration_available": payload["sl_calibration"]["available"],
    }
    return payload, coach_has_enough


def _call_learning_panel_agent(system_prompt, payload, schema, max_tokens=2000):
    """_call_agent()'s (Phase 8) pattern adapted for ONE system-wide payload -> ONE
    structured finding OBJECT (not a per-candidate array). Returns (dict, error)."""
    if not _anthropic_configured():
        return None, "ANTHROPIC_API_KEY not set in Streamlit secrets."

    user_content = "Here is the current aggregated system data:\n\n" + json.dumps(payload, indent=2, default=str)
    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None, "Agent did not return a JSON object."
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"Could not parse agent response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return None, f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return None, f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return None, f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return None, f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def learning_panel_agent_strategy_performance(payload):
    system = """You are the Strategy Performance Analyst on a 5-agent System Learning Panel
reviewing a solo trader's algorithmic research framework. Using ONLY payload["system"]
["backtest_performance"] (win rate / avg R per strategy: S1-S4 = stock strategies, FUNDA/FUNDB =
fundamental screens, FX_SMC = forex/crypto) and payload["system"]["edge_by_score_band"] (win
rate / avg R by setup-score band per strategy), determine which strategy performs best OVERALL,
and note if the ranking would plausibly change across market regimes when regime information is
present in the data. State sample sizes next to every claim — never treat n<20 as reliable
evidence. Return ONE overall finding for the whole system, not a per-strategy list."""
    return _call_learning_panel_agent(system, payload, _LEARNING_PANEL_FINDING_SCHEMA)


def learning_panel_agent_marking_component(payload):
    system = """You are the Marking/Component Analyst on a 5-agent System Learning Panel. Using
ONLY payload["marking_read"], determine which score components (HTF, Footprint, Entry Quality,
Relative Strength, Safety) show a REAL difference between winners and losers versus which show
none. If payload["marking_read"]["available"] is false, say plainly that Raw Signal Capture has
not been run yet and this section is skipped for now — do NOT invent a finding. When data IS
available, treat "Gap (in std devs)" >= 0.5 as a strong read, 0.2-0.5 as weak/secondary, and below
0.2 as no measurable difference (a candidate to de-weight or drop). Always state the win/loss
sample sizes (payload["marking_read"]["wins"]/["losses"]) behind your claim. This is informational
only — it never changes S1-S4 scoring."""
    return _call_learning_panel_agent(system, payload, _LEARNING_PANEL_FINDING_SCHEMA)


def learning_panel_agent_risk_sl(payload):
    system = """You are the Risk & Stop-Loss Analyst on a 5-agent System Learning Panel — the
direct answer to the trader's question "how much stop-loss should I use, and does it depend on
the stock's chart structure or the market regime?" Using ONLY payload["sl_calibration"], which
reports REAL historical win% / avg-R per (strategy, market_regime, scheme) bucket for candidate
stop-loss schemes (fixed_pct_7 = the CURRENT LIVE 7% stop the scanner actually uses today,
atr_mult_1_5 / atr_mult_2_0 / atr_mult_2_5 = ATR-multiple stops, structure_swing_low = a
support/swing-low based stop), recommend which scheme looks best PER strategy/regime combination
— but only where the evidence genuinely supports a claim.
CRITICAL RULES, follow all of them:
1. If payload["sl_calibration"]["available"] is false, say plainly the Stop-Loss Calibration
   Study has not been run yet and no recommendation can be made yet — do not guess.
2. NEVER recommend a scheme for a bucket whose "trades" count is below
   payload["sl_calibration"]["min_reliable_samples"] — for those, say "not enough data yet"
   rather than recommending anything, even if the win%/avg R numbers look attractive.
3. Always state the exact trade count, win%, and avg R behind every recommendation you do make.
4. Always compare against fixed_pct_7 (the current live stop) explicitly — do not suggest a
   change unless a candidate scheme measurably AND reliably beats it for that specific
   strategy/regime combination.
5. This is informational only — it never changes the live 7% stop-loss automatically; only a
   human decides whether to act on it."""
    return _call_learning_panel_agent(system, payload, _LEARNING_PANEL_FINDING_SCHEMA)


def learning_panel_agent_devils_advocate(payload):
    system = """You are the Devil's Advocate / Overfitting Skeptic on a 5-agent System Learning
Panel. You receive the SAME payload the other three analysts (Strategy Performance, Marking/
Component, Risk & Stop-Loss) saw, and your job is to challenge their likely claims, specifically:
1. Compare payload["system"]["backtest_performance"] against payload["system"]
   ["forward_test_closed"] per strategy — if they diverge meaningfully (different sign of edge,
   or a big win%/avg-R gap), flag this explicitly as likely curve-fitting or regime drift; this is
   the single most important thing to surface.
2. Flag any bucket/component/scheme claim likely to be based on fewer than 20-30 samples,
   whether drawn from edge_by_score_band, marking_read, or sl_calibration — name the sample size
   you're objecting to.
3. If the data genuinely does not support suspicion (large, consistent samples, no meaningful
   backtest/forward divergence), say so plainly rather than inventing doubt — a false alarm here
   is as costly as missed overfitting."""
    return _call_learning_panel_agent(system, payload, _LEARNING_PANEL_FINDING_SCHEMA)


def learning_panel_agent_judge(payload, strategy_finding, marking_finding, risk_finding, skeptic_finding):
    if not _anthropic_configured():
        return None, "ANTHROPIC_API_KEY not set in Streamlit secrets."

    system = """You are the Judge/Synthesizer for a 5-agent System Learning Panel. You will
receive the original aggregated system payload plus four independent findings: Strategy
Performance Analyst, Marking/Component Analyst, Risk & Stop-Loss Analyst, and Devil's Advocate /
Overfitting Skeptic. Combine them into ONE final prioritized list of concrete, numbered
recommendations for the developer. Weight the Devil's Advocate's sample-size and divergence
objections HEAVILY — never rank a recommendation highly if the Skeptic flagged its underlying
evidence as small-sample or as diverging between backtest and forward-test. Prefer fewer,
well-supported recommendations over a padded list — omit a candidate recommendation entirely
rather than include it on weak grounds. Never propose automatically changing the live S1-S4
qualification rules or the live 7% stop-loss — only describe what a human should consider
changing, and why, citing the evidence."""

    user_content = json.dumps({
        "payload": payload,
        "strategy_performance_finding": strategy_finding,
        "marking_component_finding": marking_finding,
        "risk_sl_finding": risk_finding,
        "devils_advocate_finding": skeptic_finding,
    }, indent=2, default=str)

    try:
        client = anthropic.Anthropic(api_key=_anthropic_key())
        resp = client.messages.create(
            model=ANTHROPIC_COACH_MODEL,
            max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"format": {"type": "json_schema", "schema": _LEARNING_PANEL_JUDGE_SCHEMA}},
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or "recommendations" not in parsed:
            return None, "Judge did not return a JSON object with a recommendations array."
        return parsed, None
    except json.JSONDecodeError as e:
        return None, f"Could not parse Judge response as JSON: {e}"
    except anthropic.AuthenticationError as e:
        return None, f"ANTHROPIC_API_KEY is set but was rejected (invalid/revoked key): {e}"
    except anthropic.RateLimitError as e:
        return None, f"Anthropic API rate limit hit — try again shortly: {e}"
    except anthropic.APIStatusError as e:
        return None, f"Anthropic API returned an error (HTTP {e.status_code}): {e}"
    except anthropic.APIConnectionError as e:
        return None, f"Could not reach the Anthropic API (network issue): {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def run_system_learning_panel(raw_signal_result=None):
    """Full pipeline: build payload -> 4 analyst calls -> Judge. Returns a dict
    with keys: payload, strategy, marking, risk, skeptic (each a finding dict or
    None on a per-agent failure), judge (final recommendations dict or None),
    errors (list of any agent errors — non-fatal, the panel degrades gracefully
    with whatever partial results it has, matching run_trade_debate_panel()'s
    existing errors-list pattern rather than crashing on one bad call)."""
    payload, has_enough = build_learning_panel_payload(raw_signal_result)
    if not has_enough:
        return {"error": (
            f"Not enough data yet for a reliable panel analysis "
            f"({payload['totals']['backtest_trades']} backtest trades, "
            f"{payload['totals']['forward_closed']} closed forward tests). "
            f"Run more backtests or let more forward tests resolve first."
        )}

    errors = []

    strategy_finding, e1 = learning_panel_agent_strategy_performance(payload)
    if e1: errors.append(f"Strategy Performance Analyst: {e1}")

    marking_finding, e2 = learning_panel_agent_marking_component(payload)
    if e2: errors.append(f"Marking/Component Analyst: {e2}")

    risk_finding, e3 = learning_panel_agent_risk_sl(payload)
    if e3: errors.append(f"Risk & Stop-Loss Analyst: {e3}")

    skeptic_finding, e4 = learning_panel_agent_devils_advocate(payload)
    if e4: errors.append(f"Devil's Advocate: {e4}")

    judge_result, e5 = learning_panel_agent_judge(payload, strategy_finding, marking_finding, risk_finding, skeptic_finding)
    if e5: errors.append(f"Judge: {e5}")

    return {
        "payload": payload,
        "strategy": strategy_finding, "marking": marking_finding,
        "risk": risk_finding, "skeptic": skeptic_finding,
        "judge": judge_result, "errors": errors,
    }


def ensure_learning_panel_table():
    con = _db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS system_learning_panel_runs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
            total_backtest_trades INTEGER, total_forward_closed INTEGER,
            marking_read_available INTEGER, sl_calibration_available INTEGER,
            strategy_finding_json TEXT, marking_finding_json TEXT,
            risk_finding_json TEXT, skeptic_finding_json TEXT,
            judge_json TEXT, errors_json TEXT
        )""")
        con.commit()
    finally:
        con.close()

ensure_learning_panel_table()


def save_learning_panel_run(result):
    payload = result.get("payload", {}) or {}
    totals = payload.get("totals", {}) or {}
    con = _db()
    try:
        con.execute(
            """INSERT INTO system_learning_panel_runs(
                created_at, total_backtest_trades, total_forward_closed,
                marking_read_available, sl_calibration_available,
                strategy_finding_json, marking_finding_json, risk_finding_json,
                skeptic_finding_json, judge_json, errors_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now().isoformat(timespec="seconds"),
                totals.get("backtest_trades"), totals.get("forward_closed"),
                int(bool(totals.get("marking_read_available"))),
                int(bool(totals.get("sl_calibration_available"))),
                json.dumps(result.get("strategy"), default=str),
                json.dumps(result.get("marking"), default=str),
                json.dumps(result.get("risk"), default=str),
                json.dumps(result.get("skeptic"), default=str),
                json.dumps(result.get("judge"), default=str),
                json.dumps(result.get("errors", []), default=str),
            ),
        )
        con.commit()
    finally:
        con.close()


# ========================= ML WIN PROBABILITY =========================
# Trained on learning_observations (completed backtest/forward-test trades).
# Falls back to the existing score-band edge table (adaptive_edge_table) when
# there isn't yet enough completed evidence to trust a classifier.

ML_MIN_SAMPLES = 60
ML_MIN_CLASS_SAMPLES = 15
ML_FEATURE_COLUMNS = [
    "score", "htf", "footprint", "strategy_score",
    "entry_quality", "relative_strength", "safety_score"
]

@st.cache_resource(ttl=1800, show_spinner=False)
def train_win_probability_model(market="INDIA"):
    """Fit a win-probability classifier on completed learning_observations.

    Returns a dict:
      ready=False, n_samples=<n>, min_samples=<needed> when there isn't
      enough completed evidence yet (or scikit-learn/data is unavailable) —
      callers should fall back to adaptive_edge_table()/current_candidate_edge().
      ready=True with the fitted models, feature schema, and honest
      out-of-sample reliability metrics (AUC / Brier score) otherwise.
    """
    result = {"ready": False, "n_samples": 0, "min_samples": ML_MIN_SAMPLES}
    q = learning_snapshot(market)
    if q.empty or "result_r" not in q.columns:
        return result
    q = q.dropna(subset=["result_r"]).copy()
    result["n_samples"] = len(q)
    if len(q) < ML_MIN_SAMPLES:
        return result

    q["win"] = (pd.to_numeric(q["result_r"], errors="coerce") > 0).astype(int)
    if q.win.sum() < ML_MIN_CLASS_SAMPLES or (len(q)-q.win.sum()) < ML_MIN_CLASS_SAMPLES:
        result["reason"] = "Not enough win/loss diversity yet"
        return result

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_auc_score, brier_score_loss
    except ImportError:
        result["reason"] = "scikit-learn is not installed"
        return result

    x_num = q[ML_FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    strat_dummies = pd.get_dummies(q["strategy"].astype(str).str.upper(), prefix="strategy")
    regime_dummies = pd.get_dummies(q["regime"].astype(str), prefix="regime")
    X = pd.concat([x_num, strat_dummies, regime_dummies], axis=1).fillna(0.0)
    y = q["win"].to_numpy()

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
    except ValueError:
        X_train, X_test, y_train, y_test = X, X, y, y

    gbc = GradientBoostingClassifier(random_state=42)
    gbc.fit(X_train, y_train)
    logit = LogisticRegression(max_iter=1000)
    logit.fit(X_train, y_train)

    def _reliability(model):
        p = model.predict_proba(X_test)[:, 1]
        try:
            auc = float(roc_auc_score(y_test, p))
        except ValueError:
            auc = np.nan
        return auc, float(brier_score_loss(y_test, p))

    gbc_auc, gbc_brier = _reliability(gbc)
    logit_auc, logit_brier = _reliability(logit)

    # Refit on the full dataset for production inference; the held-out split
    # above is only used to report honest reliability metrics.
    gbc.fit(X, y)
    logit.fit(X, y)

    result.update({
        "ready": True,
        "gbc_model": gbc,
        "logit_model": logit,
        "feature_columns": list(X.columns),
        "gbc_auc": gbc_auc, "gbc_brier": gbc_brier,
        "logit_auc": logit_auc, "logit_brier": logit_brier,
    })
    return result

def ml_win_probability(model_info, row):
    """O(1) inference of win probability (0-100) for one candidate row using a
    model dict from train_win_probability_model(). `row` may use either the
    learning_observations naming (score/htf/...) or scanner naming
    (Score/HTF Score/...). Returns np.nan when the model isn't ready."""
    if not model_info or not model_info.get("ready"):
        return np.nan

    def g(*keys, default=0.0):
        for k in keys:
            v = row.get(k) if hasattr(row, "get") else None
            if v is not None and pd.notna(v):
                return v
        return default

    feat = {
        "score": g("score", "Score"),
        "htf": g("htf", "HTF Score", "HTF Demand", "HTF"),
        "footprint": g("footprint", "Footprint Score", "Footprint"),
        "strategy_score": g("strategy_score", "Strategy Score"),
        "entry_quality": g("entry_quality", "Entry Quality"),
        "relative_strength": g("relative_strength", "Relative Strength"),
        "safety_score": g("safety_score", "Safety Score"),
    }
    strategy = str(g("strategy", "Strategy", default="")).upper()
    regime = str(g("regime", "Regime", default=""))

    x = pd.DataFrame([feat])
    x[f"strategy_{strategy}"] = 1.0
    x[f"regime_{regime}"] = 1.0
    x = x.reindex(columns=model_info["feature_columns"], fill_value=0.0)
    try:
        p = model_info["gbc_model"].predict_proba(x)[0, 1]
        return float(round(p*100, 1))
    except Exception:
        return np.nan


# ========================= STRATEGY COACH =========================
# Analyzes completed learning_observations per strategy: regime win-rate/avg-R
# breakdown, high-vs-low component splits, and a shallow (max_depth<=3)
# decision tree translated into plain-English rules. Never rewrites strategy
# rules — this is read-only evidence with explicit sample-size caveats.

STRATEGY_COACH_MIN_SAMPLES = 20
STRATEGY_COACH_TREE_MIN_SAMPLES = 40

def strategy_coach_regime_breakdown(q):
    g = q.groupby("regime").agg(
        Samples=("result_r", "count"),
        WinRate=("win", "mean"),
        AvgR=("result_r", "mean"),
    ).reset_index().rename(columns={"regime": "Regime"})
    g["WinRate"] = (g.WinRate * 100).round(1)
    g["AvgR"] = g.AvgR.round(3)
    return g.sort_values("Samples", ascending=False)

def strategy_coach_component_breakdown(q):
    rows = []
    for c in ML_FEATURE_COLUMNS:
        if c not in q.columns:
            continue
        vals = pd.to_numeric(q[c], errors="coerce")
        med = vals.median()
        if pd.isna(med):
            continue
        hi = q[vals >= med]; lo = q[vals < med]
        if len(hi) == 0 or len(lo) == 0:
            continue
        rows.append({
            "Component": c.replace("_", " ").title(),
            "High Samples": len(hi), "High Win %": round(float(hi.win.mean()) * 100, 1),
            "High Avg R": round(float(hi.result_r.mean()), 3),
            "Low Samples": len(lo), "Low Win %": round(float(lo.win.mean()) * 100, 1),
            "Low Avg R": round(float(lo.result_r.mean()), 3),
        })
    return pd.DataFrame(rows)

def _coach_pretty_feature(name):
    if name.startswith("regime_"):
        return f"Regime == {name[len('regime_'):]}"
    return name.replace("_", " ").upper()

def _coach_extract_tree_rules(tree, feature_names, min_leaf_samples):
    from sklearn.tree import _tree
    t = tree.tree_
    leaves = []
    def recurse(node, path):
        if t.feature[node] != _tree.TREE_UNDEFINED:
            name = feature_names[t.feature[node]]
            thresh = t.threshold[node]
            recurse(t.children_left[node], path + [(name, "<=", thresh)])
            recurse(t.children_right[node], path + [(name, ">", thresh)])
        else:
            n = int(t.n_node_samples[node])
            # tree_.value stores per-node class PROPORTIONS (rows sum to 1),
            # not raw counts, so this is already the leaf's win rate.
            win_rate = float(t.value[node][0][1]) if t.value[node].shape[1] > 1 else 0.0
            leaves.append((path, n, win_rate))
    recurse(0, [])
    leaves.sort(key=lambda x: (-x[2], -x[1]))
    rules = []
    for path, n, win_rate in leaves:
        if n < min_leaf_samples:
            continue
        desc = " AND ".join(f"{_coach_pretty_feature(nm)} {op} {th:.1f}" for nm, op, th in path) or "Overall population"
        rules.append({"Rule": desc, "Samples": n, "Win Rate %": round(win_rate * 100, 1)})
    return rules[:5]

def strategy_coach_tree_rules(q, max_depth=3, min_samples=STRATEGY_COACH_TREE_MIN_SAMPLES):
    """Fit a shallow decision tree and translate its leaves into plain-English
    rules, most winning first. Returns (rules, note); note explains why rules
    are empty when there isn't enough evidence yet."""
    if len(q) < min_samples:
        return [], f"Need ≥{min_samples} completed observations to extract rules; have {len(q)}."
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError:
        return [], "scikit-learn is not installed."
    feat_cols = [c for c in ML_FEATURE_COLUMNS if c in q.columns]
    x_num = q[feat_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    regime_dummies = pd.get_dummies(q["regime"].astype(str), prefix="regime")
    X = pd.concat([x_num, regime_dummies], axis=1)
    y = q["win"].to_numpy()
    if y.sum() < 5 or (len(y) - y.sum()) < 5:
        return [], "Not enough win/loss diversity to extract rules yet."
    min_leaf = max(10, len(q) // 20)
    tree = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=min_leaf, random_state=42)
    tree.fit(X, y)
    rules = _coach_extract_tree_rules(tree, list(X.columns), min_leaf)
    if not rules:
        return [], "No leaf had enough samples to report as a reliable rule."
    return rules, None

def strategy_coach_report(market, strategy):
    """Full read-only coaching report for one strategy, or None when there
    isn't at least one completed observation to analyze."""
    q = learning_snapshot(market)
    if q.empty or "strategy" not in q.columns:
        return None
    q = q[q.strategy.astype(str).str.upper() == str(strategy).upper()].copy()
    q = q.dropna(subset=["result_r"])
    if q.empty:
        return None
    q["result_r"] = pd.to_numeric(q["result_r"], errors="coerce")
    q = q.dropna(subset=["result_r"])
    if q.empty:
        return None
    q["win"] = (q.result_r > 0).astype(int)
    n = len(q)
    enough = n >= STRATEGY_COACH_MIN_SAMPLES
    rules, rule_note = strategy_coach_tree_rules(q)
    return {
        "strategy": strategy, "n_samples": n, "enough_for_breakdown": enough,
        "overall_win_rate": round(float(q.win.mean()) * 100, 1),
        "overall_avg_r": round(float(q.result_r.mean()), 3),
        "regime_breakdown": strategy_coach_regime_breakdown(q) if enough else pd.DataFrame(),
        "component_breakdown": strategy_coach_component_breakdown(q) if enough else pd.DataFrame(),
        "tree_rules": rules, "tree_note": rule_note,
    }


# ========================= BACKTEST =========================

def run_backtest(d,sig,capital,risk,sl,rr,slip=.001):
    x=features(d).dropna(); sig=sig.reindex(x.index).fillna(False)
    equity=capital; rows=[]; i=0
    while i<len(x)-1:
        if not bool(sig.iloc[i]): i+=1; continue
        ei=i+1; entry=float(x.close.iloc[ei])*(1+slip)
        stop=entry*(1-sl); one_r=entry-stop
        qty=int(equity*risk/one_r)
        if qty<1: i+=1; continue
        target=entry+rr*one_r; ex=ep=None; reason=""
        for j in range(ei,len(x)):
            lo=float(x.low.iloc[j]); hi=float(x.high.iloc[j])
            if lo<=stop: ex,ep,reason=j,stop*(1-slip),"SL"; break
            if hi>=target: ex,ep,reason=j,target*(1-slip),f"{rr}R"; break
            if hi>=entry+2*one_r:
                stop=max(stop,entry)
                if pd.notna(x.ema10.iloc[j]): stop=max(stop,float(x.ema10.iloc[j])*(1-slip))
        if ex is None: ex,ep,reason=len(x)-1,float(x.close.iloc[-1])*(1-slip),"End"
        pnl=(ep-entry)*qty; equity+=pnl
        rows.append({"Entry Date":x.index[ei].date(),"Exit Date":x.index[ex].date(),
                     "Entry":entry,"Exit":ep,"Return %":(ep/entry-1)*100,
                     "R":pnl/(one_r*qty),"PnL ₹":pnl,
                     "Holding Days":(x.index[ex]-x.index[ei]).days,"Reason":reason})
        i=ex+1
    return pd.DataFrame(rows),equity

def stats(t):
    if t.empty:return {}
    w=t[t.R>0]; l=t[t.R<0]; gp=w["PnL ₹"].sum(); gl=abs(l["PnL ₹"].sum())
    return {"Trades":len(t),"Win %":round(len(w)/len(t)*100,2),
            "Avg Win %":round(w["Return %"].mean(),2) if len(w) else 0,
            "Avg Loss %":round(l["Return %"].mean(),2) if len(l) else 0,
            "Expectancy R":round(t.R.mean(),3),"Total R":round(t.R.sum(),2),
            "Profit Factor":round(gp/gl,2) if gl else np.nan}

# ========================= FINAL RESEARCH ENGINES =========================
def s4_entry_plan(d,i):
    """Research-only S4 timing plan; uses only bars up to i."""
    if d is None or len(d)<80 or i<40 or i>=len(d):
        return {"State":"INSUFFICIENT DATA"}
    x=d.iloc[:i+1].copy()
    e20=float(ema(x.close,20).iloc[-1]); e50=float(ema(x.close,50).iloc[-1]); e200=float(ema(x.close,200).iloc[-1])
    swing_high=float(x.high.iloc[-60:].max())
    impulse_low=float(x.low.iloc[-60:-20].min()) if len(x)>=60 else float(x.low.iloc[:-20].min())
    close=float(x.close.iloc[-1]); high=float(x.high.iloc[-1]); low=float(x.low.iloc[-1])
    impulse=max(swing_high-impulse_low,1e-9)
    retr=(swing_high-close)/impulse
    vol20=float(sma(x.volume,20).iloc[-1]) if pd.notna(sma(x.volume,20).iloc[-1]) else np.nan
    relvol=float(x.volume.iloc[-1]/vol20) if np.isfinite(vol20) and vol20>0 else 0
    prior_high=float(x.high.iloc[-2])
    prior_low=float(x.low.iloc[-20:-1].min())
    reclaim=close>e20 and float(x.close.iloc[-2])<=float(ema(x.close,20).iloc[-2])
    higher_high=close>prior_high
    trend=(close>e50>e200)
    in_zone=(0.382<=retr<=0.618)
    pullback_low=float(x.low.iloc[-10:].min())
    stop=min(pullback_low,e20*0.98)
    # Prefer prior swing as first target; require at least 2.5R before a new high.
    risk=max(close-stop,1e-9)
    target1=swing_high
    rr1=(target1-close)/risk
    target3=close+3*risk
    confirmation=(trend and in_zone and (reclaim or higher_high) and relvol>=1.2)
    state="BUY-TRIGGER" if confirmation and rr1>=2.5 else "WATCH" if trend and in_zone else "WAIT"
    return {
        "State":state,"Retracement %":round(retr*100,1),"Entry":round(close,2),
        "Stop":round(stop,2),"Swing Target":round(target1,2),"3R Target":round(target3,2),
        "RR to Swing":round(rr1,2),"RelVol":round(relvol,2),
        "Trend OK":trend,"Reclaim":bool(reclaim),"Higher High":bool(higher_high),
    }

def _s4_recovery_event(d,i):
    if i<80 or i>=len(d)-2:return None
    close=d.close; high=d.high; low=d.low; vol=d.volume
    p0=max(0,i-80); p1=max(p0,i-30)
    prior_low=float(low.iloc[p0:p1].min()); prior_high=float(high.iloc[p0:p1].max())
    base=d.iloc[max(0,i-20):i+1]
    if base.empty or prior_low<=0:return None
    impulse=prior_high/prior_low-1
    base_range=(float(base.high.max())/float(base.low.min())-1) if float(base.low.min())>0 else 9
    peak=float(d.high.iloc[max(0,i-40):i].max())
    trough=float(d.low.iloc[max(0,i-20):i].min())
    retr=(peak-trough)/max(peak-float(d.low.iloc[max(0,i-60):i].min()),1e-9) if peak>0 else 1
    vol_base=float(base.volume.mean()); vol_prior=float(d.volume.iloc[max(0,i-60):max(0,i-20)].mean())
    compression=vol_base/vol_prior if vol_prior>0 else 1
    ema20v=float(ema(close,20).iloc[i])
    reclaim=close.iloc[i]>ema20v and close.iloc[i-1]<=ema20v if i>0 else False
    hh=close.iloc[i]>float(high.iloc[max(0,i-20):i].max()) if i>=20 else False
    relvol=float(vol.iloc[i]/sma(vol,20).iloc[i]) if pd.notna(sma(vol,20).iloc[i]) else 0
    score=0
    score+=20 if impulse>=0.40 else 15 if impulse>=0.30 else 10 if impulse>=0.20 else 0
    score+=20 if base_range<=0.12 else 14 if base_range<=0.18 else 7 if base_range<=0.25 else 0
    score+=15 if 0.20<=retr<=0.60 else 8 if retr<=0.75 else 0
    score+=15 if compression<=0.65 else 8 if compression<=0.85 else 0
    score+=15 if reclaim else 0
    score+=10 if hh else 0
    score+=5 if relvol>=1.5 else 3 if relvol>=1.2 else 0
    return {"Score":int(score),"Impulse %":round(impulse*100,1),"Base Range %":round(base_range*100,1),"Retracement %":round(retr*100,1),"Base Vol Ratio":round(compression,2),"RelVol":round(relvol,2),"Reclaim":bool(reclaim),"Higher High":bool(hh)}

def study_s4_recovery_walkforward(data,start_date,end_date,min_score=70):
    """NOTE: kept even though the old strategy4_recovery_* pattern-study
    helpers above it were removed as part of the S4 SEPA replacement - this
    walk-forward study (and its _s4_recovery_event() helper) has an
    independent caller in the Research & Risk Control tab (app.py), which is
    unrelated to the "S4 Recovery Study" tab that was removed. Deliberately
    left as a standalone research tool; not part of live S4."""
    rows=[]; start=pd.Timestamp(start_date); end=pd.Timestamp(end_date)
    for ticker,d in data.items():
        if d is None or len(d)<180:continue
        d=d.sort_index(); f=features_fast(str(ticker),d)
        # Candidate event is evaluated at close i; entry is next bar open/close proxy.
        for i in range(80,len(d)-30):
            dt=d.index[i]
            if dt<start or dt>end:continue
            ev=_s4_recovery_event(d,i)
            if not ev or ev["Score"]<min_score or not ev["Reclaim"] or not ev["Higher High"]:continue
            entry=float(d.close.iloc[i]); risk=entry*0.07; stop=entry-risk; target=entry+3*risk
            exit_idx=min(len(d)-1,i+60); outcome="TIMEOUT"; exitp=float(d.close.iloc[exit_idx]); held=exit_idx-i
            for j in range(i+1,exit_idx+1):
                bar=d.iloc[j]
                if bar.low<=stop: outcome="LOSS"; exitp=stop; held=j-i; break
                if bar.high>=target: outcome="WIN"; exitp=target; held=j-i; break
            r=(exitp-entry)/risk
            rows.append({"Date":dt.date(),"Ticker":str(ticker).replace('.NS',''),"Study":"S4 Recovery","Score":ev["Score"],**ev,"Outcome":outcome,"R":round(r,2),"Holding Bars":held})
    return pd.DataFrame(rows)

S4_EXTENSION_BUCKETS = [
    (-100.0, 0.0, "At/below EMA20"),
    (0.0, 3.0, "0-3% above (exact S4 rule)"),
    (3.0, 6.0, "3-6% above"),
    (6.0, 10.0, "6-10% above"),
    (10.0, 15.0, "10-15% above"),
    (15.0, 25.0, "15-25% above"),
    (25.0, 1000.0, ">25% above"),
]
S4_CALIBRATION_MIN_BUCKET_SAMPLES = 15

def s4_ema20_extension_calibration(data, start_date, end_date, sl_pct=0.07, target_r=3.0):
    """Backtest every exact Strategy 4 condition EXCEPT the fixed
    close<=1.03*EMA20 rule (via s4_base_conditions), and record how far above
    or below EMA20 price actually was at each qualifying signal, plus the
    resulting trade outcome. This is the raw evidence behind
    s4_extension_bucket_report() - it does not itself assume 3% is correct."""
    rows=[]; start=pd.Timestamp(start_date); end=pd.Timestamp(end_date)
    for ticker,df in data.items():
        if df is None or len(df)<260: continue
        try:
            df=df.sort_index(); f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
            if f.empty: continue
            sig=s4_base_conditions(f).fillna(False).to_numpy()
            for i in np.flatnonzero(sig):
                dt=pd.Timestamp(f.index[i])
                if dt<start or dt>end or i>=len(df)-1: continue
                z=f.iloc[i]
                if pd.isna(z.ema20) or z.ema20<=0 or pd.isna(z.close): continue
                extension=(float(z.close)/float(z.ema20)-1)*100
                regime,_=_regime_from_row(f,i)
                entry_i=i+1; entry=float(df.close.iloc[entry_i])
                if not np.isfinite(entry) or entry<=0: continue
                stop=entry*(1-sl_pct); target=entry+target_r*(entry-stop)
                outcome,exit_price,held=_fast_trade_outcome(df,entry_i,stop,target)
                result_r=(exit_price-entry)/(entry-stop) if (entry-stop)>0 else 0.0
                rows.append({
                    'Date':dt.date(),'Ticker':str(ticker).replace('.NS',''),
                    'EMA20 Extension %':round(extension,2),'Regime':regime,
                    'Entry':round(entry,2),'Outcome':outcome,'R':round(float(result_r),3),
                    'Holding Bars':int(held)
                })
        except Exception:
            continue
    return pd.DataFrame(rows)

def s4_extension_bucket_report(cal_df):
    """Bucket s4_ema20_extension_calibration() output by EMA20 distance and
    report win rate/avg R per bucket, flagging which buckets have enough
    samples to be trusted (>=S4_CALIBRATION_MIN_BUCKET_SAMPLES)."""
    if cal_df.empty:
        return pd.DataFrame()
    df=cal_df.copy()
    edges=[b[0] for b in S4_EXTENSION_BUCKETS]+[S4_EXTENSION_BUCKETS[-1][1]]
    labels=[b[2] for b in S4_EXTENSION_BUCKETS]
    df["Bucket"]=pd.cut(df["EMA20 Extension %"],bins=edges,labels=labels,include_lowest=True)
    df["Win"]=(df.R>0).astype(int)
    g=df.groupby("Bucket",observed=False).agg(
        Samples=("R","count"), WinRate=("Win","mean"), AvgR=("R","mean"), TotalR=("R","sum")
    ).reset_index()
    g["WinRate"]=(g.WinRate*100).round(1); g["AvgR"]=g.AvgR.round(3); g["TotalR"]=g.TotalR.round(2)
    g["Reliable (>=%d samples)"%S4_CALIBRATION_MIN_BUCKET_SAMPLES]=g.Samples>=S4_CALIBRATION_MIN_BUCKET_SAMPLES
    return g

def s4_custom_dsl_from_bucket(bucket_label):
    """Render a Custom Strategy DSL rule set replicating S4's other
    conditions with the learned EMA20 distance swapped in for the fixed 3%
    rule. The DSL is AND-only, so the 'OR reclaim' branch of exact S4 is
    approximated by the monthly-cross-count condition alone - this is a
    slightly narrower (fewer false positives, some missed reclaim-only
    setups), not identical, scan."""
    lo, hi, _ = next(b for b in S4_EXTENSION_BUCKETS if b[2] == bucket_label)
    lines = ["MMOM >= 20", "MRSI14 >= 50", "MEMA10 >= MEMA20", "VOL30 >= 50000", "CLOSE >= 20", "M_CROSS_COUNT20 >= 1"]
    if hi < 1000.0:
        lines.append(f"CLOSE <= {round(1+hi/100,3)} * EMA20")
    if lo > -100.0:
        lines.append(f"CLOSE >= {round(1+lo/100,3)} * EMA20")
    return "\n".join(lines)

def research_metrics(df):
    if df.empty:return {"trades":0,"win_rate":0,"avg_r":0,"profit_factor":0}
    wins=df[df.R>0].R; losses=df[df.R<=0].R
    gp=float(wins.sum()); gl=abs(float(losses.sum()))
    return {"trades":len(df),"win_rate":float((df.R>0).mean()*100),"avg_r":float(df.R.mean()),"profit_factor":gp/gl if gl>0 else (99.99 if gp>0 else 0)}

def portfolio_from_backtest(bt,capital,risk_pct,slots):
    x=bt.copy()
    if x.empty:return {"Starting Capital":capital,"Final Capital":capital,"ROI %":0,"Max DD %":0,"Trades":0}
    x=x.sort_values("Date"); equity=float(capital); peak=equity; maxdd=0; taken=0
    # Conservative fixed-fraction compounding using realized R; no overlapping-capital optimism.
    for r in x.itertuples():
        risk_cash=equity*float(risk_pct)/100
        equity += risk_cash*float(r.R)
        taken+=1; peak=max(peak,equity); maxdd=max(maxdd,(peak-equity)/peak*100 if peak else 0)
        if equity<=0:equity=0;break
    return {"Starting Capital":round(capital,2),"Final Capital":round(equity,2),"Profit ₹":round(equity-capital,2),"ROI %":round((equity/capital-1)*100,2),"Max DD %":round(maxdd,2),"Trades":taken,"Risk/Trade %":risk_pct,"Slots (display)":slots}

def load_scan_dataset(tickers, min_bars=260, lookback_days=1000):
    """Local-only candle load for a scan. Makes zero Dhan calls."""
    data = {}
    con = _db()
    try:
        for ticker in tickers:
            clean = str(ticker).upper().replace(".NS", "")
            d = _read_cache(con, clean, date.today() - timedelta(days=lookback_days), date.today())
            if d is not None and len(d) >= min_bars:
                data[ticker] = d
    finally:
        con.close()
    return data


def scan_dataset(data, strategies, regime, progress_cb=None, stats=None):
    """The scan itself: every stock against every selected strategy.

    Single source of truth shared by the Streamlit Daily Scanner and the
    headless daily job, so the scheduled run can never drift from what the UI
    shows. A setup is produced only when ALL rules of that individual strategy
    pass; score and safety rank the survivors, they never suppress one.
    """
    counts = stats if isinstance(stats, dict) else {}
    counts.setdefault("downloaded", len(data))
    counts.setdefault("usable", 0)
    counts.setdefault("too_short", 0)
    # Seed all four strategies, not just the selected ones: callers index these
    # by fixed strategy number when rendering the audit table.
    counts.setdefault("signals", {1: 0, 2: 0, 3: 0, 4: 0})
    counts.setdefault("qualified", {1: 0, 2: 0, 3: 0, 4: 0})
    counts.setdefault("safety_reject", 0)

    # Shared universe/safety/liquidity gate, applied to EVERY strategy (S1-S4)
    # before any strategy_signal() is evaluated. No strategy can surface a
    # manipulated/illiquid/choppy-price-action name, regardless of which one
    # found it - this is deliberately unconditional, not a per-strategy option.
    clean_data, safety_gate_audit = clean_liquid_universe(data)
    counts["safety_gate_audit"] = safety_gate_audit
    counts["safety_gate_excluded"] = max(0, len(data) - len(clean_data))
    data = clean_data

    ml_model = train_win_probability_model("INDIA")
    # Exposed so a caller can report on the model without re-training it
    # (train_win_probability_model is cached, but the cache is Streamlit's and
    # is not available headlessly).
    counts["ml_model"] = ml_model
    rows = []
    total = max(1, len(data))

    for n, (ticker, df) in enumerate(data.items()):
        if len(df) < 260:
            counts["too_short"] += 1
            if progress_cb:
                progress_cb((n + 1) / total)
            continue

        f = features_fast(str(ticker), df)
        # Keep the latest row even when some long-term indicators are unavailable.
        # Individual strategy conditions will evaluate NaNs as False.
        f = f.replace([np.inf, -np.inf], np.nan)
        if len(f) < 260:
            if progress_cb:
                progress_cb((n + 1) / total)
            continue

        counts["usable"] += 1
        # Do NOT fetch fundamentals for the whole universe. Price/volume safety is
        # computed locally; fundamental/news enrichment is candidate-only.
        info = {}
        safe, safe_status, flags = safety(info, df)

        for s in strategies:
            s = int(s)
            sig = strategy_signal(f, s)
            signal = bool(sig.iloc[-1])
            if signal:
                counts["signals"][s] = counts["signals"].get(s, 0) + 1
            if not signal:
                continue

            score, parts = final_setup_score(f, s, regime, safe)
            counts["qualified"][s] = counts["qualified"].get(s, 0) + 1

            z = f.iloc[-1]
            entry = float(z.close)
            stop = entry * .93
            target = entry + 3 * (entry - stop)

            # Learning-edge lookups stay keyed by "S4" (unchanged): the backtest
            # engine (which populates learning_observations) also labels this
            # slot "S4" regardless of which formula strategy_signal(x, 4)
            # currently runs, so this key must match that bucket to find any
            # historical edge at all. Only the value persisted into
            # forward_tests is renamed - see below and the migration in _db().
            edge_r, learn_conf = current_candidate_edge("INDIA", f"S{s}", float(score))
            learned_rank = float(np.clip(score + edge_r * 2.0, 0, 100))
            adaptive_score = adaptive_candidate_score(float(score), "INDIA", f"S{s}", parts)

            # The "Strategy" field below is what a caller (add_forward_candidates)
            # ultimately writes into forward_tests.strategy. S4 is tagged
            # "S4_SEPA" there (not "S4") so pre-SEPA and post-SEPA forward-test
            # rows stay distinguishable, per the forward_tests migration in _db().
            strategy_label = "S4_SEPA" if s == 4 else f"S{s}"
            row = {
                "Score": score,
                "Adaptive Score": round(adaptive_score, 2),
                "Learned Rank": round(learned_rank, 2),
                "Historical Edge R": round(edge_r, 3),
                "Learning Confidence": learn_conf,
                "Ticker": str(ticker).replace(".NS", ""),
                "Strategy": strategy_label,
                "Signal": "ALL RULES PASS",
                "Regime": regime,
                "Safety": safe_status,
                "Entry": round(entry, 2),
                "SL 7%": round(stop, 2),
                "Target 3R": round(target, 2),
                "R:R": "1:3",
                "RSI": round(float(z.rsi14), 1),
                "RelVol": round(float(z.relvol), 2),
                "HTF Score": parts["HTF Demand"],
                "Footprint Score": parts["Footprint"],
                "Strategy Score": parts["Strategy"],
                "Entry Quality": parts["Entry Quality"],
                "Relative Strength": parts["Relative Strength"],
                "Safety Score": safe,
                "Safety Flags": ", ".join(flags),
            }
            win_prob = ml_win_probability(ml_model, row)
            if pd.isna(win_prob):
                win_prob = fallback_win_probability("INDIA", f"S{s}", float(score))
            row["Win Probability %"] = win_prob
            rows.append(row)

        if progress_cb:
            progress_cb((n + 1) / total)

    return pd.DataFrame(rows)


def persist_scanner_signals(result, min_score, signal_date=None):
    """Store every qualified signal; mark only those at/above the gate as
    selected for forward testing. Keyed on date|symbol|strategy, so re-running
    a scan on the same day updates rows instead of duplicating them."""
    if result is None or result.empty:
        return 0
    signal_date = str(signal_date or date.today())
    now = datetime.now().isoformat(timespec="seconds")
    con = _db()
    try:
        for _, r in result.iterrows():
            sym = str(r.get("Ticker", "")).upper().replace(".NS", "")
            strat = str(r.get("Strategy", "")).upper()
            con.execute("""INSERT OR REPLACE INTO scanner_signals(
                signal_key,created_at,signal_date,symbol,strategy,score,learned_rank,
                historical_edge_r,learning_confidence,regime,safety_status,safety_score,
                entry,stop,target,rr,rsi,relvol,htf_score,footprint_score,
                strategy_score,entry_quality,relative_strength,safety_flags,selected_for_forward
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                f"{signal_date}|{sym}|{strat}", now, signal_date, sym, strat,
                float(r.get("Score", 0)), float(r.get("Learned Rank", 0)),
                float(r.get("Historical Edge R", 0)), str(r.get("Learning Confidence", "")),
                str(r.get("Regime", "")), str(r.get("Safety", "")),
                float(r.get("Safety Score", 0)), float(r.get("Entry", np.nan)),
                float(r.get("SL 7%", r.get("SL", np.nan))),
                float(r.get("Target 3R", r.get("Target", np.nan))),
                3.0, float(r.get("RSI", np.nan)), float(r.get("RelVol", np.nan)),
                float(r.get("HTF Score", r.get("HTF Demand", 0))),
                float(r.get("Footprint Score", r.get("Footprint", 0))),
                float(r.get("Strategy Score", 0)), float(r.get("Entry Quality", 0)),
                float(r.get("Relative Strength", 0)), str(r.get("Safety Flags", "")),
                int(float(r.get("Score", 0)) >= min_score)
            ))
        con.commit()
    finally:
        con.close()
    return len(result)


def add_forward_candidates(candidates):
    """Persist scanner-selected candidates into SQLite so refresh/restart does not erase them."""
    if candidates is None or len(candidates)==0:
        return 0
    con=_db(); added=0
    try:
        today=str(date.today())
        for _,r in candidates.iterrows():
            symbol=str(r.get("Ticker","")).upper().replace(".NS","")
            strategy=str(r.get("Strategy","")).upper()
            score=float(r.get("Score",0))
            if not symbol or strategy not in {"S1","S2","S3","S4_SEPA"}:
                continue
            entry=float(r.get("Entry",np.nan)); sl=float(r.get("SL",r.get("SL 7%",np.nan)))
            target=float(r.get("Target",r.get("Target 3R",np.nan)))
            if not np.isfinite(entry) or entry<=0 or not np.isfinite(sl) or not np.isfinite(target):
                continue
            exists=con.execute(
                """SELECT id FROM forward_tests
                   WHERE symbol=? AND strategy=? AND signal_date=? LIMIT 1""",
                (symbol,strategy,today)
            ).fetchone()
            if exists:
                continue
            now=datetime.now().isoformat(timespec="seconds")
            snapshot={k:r.get(k,None) for k in r.index}
            cur=con.execute("""INSERT INTO forward_tests(
                created_at,symbol,strategy,score,regime,entry,sl,target,status,ltp,mfe,mae,
                exit_price,result_r,updated_at,signal_date,signal_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                now,symbol,strategy,score,str(r.get("Regime","")).strip(),
                entry,sl,target,"ACTIVE",entry,0.0,0.0,None,None,now,
                today,json.dumps(snapshot,default=str,allow_nan=True)
            ))
            fid=int(cur.lastrowid); added+=1
            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
                fid,now,today,entry,entry,entry,0.0,0.0,0.0,"ACTIVE"
            ))
        con.commit()
    finally:
        con.close()
    if added:
        maybe_backup_db()
    return added

# ========================= RESEARCH MODULES =========================

def refresh_forward_positions():
    """Update active forward records using only locally stored daily candles."""
    con=_db()
    try:
        active=pd.read_sql_query(
            """SELECT id,created_at,signal_date,symbol,strategy,score,regime,entry,sl,target
               FROM forward_tests WHERE status='ACTIVE' ORDER BY created_at DESC""",con
        )
    finally: con.close()
    if active.empty:return 0,0

    today=last_expected_nse_session(); updates=0
    newly_closed=[]
    con=_db()
    try:
        for r in active.itertuples():
            s=str(r.symbol).upper().replace(".NS","")
            signal_date=pd.to_datetime(r.signal_date or r.created_at).date()
            d=_read_cache(con,s,signal_date,today)
            if d is None or d.empty: continue

            entry=float(r.entry);stop=float(r.sl);target=float(r.target)
            last_dt=pd.Timestamp(d.index[-1]).date(); close=float(d.close.iloc[-1])
            mfe=max(0.0,(float(d.high.max())/entry-1)*100)
            mae=min(0.0,(float(d.low.min())/entry-1)*100)
            ret=(close/entry-1)*100; held=max(0,len(d)-1)
            status="ACTIVE";exitp=None;result_r=None;closed_at=None

            for _,bar in d.iterrows():
                if float(bar.low)<=stop:
                    status="STOP";exitp=stop;result_r=(exitp-entry)/(entry-stop);closed_at=datetime.now().isoformat(timespec="seconds");break
                if float(bar.high)>=target:
                    status="TARGET";exitp=target;result_r=(exitp-entry)/(entry-stop);closed_at=datetime.now().isoformat(timespec="seconds");break

            con.execute("""INSERT OR IGNORE INTO forward_observations(
                forward_id,observed_at,dt,ltp,high,low,unrealized_return_pct,mfe_pct,mae_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
                int(r.id),datetime.now().isoformat(timespec="seconds"),str(last_dt),
                close,float(d.high.iloc[-1]),float(d.low.iloc[-1]),ret,mfe,mae,status
            ))

            if status!="ACTIVE":
                con.execute("""UPDATE forward_tests
                    SET status=?,ltp=?,mfe=?,mae=?,exit_price=?,result_r=?,updated_at=?
                    WHERE id=?""",
                    (status,exitp,mfe,mae,exitp,result_r,closed_at,int(r.id)))
                con.execute("""INSERT OR IGNORE INTO forward_results(
                    forward_id,symbol,strategy,signal_date,entry,exit_price,result_r,
                    return_pct,outcome,holding_bars,mfe_pct,mae_pct,regime,score,closed_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    int(r.id),s,str(r.strategy),str(signal_date),entry,exitp,result_r,
                    (exitp/entry-1)*100,status,held,mfe,mae,str(r.regime),float(r.score),closed_at
                ))
                newly_closed.append({
                    "symbol": s, "strategy": str(r.strategy), "signal_time": str(signal_date),
                    "score": float(r.score), "regime": str(r.regime), "entry": entry,
                    "exit_price": exitp, "result_r": result_r,
                    "outcome": "WIN" if status == "TARGET" else "LOSS" if status == "STOP" else status,
                    "holding_minutes": held * 24 * 60,  # daily-bar strategy; bars converted to minutes for schema consistency
                })
            else:
                con.execute("""UPDATE forward_tests SET ltp=?,mfe=?,mae=?,updated_at=? WHERE id=?""",
                            (close,mfe,mae,datetime.now().isoformat(timespec="seconds"),int(r.id)))
            updates+=1
        con.commit()
    finally: con.close()

    # Feed the learning DB only after the connection above is committed and
    # closed, so this never contends with it for the SQLite write lock.
    # Previously forward-test outcomes closed here (forward_tests/forward_results)
    # but never reached learning_observations at all - the learning engine only
    # ever learned from backtests, never from real forward performance.
    for trade in newly_closed:
        _record_learning_trade("INDIA", trade, source="forward")

    return updates, len(newly_closed)

def forward_positions_view(use_live=True):
    """Forward-test book with a real current price and live P/L.

    The tab previously showed the raw `forward_tests` rows, where the only price
    column was `ltp` — a value written by refresh_forward_positions() from the
    last STORED daily candle. So it was as stale as the candle cache, and there
    was no gain/loss column at all. This adds:
      - Current Price taken from the live feed when the session is open
      - Gain/Loss % and per-share Gain/Loss
      - Unrealized R, measured on the position's own risk (entry - stop)
      - How far price still is from target and from stop
      - Days held, plus where the price came from and when

    Returns (dataframe, meta).
    """
    con = _db()
    try:
        ft = pd.read_sql_query(
            """SELECT id,signal_date,created_at,symbol,strategy,score,regime,entry,sl,target,
                      status,ltp,mfe,mae,exit_price,result_r,updated_at
               FROM forward_tests ORDER BY signal_date DESC, score DESC""", con)
    finally:
        con.close()

    meta = {"live_symbols": 0, "as_of": None, "source": "STORED CLOSE", "market_open": nse_market_is_open()}
    if ft.empty:
        return ft, meta

    for c in ["score", "entry", "sl", "target", "ltp", "mfe", "mae", "exit_price", "result_r"]:
        ft[c] = pd.to_numeric(ft[c], errors="coerce")

    live = {}
    active_symbols = sorted({str(s).upper().replace(".NS", "")
                             for s in ft.loc[ft.status == "ACTIVE", "symbol"].tolist()})
    if use_live and active_symbols:
        try:
            live = live_price_map(active_symbols)
        except Exception:
            live = {}
    if live:
        meta["live_symbols"] = len(live)
        meta["as_of"] = max(v["ts"] for v in live.values())
        sources = {v["source"] for v in live.values()}
        meta["source"] = "WEBSOCKET" if sources == {"WEBSOCKET"} else ("QUOTE" if sources == {"QUOTE"} else "MIXED")

    def _price_row(r):
        sym = str(r.symbol).upper().replace(".NS", "")
        if r.status != "ACTIVE":
            # A closed position's price is its realised exit, not a live quote.
            px = r.exit_price if np.isfinite(r.exit_price) else r.ltp
            return px, "EXIT FILL", str(r.updated_at or "")
        hit = live.get(sym)
        if hit and np.isfinite(hit["price"]) and hit["price"] > 0:
            return float(hit["price"]), hit["source"], hit["ts"]
        return (r.ltp if np.isfinite(r.ltp) else r.entry), "STORED CLOSE", str(r.updated_at or "")

    priced = [_price_row(r) for r in ft.itertuples()]
    ft["Current Price"] = [p[0] for p in priced]
    ft["Price Source"] = [p[1] for p in priced]
    ft["Price As Of"] = [p[2] for p in priced]

    entry = ft["entry"]
    cur = pd.to_numeric(ft["Current Price"], errors="coerce")
    risk = (entry - ft["sl"]).replace(0, np.nan)
    reward = (ft["target"] - entry).replace(0, np.nan)

    ft["Gain/Loss %"] = (cur / entry - 1) * 100
    ft["Gain/Loss ₹"] = cur - entry
    ft["Unrealized R"] = (cur - entry) / risk
    ft["To Target %"] = (ft["target"] / cur - 1) * 100
    ft["To Stop %"] = (ft["sl"] / cur - 1) * 100
    # How much of the planned entry->target distance has been travelled.
    # Clipped to the same range the UI progress bar renders, so a runner past
    # its target reads as a full bar rather than overflowing it.
    ft["Progress to Target %"] = ((cur - entry) / reward * 100).clip(lower=-100, upper=100)

    signal_dt = pd.to_datetime(ft["signal_date"].fillna(ft["created_at"]), errors="coerce")
    ft["Days Held"] = (pd.Timestamp(date.today()) - signal_dt.dt.normalize()).dt.days

    # Vectorised, so no reliance on itertuples' renaming of columns whose names
    # are not valid Python identifiers ("Gain/Loss %" and friends).
    gl = ft["Gain/Loss %"]
    active = ft["status"].eq("ACTIVE")
    ft["Alert"] = np.select(
        [
            ~active,
            active & cur.ge(ft["target"]),
            active & cur.le(ft["sl"]),
            active & gl.ge(5),
            active & gl.le(-4),
            active & gl.notna(),
        ],
        ["🏁 CLOSED", "🎯 AT/ABOVE TARGET", "🛑 AT/BELOW STOP",
         "🟢 IN PROFIT", "🔴 UNDER WATER", "⚪ FLAT"],
        default="—",
    )

    out = pd.DataFrame({
        "Alert": ft["Alert"],
        "Signal Date": ft["signal_date"],
        "Ticker": ft["symbol"],
        "Strategy": ft["strategy"],
        "Status": ft["status"],
        "Score": ft["score"].round(1),
        "Entry": entry.round(2),
        "Current Price": cur.round(2),
        "Gain/Loss %": ft["Gain/Loss %"].round(2),
        "Gain/Loss ₹": ft["Gain/Loss ₹"].round(2),
        "Unrealized R": ft["Unrealized R"].round(2),
        "Stop": ft["sl"].round(2),
        "Target": ft["target"].round(2),
        "To Target %": ft["To Target %"].round(2),
        "To Stop %": ft["To Stop %"].round(2),
        "Progress to Target %": ft["Progress to Target %"].round(1),
        "MFE %": ft["mfe"].round(2),
        "MAE %": ft["mae"].round(2),
        "Days Held": ft["Days Held"],
        "Regime": ft["regime"],
        "Realized R": ft["result_r"].round(2),
        "Price Source": ft["Price Source"],
        "Price As Of": ft["Price As Of"],
        "id": ft["id"],
    })
    return out, meta


def forward_summary_table():
    """Persistent strategy scorecard from forward-test records."""
    con=_db()
    try:
        q=pd.read_sql_query(
            """SELECT strategy AS Strategy,
                      COUNT(*) AS Records,
                      SUM(CASE WHEN status='ACTIVE' THEN 1 ELSE 0 END) AS Open,
                      SUM(CASE WHEN status IN ('TARGET','STOP','EXIT','EXPIRED') THEN 1 ELSE 0 END) AS Closed,
                      SUM(CASE WHEN result_r>0 THEN 1 ELSE 0 END) AS Wins,
                      SUM(CASE WHEN result_r<=0 AND result_r IS NOT NULL THEN 1 ELSE 0 END) AS Losses,
                      AVG(result_r) AS AvgR,
                      SUM(result_r) AS TotalR,
                      AVG(CASE WHEN result_r IS NOT NULL THEN (result_r*100.0/3.0) END) AS AvgROIProxy,
                      AVG(mfe) AS AvgMFE,
                      AVG(mae) AS AvgMAE
               FROM forward_tests GROUP BY strategy ORDER BY AvgR DESC""",con
        )
    finally:
        con.close()
    if q.empty:return q
    # SQLite AVG()/SUM() return NULL when every row is still ACTIVE (no closed
    # trades yet for that strategy), which pd.read_sql_query surfaces as an
    # object-dtype column of Nones rather than numeric NaN — .round() raises
    # TypeError on an object dtype, so coerce to numeric first.
    for col in ["AvgR","TotalR","AvgROIProxy","AvgMFE","AvgMAE"]:
        q[col]=pd.to_numeric(q[col],errors="coerce")
    q["Win %"]=np.where((q["Wins"]+q["Losses"])>0,q["Wins"]/(q["Wins"]+q["Losses"])*100,np.nan)
    q["Status"]=np.where(q["Closed"]<3,"BUILDING SAMPLE",
                         np.where(q["AvgR"]>0.75,"STRONG",
                                  np.where(q["AvgR"]>0.2,"POSITIVE",
                                           np.where(q["AvgR"]>-0.1,"NEUTRAL","WEAK"))))
    q["AvgR"]=q["AvgR"].round(3);q["TotalR"]=q["TotalR"].round(2)
    q["Win %"]=pd.to_numeric(q["Win %"],errors="coerce").round(1)
    q["AvgMFE"]=q["AvgMFE"].round(2);q["AvgMAE"]=q["AvgMAE"].round(2)
    return q


def crypto_learning_summary(symbol=None):
    """Summarise persisted crypto research observations; safe when empty."""
    _ensure_research_tables()
    con=_db()
    try:
        if symbol:
            q=pd.read_sql_query(
                "SELECT * FROM research_events WHERE market='CRYPTO' AND symbol=? ORDER BY created_at DESC",
                con,params=(str(symbol).upper(),)
            )
        else:
            q=pd.read_sql_query(
                "SELECT * FROM research_events WHERE market='CRYPTO' ORDER BY created_at DESC",
                con
            )
    finally:
        con.close()
    if q.empty:
        return pd.DataFrame()
    q["Win"]=(q["r_multiple"]>0).astype(int)
    return (q.groupby(["symbol","study"],dropna=False)
              .agg(Observations=("id","count"),WinRate=("Win","mean"),AvgR=("r_multiple","mean"),BestR=("r_multiple","max"))
              .reset_index()
              .assign(WinRate=lambda x:(x.WinRate*100).round(1),AvgR=lambda x:x.AvgR.round(3),BestR=lambda x:x.BestR.round(3)))

def _two_year_backtest(data, strategies, threshold=85):
    return _fast_score_learning_backtest(data, strategies, threshold)

def _learning_summary(bt):
    if bt.empty:return pd.DataFrame()
    x=bt.copy();x["Win"]=(x.Outcome=="WIN").astype(int)
    y=x.groupby("Strategy").agg(Signals=("Ticker","count"),Wins=("Win","sum"),
        WinRate=("Win","mean"),AvgR=("R","mean"),BestScore=("Score","max")).reset_index()
    y["WinRate"]=(y.WinRate*100).round(1); y["AvgR"]=y.AvgR.round(2)
    return y


