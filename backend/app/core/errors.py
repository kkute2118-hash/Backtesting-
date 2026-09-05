"""One error vocabulary for the API.

Every provider failure inside the engine surfaces as a bare ``RuntimeError``
with a message written for a human. The handlers here turn those into a stable
JSON envelope so the frontend can show something understandable instead of a
stack trace, and so a missing credential reads as 503 (fix your configuration)
rather than 500 (the server is broken).
"""

from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

log = logging.getLogger("ati.api")


class ApiError(Exception):
    """A failure with a message that is safe and useful to show a user."""

    def __init__(self, message: str, *, status_code: int = 400,
                 code: str = "error", detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.detail = detail


class NotConfigured(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         code="not_configured")


class NotFound(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=status.HTTP_404_NOT_FOUND, code="not_found")


class UpstreamError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=status.HTTP_502_BAD_GATEWAY, code="upstream_error")


def _envelope(code: str, message: str, detail: str | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if detail:
        body["error"]["detail"] = detail
    return body


def install_error_handlers(app: FastAPI) -> None:
    from app.engine.core import DatabaseUnavailable, DhanNoDataError

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content=_envelope(exc.code, exc.message, exc.detail))

    @app.exception_handler(DatabaseUnavailable)
    async def _db_error(_: Request, exc: DatabaseUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope("database_unavailable", str(exc)),
        )

    @app.exception_handler(DhanNoDataError)
    async def _no_data(_: Request, exc: DhanNoDataError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_envelope("no_data", str(exc)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The engine raises RuntimeError with human-readable text for every
        # provider problem, so that text is worth showing. Anything else is a
        # real defect and must not leak its traceback to the browser.
        log.error("Unhandled error on %s %s\n%s", request.method, request.url.path,
                  traceback.format_exc())
        if isinstance(exc, RuntimeError) and str(exc):
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content=_envelope("upstream_error", str(exc)),
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error",
                              "Something went wrong on the server. Please try again."),
        )
