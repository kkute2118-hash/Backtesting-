"""Shared-secret guard and rate limiting for state-changing requests.

Read endpoints stay open - this is research output, and locking them would
break the app for its own frontend. Anything that SPENDS something needs the
key: a scan burns minutes of CPU on a single shared instance, a sync burns a
rate-limited Dhan budget, and watchlist and settings writes change what the
owner sees.

Implemented as middleware rather than a per-route dependency on purpose. A
dependency has to be remembered on every new route; middleware cannot be
forgotten, and a route added next month is guarded by default.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("ati.guard")

HEADER = "X-API-Key"
GUARDED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths that change nothing and are called by the browser on every load.
OPEN_PATHS = ("/health", "/docs", "/openapi.json", "/redoc")

# Requests per window, per client, for the two genuinely expensive actions.
# Deliberately generous: this is a brake on a runaway loop or a bored
# stranger, not a quota for the owner.
EXPENSIVE_PREFIXES = ("/api/v1/scan", "/api/v1/sepa", "/api/v1/custom-strategy",
                      "/api/v1/data/sync", "/api/v1/market/sector-sync",
                      "/api/v1/market/index-sync", "/api/v1/backtest")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_WINDOW", "10"))
RATE_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

_LOCK = threading.Lock()
_HITS: dict[str, list[float]] = {}


def access_key() -> str:
    """The configured key, or "" when the guard is off.

    Read per request rather than captured at import so the key can be rotated
    by restarting the service without a code change.
    """
    return (os.environ.get("API_ACCESS_KEY") or "").strip()


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(key: str) -> bool:
    now = time.time()
    with _LOCK:
        hits = [t for t in _HITS.get(key, []) if now - t < RATE_WINDOW_SECONDS]
        if len(hits) >= RATE_LIMIT:
            _HITS[key] = hits
            return True
        hits.append(now)
        _HITS[key] = hits
        # Bound the dictionary: one entry per client per window, and nothing
        # prunes it otherwise.
        if len(_HITS) > 512:
            for k in [k for k, v in _HITS.items()
                      if not v or now - max(v) > RATE_WINDOW_SECONDS * 4]:
                _HITS.pop(k, None)
    return False


async def guard_middleware(request: Request, call_next):
    path = request.url.path
    if request.method in GUARDED_METHODS and not path.startswith(OPEN_PATHS):
        configured = access_key()
        if configured:
            supplied = request.headers.get(HEADER, "")
            # compare_digest: a plain == leaks the key one character at a time
            # to anyone who can measure the response.
            import hmac
            if not supplied or not hmac.compare_digest(supplied, configured):
                # The key itself is never logged, and the body never echoes
                # what was sent.
                log.warning("Rejected %s %s: missing or wrong API key", request.method, path)
                return JSONResponse(
                    status_code=401,
                    content={"code": "unauthorized",
                             "message": "This action needs the API access key. Set "
                                        "API_ACCESS_KEY on the server and send it as the "
                                        f"{HEADER} header."},
                )
        elif path.startswith(EXPENSIVE_PREFIXES):
            # Said once per process, not per request.
            _warn_unguarded()

    if request.method in GUARDED_METHODS and path.startswith(EXPENSIVE_PREFIXES):
        if _rate_limited(_client(request)):
            return JSONResponse(
                status_code=429,
                content={"code": "rate_limited",
                         "message": f"Too many requests. This endpoint allows {RATE_LIMIT} "
                                    f"every {RATE_WINDOW_SECONDS} seconds."},
                headers={"Retry-After": str(RATE_WINDOW_SECONDS)},
            )
    return await call_next(request)


_WARNED = False


def _warn_unguarded() -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        log.warning("API_ACCESS_KEY is not set: scans and syncs are open to anyone who "
                    "can reach this server.")


def reset_rate_limit() -> None:
    """Test hook. Nothing in the app clears the window."""
    with _LOCK:
        _HITS.clear()
