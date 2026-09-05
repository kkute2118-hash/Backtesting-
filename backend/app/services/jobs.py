"""Background job runner for the long engine operations.

A scan of the full NSE cash list reads ~2,000 candle histories, computes
multi-timeframe features for each and evaluates four strategies over them. That
is minutes of CPU, not milliseconds, so it can never be the body of an HTTP
request: the browser would time out and a page reload would start it again.

Every such operation is therefore a job:

    POST .../runs      -> 202 with a job id
    GET  /jobs/{id}    -> queued | running (+progress) | succeeded | failed
    GET  .../runs/{id} -> the result, once it exists

Jobs run in a small thread pool. The engine releases the GIL inside pandas and
numpy, and the work is I/O-bound on SQLite besides, so threads are the right
tool here - and they keep the engine's module-level caches and its rate-limit
lock shared, which separate processes would not.

Results are written to ``app_scan_runs`` as well as held in memory, so a
finished scan survives a server restart and can be reopened by URL.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.core.config import get_settings
from app.core.errors import NotFound
from app.db import app_store

log = logging.getLogger("ati.jobs")

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = {SUCCEEDED, FAILED, CANCELLED}


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: str = QUEUED
    progress: float = 0.0
    message: str = "Queued"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    request: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": round(float(self.progress), 4),
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "request": self.request,
        }


class JobHandle:
    """What a job function is given: progress reporting plus a cancel check."""

    def __init__(self, job: Job) -> None:
        self._job = job

    @property
    def id(self) -> str:
        return self._job.id

    @property
    def cancelled(self) -> bool:
        return self._job._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled(self._job.id)

    def progress(self, fraction: float, message: str | None = None) -> None:
        self._job.progress = max(0.0, min(1.0, float(fraction)))
        if message:
            self._job.message = message
        self.raise_if_cancelled()

    def status(self, message: str) -> None:
        self._job.message = message


class JobCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobRegistry:
    def __init__(self) -> None:
        settings = get_settings()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.job_workers), thread_name_prefix="ati-job"
        )
        self._retention = timedelta(minutes=settings.job_retention_minutes)

    # -- submission -------------------------------------------------------- #
    def submit(self, kind: str, label: str, fn: Callable[[JobHandle], Any], *,
               request: dict[str, Any] | None = None,
               persist: bool = False) -> Job:
        job = Job(id=uuid.uuid4().hex[:16], kind=kind, label=label,
                  created_at=_now(), request=request or {})
        with self._lock:
            self._prune_locked()
            self._jobs[job.id] = job
        if persist:
            _persist_run_created(job)
        self._pool.submit(self._run, job, fn, persist)
        return job

    def _run(self, job: Job, fn: Callable[[JobHandle], Any], persist: bool) -> None:
        job.status = RUNNING
        job.started_at = _now()
        job.message = "Running"
        handle = JobHandle(job)
        try:
            job.result = fn(handle)
            job.status = SUCCEEDED
            job.progress = 1.0
            job.message = "Complete"
        except JobCancelled:
            job.status = CANCELLED
            job.message = "Cancelled"
        except Exception as exc:  # noqa: BLE001 - the message is the product here
            job.status = FAILED
            job.error = str(exc) or exc.__class__.__name__
            job.message = "Failed"
            log.error("Job %s (%s) failed: %s\n%s", job.id, job.kind, exc,
                      traceback.format_exc())
        finally:
            job.finished_at = _now()
            if persist:
                _persist_run_finished(job)

    # -- lookup ------------------------------------------------------------ #
    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"Job {job_id} is not known. It may have expired.")
        return job

    def find(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in TERMINAL:
            return job
        job._cancel.set()
        job.message = "Cancelling"
        return job

    def _prune_locked(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._retention
        for job_id, job in list(self._jobs.items()):
            if job.status not in TERMINAL or not job.finished_at:
                continue
            try:
                finished = datetime.fromisoformat(job.finished_at)
            except ValueError:
                continue
            if finished < cutoff:
                self._jobs.pop(job_id, None)


# --------------------------------------------------------------------------- #
# run persistence
# --------------------------------------------------------------------------- #
def _persist_run_created(job: Job) -> None:
    try:
        con = app_store.connect()
        try:
            con.execute(
                """INSERT OR REPLACE INTO app_scan_runs
                       (id, kind, created_at, status, request)
                   VALUES(?,?,?,?,?)""",
                (job.id, job.kind, job.created_at, job.status, json.dumps(job.request)),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        log.warning("Could not record run %s", job.id, exc_info=True)


def _persist_run_finished(job: Job) -> None:
    result = job.result if isinstance(job.result, dict) else {}
    rows = result.get("rows") or []
    stats = result.get("stats") or {}
    try:
        con = app_store.connect()
        try:
            con.execute(
                """UPDATE app_scan_runs
                      SET status=?, finished_at=?, stats=?, error=?, row_count=?, results=?
                    WHERE id=?""",
                (job.status, job.finished_at, json.dumps(stats, default=str),
                 job.error, len(rows), json.dumps(result, default=str), job.id),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        log.warning("Could not persist run %s", job.id, exc_info=True)


def load_run(run_id: str) -> dict[str, Any] | None:
    con = app_store.connect()
    try:
        row = con.execute("SELECT * FROM app_scan_runs WHERE id=?", (run_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    record = dict(row)
    for key in ("request", "stats", "results"):
        raw = record.get(key)
        if raw:
            try:
                record[key] = json.loads(raw)
            except (TypeError, ValueError):
                record[key] = None
    return record


def list_runs(kind: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    con = app_store.connect()
    try:
        if kind:
            rows = con.execute(
                """SELECT id,kind,created_at,finished_at,status,request,row_count,error
                     FROM app_scan_runs WHERE kind=? ORDER BY created_at DESC LIMIT ?""",
                (kind, int(limit)),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT id,kind,created_at,finished_at,status,request,row_count,error
                     FROM app_scan_runs ORDER BY created_at DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
    finally:
        con.close()
    out = []
    for row in rows:
        record = dict(row)
        try:
            record["request"] = json.loads(record["request"]) if record["request"] else {}
        except (TypeError, ValueError):
            record["request"] = {}
        out.append(record)
    return out


registry = JobRegistry()
