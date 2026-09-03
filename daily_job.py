#!/usr/bin/env python3
"""Scheduled, headless runner for the Adaptive Trading Intelligence Lab.

Streamlit Cloud only executes the app while somebody has it open, so nothing in
app.py can keep the forward test running on its own. This script drives the same
engine (core.py) from GitHub Actions instead, on a cron schedule, with the app
closed.

    python daily_job.py token     # renew the Dhan access token only
    python daily_job.py daily     # full post-close run
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
               SCAN_UNIVERSE     default "Nifty 500"
               SCAN_STRATEGIES   default "1,2,3,4"
               SCAN_MIN_SCORE    default "85"
               SYNC_TAIL_DAYS    default core.LATEST_SYNC_TAIL_DAYS

GitHub refuses to create secrets or variables whose NAME starts with "GITHUB_",
so the backup settings are read from the non-reserved aliases above (the
original GITHUB_TOKEN / GITHUB_REPO names still work in Streamlit Secrets).
"""

import argparse
import json
import os
import sys
import traceback
from datetime import date, datetime, timedelta

# Import the engine, not the UI. core.py runs no Streamlit commands at import.
import core


def log(step, message):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {step:<8} {message}", flush=True)


def _env_int(name, default):
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def _selected_strategies():
    raw = os.environ.get("SCAN_STRATEGIES", "1,2,3,4")
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if part in {"1", "2", "3", "4"} and int(part) not in out:
            out.append(int(part))
    return out or [1, 2, 3, 4]


def _universes():
    raw = os.environ.get("SCAN_UNIVERSE", "Nifty 500")
    valid = {"Nifty 500", "Nifty Smallcap 100", "Nifty Smallcap 250", "Nifty Midcap 150"}
    out = [u.strip() for u in str(raw).split("|") if u.strip() in valid]
    return out or ["Nifty 500"]


# ----------------------------------------------------------------- steps ----

def step_restore():
    """Pull the last database backup. The runner's filesystem starts empty on
    every job, so without this the run would build a brand-new database and the
    backup at the end would overwrite the real one with it."""
    if not core._github_configured():
        raise RuntimeError(
            "The GitHub backup is not configured (GH_BACKUP_TOKEN / GH_REPO). The database "
            "cannot be restored, and continuing would push an empty database over your saved "
            "forward tests."
        )
    restored = core.restore_db_from_github()
    if restored:
        size = os.path.getsize(core.DATA_DB)
        log("restore", f"pulled backup from GitHub ({size:,} bytes)")
    elif os.path.exists(core.DATA_DB) and os.path.getsize(core.DATA_DB) > 0:
        log("restore", "local database already present, keeping it")
    else:
        # First ever run: no backup exists yet. Safe — there is nothing to lose.
        # Anything else (bad token, wrong repo, missing branch) is recorded by
        # the engine, and is NOT safe to ignore: continuing would back an empty
        # database up over the real one.
        why = core._GITHUB_LAST_ERROR
        if why:
            raise RuntimeError(
                f"Could not restore the database backup: {why} — refusing to continue, because "
                "backing up now would overwrite your saved forward tests with an empty database."
            )
        log("restore", "no backup found on GitHub; starting a new database")
    return restored


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
    if force:
        core._dhan_generate_fresh_token()
        log("token", "forced a fresh token via PIN+TOTP")
    else:
        core._dhan_ensure_fresh_token()
        _tok, issued = core._read_cached_dhan_token()
        log("token", f"token valid (issued {issued})")
    return True


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


def step_scan(tickers, strategies, min_score):
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
    core.persist_scanner_signals(result, min_score)
    log("scan", f"{len(result):,} qualified setup(s) persisted")
    return result, regime


def step_add(result, min_score):
    if result is None or result.empty:
        log("add", "no qualified setups today; nothing added")
        return 0
    selected = result[result["Score"] >= min_score].copy()
    if selected.empty:
        log("add", f"no setup reached the >={min_score} gate; nothing added")
        return 0
    added = core.add_forward_candidates(selected)
    names = ", ".join(f"{r.Ticker}/{r.Strategy}" for r in selected.itertuples())
    log("add", f"{added} new forward-test candidate(s) from {len(selected)} at/above the gate")
    if added:
        log("add", f"  {names}")
    return added


def step_backup():
    if not core._github_configured():
        log("backup", "GITHUB_TOKEN/GITHUB_REPO not set — SKIPPED, this run will be lost")
        return False
    ok, reason = core.backup_db_to_github(return_reason=True)
    log("backup", reason if ok else f"FAILED — {reason}")
    return ok


# ------------------------------------------------------------------ main ----

def run_token_only():
    step_restore()
    step_token(force=True)
    # The token is cached inside the database, so it only survives if the
    # database goes back to GitHub.
    step_backup()
    return {"step": "token", "ok": True}


def run_daily():
    summary = {"date": str(date.today()), "traded": None, "added": 0, "resolved": 0}
    step_restore()
    step_token(force=True)

    session = core.latest_completed_nse_session()
    if session != core.last_expected_nse_session(date.today()):
        # Runs before today's close (or on a weekend) target the previous
        # session, which has already been processed.
        log("guard", f"no new completed session to process (latest is {session}); "
                     "syncing and backing up only")

    universes = _universes()
    tickers = sorted({t for u in universes for t in core.index_universe(u)})
    log("universe", f"{', '.join(universes)} — {len(tickers):,} symbols")

    step_sync(tickers, _env_int("SYNC_TAIL_DAYS", core.LATEST_SYNC_TAIL_DAYS))

    freshness = core.data_freshness_status(tickers)
    log("fresh", f"stored candles end {freshness['latest']}, expected {freshness['expected']}")
    summary["traded"] = bool(freshness["current"])

    if not freshness["current"]:
        # Dhan sometimes publishes the daily candle late. Scanning on a stale
        # cache would record forward tests against yesterday's prices, which is
        # exactly the late-entry problem this job exists to avoid.
        log("guard", "candles are not current for the latest expected session — "
                     "SKIPPING the scan so no candidate is recorded from stale prices")
        checked, closed = step_resolve()
        summary["resolved"] = closed
        step_backup()
        return summary

    checked, closed = step_resolve()
    summary["resolved"] = closed

    min_score = _env_int("SCAN_MIN_SCORE", 85)
    result, regime = step_scan(tickers, _selected_strategies(), min_score)
    summary["added"] = step_add(result, min_score)
    summary["regime"] = regime
    summary["qualified"] = int(len(result))

    step_backup()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["token", "daily"],
                        help="token = renew the Dhan token only; daily = the full post-close run")
    args = parser.parse_args(argv)

    log("start", f"job={args.job}")
    try:
        summary = run_token_only() if args.job == "token" else run_daily()
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
