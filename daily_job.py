#!/usr/bin/env python3
"""Scheduled, headless runner for the Adaptive Trading Intelligence Lab.

The web app only runs the engine while its API server is up and somebody asks
it to. This script drives the same engine (backend/app/engine/core.py) from
GitHub Actions instead, on a cron schedule, with nothing else running.

    python daily_job.py token      # renew the Dhan access token only
    python daily_job.py daily      # full post-close run
    python daily_job.py bootstrap  # build the candle history from scratch, once
    python daily_job.py backtest   # replay the strategies over the stored history
    python daily_job.py study      # one research study (BACKTEST_STUDY names it)
    python daily_job.py --help

The full run, in order:

  1. restore   pull the last database backup from GitHub
  2. token     renew the Dhan access token (PIN+TOTP)
  3. sync      top up the newest candles for the configured universe
  4. resolve   close any forward test that hit its stop or target
  5. scan      run the scanner on the just-closed session
  6. add       record signals at/above the gate as forward-test candidates
  7. backup    push the database back to GitHub

Every step is idempotent: running twice in one day updates rows rather than
duplicating them, and add_forward_candidates() already refuses a second record
for the same symbol/strategy/date. Steps 5-7 are skipped entirely on a day the
NSE did not trade.

Configuration comes from environment variables (see core._secret):

    required   DHAN_CLIENT_ID
               DHAN_PIN + DHAN_TOTP_SECRET   (or DHAN_ACCESS_TOKEN)
               GH_BACKUP_TOKEN + GH_REPO     (the database lives there)
    optional   DB_BACKUP_BRANCH  dedicated branch for the backup commits
               SCAN_UNIVERSE     default "Nifty 500"; any name in
                                 core.UNIVERSE_CHOICES, including
                                 "NSE All Cash (~2000)" for the full list
               SCAN_STRATEGIES   default "1,2,3,4"
               SCAN_MIN_SCORE    default "85"
               SYNC_TAIL_DAYS    default core.LATEST_SYNC_TAIL_DAYS

GitHub refuses to create secrets or variables whose NAME starts with "GITHUB_",
so the backup settings are read from the non-reserved aliases above (the
original GITHUB_TOKEN / GITHUB_REPO names still work in a local .env).
"""

import argparse
import gzip
import json
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# Import the engine, not the API. The engine moved into the backend package
# during the web-app migration; this keeps the workflows' entry point and CLI
# unchanged by putting backend/ on the path rather than moving the script.
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from app.engine import core  # noqa: E402
from app.services import bootstrap  # noqa: E402


# The session the scan last covered, so a second run in the same day is a
# no-op rather than repeated work.
LAST_SCANNED_SESSION_KEY = "daily_job_last_scanned_session"


def log(step, message):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {step:<8} {message}", flush=True)


def _env_int(name, default):
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _env_flag(name):
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _clear_candles():
    """Drop every stored candle so the next download rebuilds the store.

    Only the candle table: forward tests, resolved results and learning live in
    other tables and are not reproducible from anywhere, so they are never
    touched here. Candles are, by definition, re-downloadable — which is what
    makes a rebuild the safe way to correct data that is wrong rather than
    missing, where a top-up would find nothing to do.
    """
    con = core._db()
    try:
        removed = int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
        con.execute("DELETE FROM candles")
        con.commit()
    finally:
        con.close()
    con = core._db()
    try:
        con.execute("VACUUM")          # otherwise the freed pages ride along in every backup
    finally:
        con.close()
    return removed


def _selected_strategies():
    raw = os.environ.get("SCAN_STRATEGIES", "1,2,3,4")
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if part in {"1", "2", "3", "4"} and int(part) not in out:
            out.append(int(part))
    return out or [1, 2, 3, 4]


def _universes():
    """Universe names from SCAN_UNIVERSE, validated against the engine's own list.

    This used to check against a hand-copied set of the four index names, which
    silently dropped "NSE All Cash (~2000)" — the one option this file's own
    docstring tells you to use for the full list. Validating against
    core.UNIVERSE_CHOICES is the whole point of that constant existing.

    An unrecognised name is logged rather than dropped in silence: a typo that
    quietly scans a different universe than the one you configured is worse
    than one that says so.
    """
    raw = os.environ.get("SCAN_UNIVERSE", "Nifty 500")
    requested = [u.strip() for u in str(raw).split("|") if u.strip()]
    out, unknown = [], []
    for name in requested:
        (out if name in core.UNIVERSE_CHOICES else unknown).append(name)
    for name in unknown:
        log("universe", f"ignoring unknown SCAN_UNIVERSE entry {name!r}; "
                        f"valid names are: {', '.join(core.UNIVERSE_CHOICES)}")
    if not out:
        log("universe", "no usable SCAN_UNIVERSE value; falling back to Nifty 500")
    return out or ["Nifty 500"]


# ----------------------------------------------------------------- steps ----

def step_restore():
    """Pull the last database backup before anything else touches the store.

    The runner's filesystem starts empty on every job, so without this the run
    would build a brand-new database and the backup at the end would overwrite
    the real one with it.

    This defers to the same cold-start path the API server uses, and for the
    same reason: importing ``core`` runs its learning restore, which leaves the
    database holding rows, and ``restore_db_from_github()`` then refuses to
    overwrite it. Calling that function directly here therefore looked like
    "local database already present, keeping it" on a machine that had just been
    created — and the backup at the end of the run would have pushed that
    learning-only database over the real one, destroying the candle history.
    """
    if not core._github_configured():
        raise RuntimeError(
            "The GitHub backup is not configured (GH_BACKUP_TOKEN / GH_REPO). The database "
            "cannot be restored, and continuing would push an empty database over your saved "
            "forward tests."
        )

    outcome = bootstrap.restore_on_cold_start()
    if outcome["restored_full"]:
        size = os.path.getsize(core.DATA_DB)
        log("restore", f"pulled backup from GitHub ({size:,} bytes, "
                       f"{outcome['candles_after']:,} candles)")
        return True
    if outcome["candles_before"] > 0:
        # Only reachable outside Actions, where the file survives between runs.
        log("restore", f"local store already holds {outcome['candles_before']:,} candles; "
                       "keeping it")
        return False

    # Nothing came back. Exactly one explanation is safe to continue from: no
    # backup has ever been taken, so there is nothing to lose. Every other one
    # (bad token, wrong repo, unreadable branch) means a backup may well exist,
    # and finishing the run would replace it with this empty database. The
    # engine's own diagnostic is what separates the two — a bare 404 from the
    # contents API cannot, since a missing file and an invisible repository
    # return the same status.
    #
    # What makes it safe is that there is nothing to overwrite, so the two
    # conditions are: the token can see the repository (otherwise "no backup
    # here" is not a claim it is entitled to make) and no backup file is there.
    # Write permission is deliberately NOT required. It is not a safety
    # property — a token that cannot write simply fails at the end of the run,
    # which loses nothing — and the diagnostic reads it from the repository
    # API's `permissions` block, which GitHub's own Actions token under-reports:
    # requiring it here stopped the very first history build on a repository
    # whose backup branch did not exist yet.
    diag = core.github_backup_diagnostic()
    if diag["repo_visible"] and not diag["backup_exists"]:
        log("restore", "no backup exists on GitHub yet; starting a new database")
        if outcome["restored_learning"]:
            log("restore", "  (forward tests and learning were restored from the small backup)")
        if not diag["can_write"]:
            log("restore", "  note: this token does not report write access. If the backup at the "
                           "end of the run fails, that is why — but GitHub's Actions token "
                           "under-reports it, so this is a warning, not a reason to stop.")
        return False

    raise RuntimeError(
        "Could not restore the database backup, and it is not safe to continue: backing up at "
        "the end of this run would overwrite whatever is stored there. GitHub said — "
        + " ".join(str(d) for d in diag["details"][-3:])
    )


def step_token(force=False):
    """Renew the Dhan access token. Dhan expires them every 24h, so a job that
    runs before the market opens keeps the app usable all day without anyone
    pasting a token by hand."""
    if not core._dhan_pin_totp_configured():
        if core._dhan_manual_token_configured():
            log("token", "PIN+TOTP not configured; using the manual DHAN_ACCESS_TOKEN as-is")
            return False
        raise RuntimeError(
            "No Dhan credentials. Set DHAN_CLIENT_ID plus DHAN_PIN and DHAN_TOTP_SECRET "
            "(preferred), or DHAN_ACCESS_TOKEN."
        )
    if not force:
        core._dhan_ensure_fresh_token()
        _tok, issued = core._read_cached_dhan_token()
        log("token", f"token valid (issued {issued})")
        return True

    # A forced renewal must not be able to lose the whole run. Dhan's token
    # endpoint returned a 500 on 8 Sep and the job died on the spot — no sync,
    # no scan, no backup — while a perfectly usable token was sitting in the
    # cache. Mint a fresh one when we can; fall back to the cached one when the
    # provider is having a moment, and only fail when there is nothing to use.
    try:
        core._dhan_generate_fresh_token()
        log("token", "forced a fresh token via PIN+TOTP")
        return True
    except Exception as exc:
        cached, issued = core._read_cached_dhan_token()
        if not cached:
            raise
        age_note = f"issued {issued}" if issued else "age unknown"
        log("token", f"renewal failed ({exc}); continuing on the cached token ({age_note})")
        log("token", "  a cached Dhan token lasts 24h, so this is only a problem if it repeats")
        return False


def step_sync(tickers, tail_days):
    summary = core.sync_latest_sessions(tickers, tail_days=tail_days)
    log("sync", f"{summary['advanced']:,}/{summary['symbols']:,} stocks advanced; "
                f"newest stored session {summary['latest'] or '—'}")
    for err in summary["errors"][:5]:
        log("sync", f"  Dhan error — {err}")
    return summary


def step_resolve():
    """Close any forward test whose stored candles have hit its stop or target.
    This only ever moves a record from ACTIVE to STOP/TARGET with its result;
    nothing is deleted."""
    checked, closed = core.refresh_forward_positions()
    core._metric_set("forward_last_resolved_at", datetime.now().isoformat(timespec="seconds"))
    log("resolve", f"{checked} open position(s) checked, {closed} resolved")
    return checked, closed


def step_scan(tickers, strategies, min_score, session_date=None):
    data = core.load_scan_dataset(tickers)
    if not data:
        raise RuntimeError(
            "The local candle store has no stock with 260+ bars. Build the history once from "
            "the app's Data Manager (SYNC ONLY MISSING DATA) before relying on this job."
        )
    proxy = max(data.values(), key=len)
    regime, regime_score = core.regime_from_index(proxy)
    log("scan", f"{len(data):,} stocks loaded; regime {regime} ({regime_score})")

    stats = {}
    result = core.scan_dataset(data, strategies, regime, stats=stats)
    log("scan", f"{stats['usable']:,} usable; raw signals "
                + ", ".join(f"S{k}={stats['signals'][k]}" for k in sorted(stats["signals"])))

    # Deliberately scanned AFTER the close, on the finished daily candle. An
    # intraday scan can show a signal at 11:00 that is gone by 15:30, which
    # would record forward tests against setups that never actually existed.
    core.persist_scanner_signals(result, min_score, signal_date=session_date)
    log("scan", f"{len(result):,} qualified setup(s) persisted for session {session_date}")
    return result, regime


def step_add(result, min_score, session_date=None):
    if result is None or result.empty:
        log("add", "no qualified setups today; nothing added")
        return 0
    selected = result[result["Score"] >= min_score].copy()
    if selected.empty:
        log("add", f"no setup reached the >={min_score} gate; nothing added")
        return 0
    added = core.add_forward_candidates(selected, signal_date=session_date)
    names = ", ".join(f"{r.Ticker}/{r.Strategy}" for r in selected.itertuples())
    log("add", f"{added} new forward-test candidate(s) from {len(selected)} at/above the gate")
    if added:
        log("add", f"  {names}")
    return added


# Derived tables: rebuilt from the candles on demand, so backing them up costs
# transfer and memory on a host that has little of either and buys nothing.
# feature_snapshots alone is one pickled DataFrame per symbol — 183 KB each,
# 65 MB across a 500-stock universe, which was more than the entire candle
# history it is computed from. The app has to download and unpack the backup on
# every cold start, on an instance with 512 MB of RAM.
BACKUP_SKIP_TABLES = ("feature_snapshots",)


def _stage_backup(stage_path):
    """Write a gzipped copy of the database for the workflow to push.

    Returns (whole MB, kept MB, dropped MB). Works on a copy, so the live
    database keeps its caches.
    """
    import sqlite3

    raw_bytes = os.path.getsize(core.DATA_DB)
    work = f"{stage_path}.staging.sqlite3"
    try:
        shutil.copyfile(core.DATA_DB, work)
        con = sqlite3.connect(work)
        try:
            present = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in BACKUP_SKIP_TABLES:
                if table in present:
                    con.execute(f'DELETE FROM "{table}"')
            con.commit()
            con.execute("VACUUM")      # otherwise the freed pages ride along anyway
        finally:
            con.close()
        kept_bytes = os.path.getsize(work)
        with open(work, "rb") as src, gzip.open(stage_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    finally:
        for leftover in (work, f"{work}-wal", f"{work}-shm", f"{work}-journal"):
            if os.path.exists(leftover):
                os.remove(leftover)
    mb = 1_048_576
    return raw_bytes / mb, kept_bytes / mb, (raw_bytes - kept_bytes) / mb


def backup_or_fail():
    """Back up, and treat a failure as a failed run.

    Everything a run produces lives in the database, and the machine it lives on
    is discarded a minute later — so a run whose backup fails has produced
    nothing, whatever else it did. One such run had already recorded four
    forward-test candidates from a completed scan when GitHub answered the
    upload with a 502; it reported success and the candidates were gone. The
    next scheduled run redoes the work, which is the right outcome, but only if
    this one is honest about having failed.
    """
    if not step_backup():
        raise RuntimeError(
            "The run finished but could NOT be saved, so nothing it did survives. "
            "The backup step above says why."
        )
    return True


def step_backup():
    """Save the database where the next run and the app can find it.

    Two ways out, because the contents API turned out not to be a reliable way
    to store a file this size against this repository. It worked three times and
    then answered every attempt with

        403 {"message":"Timed out validating rule, please try again"}

    — ruleset validation giving up on an 18 MB upload — and retrying three times
    over seven minutes did not help. GitHub's own 422 for an oversized file says
    what to do instead: "Consider creating/updating the file in a local clone
    and pushing it to GitHub."

    So on a runner, which has a clone and a credentialed remote already, the
    database is staged to BACKUP_STAGE_PATH and pushed by git in the next
    workflow step. Everywhere else — the app on its web host, a laptop — there is
    no clone to push from, and the API remains the only option.
    """
    if not core._github_configured():
        log("backup", "GITHUB_TOKEN/GITHUB_REPO not set — SKIPPED, this run will be lost")
        return False

    stage = os.environ.get("BACKUP_STAGE_PATH", "").strip()
    if stage:
        try:
            os.makedirs(os.path.dirname(stage) or ".", exist_ok=True)
            raw_mb, kept_mb, dropped = _stage_backup(stage)
        except Exception as exc:
            log("backup", f"FAILED — could not stage the database: {type(exc).__name__}: {exc}")
            return False
        gz_mb = os.path.getsize(stage) / 1_048_576
        note = f", {dropped:.0f} MB of rebuildable cache left out" if dropped >= 1 else ""
        log("backup", f"staged {kept_mb:.1f} MB of {raw_mb:.1f} MB ({gz_mb:.1f} MB compressed){note} "
                      f"for the workflow to push with git — the run is not saved until that "
                      f"step succeeds")
        return True

    ok, reason = core.backup_db_to_github(return_reason=True)
    log("backup", reason if ok else f"FAILED — {reason}")
    return ok


# ------------------------------------------------------------------ main ----

def run_token_only():
    step_restore()
    step_token(force=True)
    # The token is cached inside the database, so it only survives if the
    # database goes back to GitHub.
    backup_or_fail()
    return {"step": "token", "ok": True}


def run_daily():
    # Market time throughout, never the runner's clock. GitHub runners are UTC,
    # and after 18:30 UTC it is already tomorrow in India — dating a run by the
    # host would put it on the wrong session.
    summary = {"date": str(core.market_today()), "traded": None, "added": 0, "resolved": 0}
    step_restore()
    step_token(force=True)

    session = core.latest_completed_nse_session()
    if session != core.last_expected_nse_session(core.market_today()):
        # Runs before today's close (or on a weekend) target the previous
        # session, which has already been processed.
        log("guard", f"no new completed session to process (latest is {session}); "
                     "syncing and backing up only")

    universes = _universes()
    tickers = core.resolve_universes(universes)
    log("universe", f"{', '.join(universes)} — {len(tickers):,} symbols")

    step_sync(tickers, _env_int("SYNC_TAIL_DAYS", core.LATEST_SYNC_TAIL_DAYS))

    freshness = core.data_freshness_status(tickers)
    stored = freshness["latest"]
    log("fresh", f"stored candles end {stored}, expected {freshness['expected']}")
    summary["traded"] = bool(freshness["current"])
    summary["session"] = str(stored) if stored else None

    checked, closed = step_resolve()
    summary["resolved"] = closed

    # Scan the newest session the store actually HOLDS, not the newest one the
    # calendar expects.
    #
    # This used to refuse unless the two matched, to avoid recording candidates
    # from stale prices. That reasoning was right but the test was wrong: a
    # stored daily candle IS a completed session, whatever the calendar says.
    # Dhan does not reliably publish a session's candle the same evening — on
    # 8 Sep the 17:01 and 19:06 IST runs both found nothing — so the store sits
    # one session behind "expected" for most of a day, and the old test skipped
    # the scan every single time. The forward test recorded nothing at all on a
    # schedule; the only scan that ever landed was one run by hand at an hour
    # when the two happened to agree.
    #
    # Signals are dated by that session rather than by the run, so a scan that
    # happens the next morning still files under the close it was computed
    # from, and re-running is a no-op instead of a duplicate.
    if stored is None:
        log("guard", "the candle store is empty — nothing to scan. Run `daily_job.py bootstrap` "
                     "once to build the history.")
        backup_or_fail()
        return summary

    last_scanned = core._metric_get(LAST_SCANNED_SESSION_KEY)
    if last_scanned == str(stored) and not _env_flag("FORCE_RESCAN"):
        log("guard", f"session {stored} has already been scanned; nothing new to do. "
                     "Set FORCE_RESCAN=1 to scan it again.")
        backup_or_fail()
        return summary

    if not freshness["current"]:
        log("scan", f"the provider has not published {freshness['expected']} yet; scanning the "
                    f"newest session actually stored ({stored}) instead of skipping the day.")

    min_score = _env_int("SCAN_MIN_SCORE", 85)
    result, regime = step_scan(tickers, _selected_strategies(), min_score, session_date=stored)
    summary["added"] = step_add(result, min_score, session_date=stored)
    summary["regime"] = regime
    summary["qualified"] = int(len(result))
    core._metric_set(LAST_SCANNED_SESSION_KEY, str(stored))

    backup_or_fail()
    return summary


def run_bootstrap():
    """Build the candle history from nothing. Run once, by hand.

    The daily job only tops up the newest sessions, and refuses to scan a store
    with no history — correctly, since scanning nothing would record nothing.
    But that leaves no way to get the first history in place on a host too small
    to download it, which is every free tier. This does that job here, where
    there are real cores and no restarts.

    Idempotent: download_prices() fetches only the range each symbol is missing,
    so running it again after a partial run resumes rather than restarting.
    """
    years = _env_int("BOOTSTRAP_YEARS", 3)
    summary = {"years": years}

    step_restore()
    step_token(force=True)

    if _env_flag("REBUILD_CANDLES"):
        removed = _clear_candles()
        summary["rebuilt_from_scratch"] = True
        summary["candles_removed"] = removed
        log("rebuild", f"deleted {removed:,} stored candle(s); every bar will be re-downloaded")

    universes = _universes()
    tickers = core.resolve_universes(universes)
    summary["universes"] = universes
    summary["symbols"] = len(tickers)
    log("universe", f"{', '.join(universes)} — {len(tickers):,} symbols")

    end = core.last_expected_nse_session()
    start = end - timedelta(days=365 * years)
    log("build", f"downloading {start} → {end}. Rate-limited to ~5 requests/second, "
                 f"so expect roughly {len(tickers) * 0.25 / 60:.0f}+ minutes.")

    data = core.sync_missing_backtest_data(tickers, start, end)
    summary["symbols_with_data"] = len(data or {})
    log("build", f"{summary['symbols_with_data']:,}/{len(tickers):,} symbols have history")

    for err in (core._DHAN_LAST_DATA_ERRORS or [])[:5]:
        log("build", f"  Dhan error — {err}")

    status = core.data_freshness_status(tickers)
    summary["latest_session"] = str(status["latest"])
    log("build", f"stored candles end {status['latest']}")

    # Everything above cost real Dhan rate limit; it must not die with the
    # runner. A build whose backup fails has produced nothing at all — the
    # container is thrown away minutes later — so it must not report success:
    # the first full build did exactly that, downloading three years for 500
    # stocks and then exiting 0 after GitHub rejected the upload as too large.
    backup_or_fail()
    return summary


def run_backtest():
    """Replay the strategies over the stored history and record the result.

    This exists because the backtest cannot run where the app runs. On the free
    web instance a Nifty 500 / 1 Year replay pins the CPU at its 0.15-core limit
    and climbs to 535 MB against a 512 MB cap, where it sits until something
    kills it — measured, not guessed. A runner has real cores and 16 GB and gets
    through it.

    It needs no Dhan credentials at all: run_local_backtest() reads the local
    candle store and is documented never to download. The result is written to
    the same tables the app reads, so the Backtest page shows this run as its
    latest without knowing where it happened.
    """
    period = os.environ.get("BACKTEST_PERIOD", "1 Year").strip() or "1 Year"
    threshold = _env_int("BACKTEST_THRESHOLD", 85)
    summary = {"period": period, "threshold": threshold}

    step_restore()

    universes = _universes()
    tickers = core.resolve_universes(universes)
    summary["universes"] = universes
    summary["symbols"] = len(tickers)

    try:
        start, end = core._bt_period(period)
    except KeyError:
        raise RuntimeError(
            f"Unknown BACKTEST_PERIOD {period!r}. Use one of: 6 Months, 1 Year, 2 Years, 3 Years."
        )
    summary["window"] = f"{start} → {end}"
    log("backtest", f"{', '.join(universes)} — {len(tickers):,} symbols, {period} "
                    f"({start} → {end}), score gate {threshold}")

    status = core.local_backtest_status(tickers, start, end)
    ready = int(status.Ready.sum()) if not status.empty else 0
    log("backtest", f"{ready:,}/{len(tickers):,} symbols have enough local history for this window")

    started = time.perf_counter()
    try:
        bt = core.run_local_backtest(tickers, start, end, threshold)
    except RuntimeError as exc:
        if str(exc) == "NO_LOCAL_DATA":
            raise RuntimeError(
                "No local history covers this window. Run the history build first, or pick a "
                "shorter period."
            ) from exc
        raise
    elapsed = time.perf_counter() - started

    trades = int(len(bt)) if bt is not None else 0
    summary["trades"] = trades
    summary["elapsed_seconds"] = round(elapsed, 1)
    log("backtest", f"{trades:,} trade(s) replayed in {elapsed / 60:.1f} minutes")

    if trades:
        wins = int((bt.R > 0).sum())
        summary["win_pct"] = round(wins / trades * 100, 1)
        summary["avg_r"] = round(float(bt.R.mean()), 3)
        summary["total_r"] = round(float(bt.R.sum()), 2)
        log("backtest", f"win rate {summary['win_pct']}%, average {summary['avg_r']}R, "
                        f"{summary['total_r']}R total")

    core._persist_backtest(bt, period, start, end, threshold, len(tickers), elapsed)
    summary["learning_observations_added"] = int(core._learn_from_backtest(bt))
    log("backtest", f"recorded; {summary['learning_observations_added']} learning observation(s) added")

    backup_or_fail()
    return summary


# The research studies, by the name the workflow passes in. Each returns a short
# summary for the run log; all of them persist their full output to the database,
# which is where the app reads them from.
def _log_study_diagnostics(result):
    """Say what happened to every symbol, so 'no signals' can never again mean
    'everything crashed'."""
    diag = getattr(result, "attrs", {}).get("diagnostics") if result is not None else None
    if not diag:
        return
    first = diag.pop("first_failure", None)
    log("study", "  symbols: " + ", ".join(f"{k}={v}" for k, v in diag.items()))
    if first:
        log("study", f"  first failure — {first}")


def _study_raw_signals(data, tickers, start, end):
    """Every S1-S4 signal, ungated — the only way to ask whether the score predicts
    anything, rather than only ever seeing setups that already passed the gate."""
    # run_raw_signal_backtest() persists its own fingerprints on the way out, so
    # this must not persist them again: doing both wrote every signal twice and
    # left 177,890 rows for 88,945 signals — enough to mislead any query that
    # forgets to filter by run_id, and to double the backup for nothing.
    result = core.run_raw_signal_backtest(data, [1, 2, 3, 4], start, end)
    signals = 0 if result is None else len(result)
    _log_study_diagnostics(result)
    summary = {"signals": signals}
    if signals:
        summary["gated_at_85"] = int((result.Score >= 85).sum()) if "Score" in result else None
    return summary


def _study_sl_calibration(data, tickers, start, end):
    """Five stop-placement schemes over the SAME signals and the SAME forward bars,
    which isolates the effect of placement alone."""
    # Persisted inside the study, as above — do not write the rows a second time.
    result = core.run_sl_calibration_study(data, [1, 2, 3, 4], start, end)
    _log_study_diagnostics(result)
    report = core.sl_calibration_report(result)
    if report is not None and not report.empty:
        for row in report.to_dict("records"):
            log("study", "  " + "  ".join(f"{k}={v}" for k, v in row.items()))
    return {"trades": 0 if result is None else len(result),
            "schemes": sorted(core.SL_CALIBRATION_SCHEMES)}


def _study_s4_extension(data, tickers, start, end):
    cal = core.s4_ema20_extension_calibration(data, start, end)
    report = core.s4_extension_bucket_report(cal)
    if report is not None and not report.empty:
        for row in report.to_dict("records"):
            log("study", "  " + "  ".join(f"{k}={v}" for k, v in row.items()))
    return {"signals": 0 if cal is None else len(cal)}


def _study_s4_recovery(data, tickers, start, end):
    result = core.study_s4_recovery_walkforward(data, start, end)
    metrics = core.research_metrics(result) if result is not None else {}
    return {"events": 0 if result is None else len(result),
            "metrics": {str(k): v for k, v in (metrics or {}).items()}}


def _study_win_probability(data, tickers, start, end):
    """Check whether the scanner's Win Probability actually ranks outcomes.

    Reads the already-captured signals rather than re-simulating: they carry the
    features AND what each one went on to do, so this is a fit-and-measure over
    stored evidence, not another walk-forward.
    """
    res = core.win_probability_validation(
        train_frac=_env_float("WINPROB_TRAIN_FRAC", 0.5),
        buckets=_env_int("WINPROB_BUCKETS", 10),
    )
    if not res.get("ok"):
        log("study", f"could not validate: {res.get('reason')}")
        return res

    log("study", f"{res['n_total']:,} signals with outcomes — fit on {res['n_train']:,} "
                 f"({res['train_window'][0]} → {res['train_window'][1]}), "
                 f"tested on {res['n_test']:,} it never saw "
                 f"({res['test_window'][0]} → {res['test_window'][1]})")
    log("study", f"AUC {res['auc']} (0.5 = no better than chance), Brier {res['brier']}, "
                 f"base rate {res['baseline_win_pct']}% wins")
    log("study", "bucket  signals  predicted%  actual%   avg R    total R")
    for b in res["buckets"]:
        log("study", f"  {b['bucket']:>2}   {b['signals']:>7,}   {b['predicted_win_pct']:>8.2f}"
                     f"   {b['actual_win_pct']:>6.2f}  {b['avg_r']:>7.4f}  {b['total_r']:>9.2f}")
    verdict = ("the top bucket is PROFITABLE out of sample"
               if res.get("top_bucket_profitable") else
               "even the highest-probability bucket LOSES money out of sample")
    log("study", f"spread top-minus-bottom {res['spread_r']} R; {verdict}")
    if not res.get("monotonic"):
        log("study", "buckets are not monotonic — the ranking is not clean even where it helps")
    return res


STUDIES = {
    "win_probability": _study_win_probability,
    "raw_signals": _study_raw_signals,
    "sl_calibration": _study_sl_calibration,
    "s4_extension": _study_s4_extension,
    "s4_recovery": _study_s4_recovery,
}


def run_study():
    """One research study over the stored history, on hardware that can finish it.

    Same reason as the backtest: these walk every signal forward over years of
    bars, which the free web instance cannot do. They read local candles only and
    need no Dhan credentials.
    """
    name = os.environ.get("BACKTEST_STUDY", "").strip()
    if name not in STUDIES:
        raise RuntimeError(f"Unknown study {name!r}. Use one of: {', '.join(sorted(STUDIES))}.")

    period = os.environ.get("BACKTEST_PERIOD", "1 Year").strip() or "1 Year"
    summary = {"study": name, "period": period}

    step_restore()

    universes = _universes()
    tickers = core.resolve_universes(universes)
    summary["universes"] = universes
    summary["symbols"] = len(tickers)

    try:
        start, end = core._bt_period(period)
    except KeyError:
        raise RuntimeError(
            f"Unknown BACKTEST_PERIOD {period!r}. Use one of: 6 Months, 1 Year, 2 Years, 3 Years."
        )
    summary["window"] = f"{start} → {end}"
    log("study", f"{name} — {', '.join(universes)}, {len(tickers):,} symbols, "
                 f"{period} ({start} → {end})")

    data = core.load_local_backtest_data(tickers, start, end)
    if not data:
        raise RuntimeError(
            "No local history covers this window. Run the history build first, or pick a "
            "shorter period."
        )
    log("study", f"{len(data):,} symbols loaded")

    started = time.perf_counter()
    summary.update(STUDIES[name](data, tickers, start, end))
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 1)
    log("study", f"{name} finished in {summary['elapsed_seconds'] / 60:.1f} minutes")

    backup_or_fail()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["token", "daily", "bootstrap", "backtest", "study"],
                        help="token = renew the Dhan token only; daily = the full post-close "
                             "run; bootstrap = build the candle history from scratch, once; "
                             "backtest = replay the strategies over the stored history; "
                             "study = one research study, named by BACKTEST_STUDY")
    args = parser.parse_args(argv)

    log("start", f"job={args.job}")
    jobs = {"token": run_token_only, "daily": run_daily, "bootstrap": run_bootstrap,
            "backtest": run_backtest, "study": run_study}
    try:
        summary = jobs[args.job]()
    except Exception:
        log("FAILED", "the job did not complete:")
        traceback.print_exc()
        return 1
    log("done", json.dumps(summary, default=str))

    # Surface the outcome in the workflow's step summary when running in Actions.
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as fh:
                fh.write(f"### {args.job} run — {datetime.now():%d %b %Y %H:%M}\n\n")
                for k, v in summary.items():
                    fh.write(f"- **{k}**: {v}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
