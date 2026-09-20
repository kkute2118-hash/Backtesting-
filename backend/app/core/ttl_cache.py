"""A tiny TTL cache for read endpoints, with explicit invalidation.

The dashboard fires several requests at once and each one re-reads the same
SQLite tables. On a one-instance free plan that contention is most of the
latency, and the underlying answers change at most once per scan - so a few
seconds of staleness costs nothing and a cache hit costs nothing at all.

Deliberately NOT used for anything a scan selects or scores: this caches
whole endpoint responses, and every entry is dropped when a scan or a forward
resolve finishes, so a stale reading can never outlive the event that changed
it.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

_LOCK = threading.RLock()
_STORE: dict[str, tuple[float, Any]] = {}
_STATS = {"hits": 0, "misses": 0, "invalidations": 0}


def cached(key: str, ttl: float, build: Callable[[], Any]) -> Any:
    """Return the cached value for `key`, building it if missing or expired.

    `build` runs OUTSIDE the lock: it reads SQLite and can take seconds, and
    holding the lock across it would serialise exactly the concurrent
    dashboard requests this exists to speed up. Two callers racing on a cold
    key both build, which is wasteful once and correct always.
    """
    now = time.time()
    with _LOCK:
        hit = _STORE.get(key)
        if hit is not None and (now - hit[0]) < ttl:
            _STATS["hits"] += 1
            return hit[1]
        _STATS["misses"] += 1
    value = build()
    with _LOCK:
        _STORE[key] = (time.time(), value)
    return value


def invalidate(*prefixes: str) -> int:
    """Drop cached entries whose key starts with any of `prefixes`.

    No prefixes drops everything. Called when a scan or a resolve finishes,
    so the next read reflects it rather than waiting out a TTL.
    """
    with _LOCK:
        if not prefixes:
            dropped = len(_STORE)
            _STORE.clear()
        else:
            keys = [k for k in _STORE if k.startswith(prefixes)]
            for k in keys:
                _STORE.pop(k, None)
            dropped = len(keys)
        _STATS["invalidations"] += dropped
    return dropped


def stats() -> dict[str, Any]:
    with _LOCK:
        return {"entries": len(_STORE), **_STATS}
