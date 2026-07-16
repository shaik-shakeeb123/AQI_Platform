"""Centralized exception hierarchy and FastAPI exception handlers.

All domain-specific errors inherit from :class:`AppException` so they can
be caught by a single FastAPI exception handler and returned as structured
JSON responses.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── Base Exception ──────────────────────────────────────────────────────────


class AppException(Exception):
    """Base exception for all application-level errors.

    Attributes:
        status_code: HTTP status code to return to the client.
        detail: Human-readable error description.
        error_code: Machine-readable error code for programmatic handling.
    """

    def __init__(
        self,
        detail: str = "An unexpected error occurred.",
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        upstream_status: int | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        self.error_code = error_code
        self.upstream_status = upstream_status
        super().__init__(self.detail)


# ── Concrete Exceptions ────────────────────────────────────────────────────


class NotFoundException(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(
        self,
        detail: str = "Resource not found.",
        error_code: str = "NOT_FOUND",
    ) -> None:
        super().__init__(detail=detail, status_code=404, error_code=error_code)


class ExternalAPIException(AppException):
    """Raised when an external API call (OpenAQ / Open-Meteo) fails."""

    def __init__(
        self,
        detail: str = "External API request failed.",
        error_code: str = "EXTERNAL_API_ERROR",
        status_code: int = 502,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(
            detail=detail, 
            status_code=status_code, 
            error_code=error_code, 
            upstream_status=upstream_status
        )


class DuplicateException(AppException):
    """Raised when an entity with the same unique constraint already exists."""

    def __init__(
        self,
        detail: str = "Resource already exists.",
        error_code: str = "DUPLICATE_RESOURCE",
    ) -> None:
        super().__init__(detail=detail, status_code=409, error_code=error_code)


class DatabaseException(AppException):
    """Raised when a database operation fails unexpectedly."""

    def __init__(
        self,
        detail: str = "A database error occurred.",
        error_code: str = "DATABASE_ERROR",
    ) -> None:
        super().__init__(detail=detail, status_code=500, error_code=error_code)


# ── FastAPI Exception Handlers ─────────────────────────────────────────────


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle all :class:`AppException` subclasses and return a structured
    JSON error response.
    """
    logger.error(
        "AppException — status=%s error_code=%s detail=%s path=%s upstream_status=%s",
        exc.status_code,
        exc.error_code,
        exc.detail,
        request.url.path,
        exc.upstream_status,
    )
    
    error_payload = {
        "code": exc.error_code,
        "message": exc.detail,
        "path": request.url.path,
    }
    if exc.upstream_status is not None:
        error_payload["upstream_status"] = exc.upstream_status

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error_payload},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions.

    Logs the full traceback and returns a generic *500* response so that
    internal details are never leaked to the client.
    """
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected internal error occurred.",
                "path": request.url.path,
            }
        },
    )
