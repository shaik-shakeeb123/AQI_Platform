"""Centralized logging configuration.

Call :func:`configure_logging` once at application startup to set up
structured logging for the entire application, including Uvicorn's own
loggers.  Use :func:`get_logger` to obtain a named logger in any module.
"""

import logging
import sys
from typing import Callable

from api_layer.config import get_settings


class StructuredFormatter(logging.Formatter):
    """A log formatter that outputs lines in the format:

    ``timestamp | LEVEL | logger_name | message``
    """

    FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self.FORMAT, datefmt=self.DATE_FORMAT)


def configure_logging() -> Callable[[str], logging.Logger]:
    """Set up structured logging for the application.

    * Applies :class:`StructuredFormatter` to every handler.
    * Configures the **root** logger and Uvicorn's ``uvicorn``,
      ``uvicorn.access``, and ``uvicorn.error`` loggers.

    Returns:
        A :func:`get_logger` callable so callers can conveniently create
        named loggers after configuration is complete.
    """
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = StructuredFormatter()

    # ── Root logger ─────────────────────────────────────────────────────
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any pre-existing handlers to avoid duplicate output.
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ── Uvicorn loggers ─────────────────────────────────────────────────
    for uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(console_handler)
        uv_logger.setLevel(level)
        uv_logger.propagate = False

    root_logger.info("Logging configured — level=%s", settings.LOG_LEVEL)

    return get_logger


def get_logger(name: str) -> logging.Logger:
    """Return a :class:`logging.Logger` with the given *name*.

    This is a thin convenience wrapper around :func:`logging.getLogger` to
    keep a single import path across the project.
    """
    return logging.getLogger(name)


# Module-level convenience logger for this module itself.
logger: logging.Logger = get_logger(__name__)
