"""Prefab logging helpers for DUUI Python components.

Each ``log_*`` function builds a structured record — level, message, optional timestamp
and stacktrace — appends it to the current request's log buffer (so the middleware can
return it to Java on the response), and echoes it through the stdlib :mod:`logging`
framework so it stays visible in the tool's own container output (falling back to a plain
stderr print when no logging handler is configured). The DUUI level is mapped to the
nearest stdlib level for that echo (``TRACE`` has no stdlib equivalent, so it shows at
``INFO``), but the record buffered for Java always keeps its true DUUI level. Every helper
also returns the :class:`~duui_logging.records.LogRecord` it emitted.

Correlation (which component / which document) is added by the Java side, which already
knows both — so the tool does not need to send them.

Stacktraces come in two flavours:

* ``withException`` (default on for ``error`` / ``critical``): if the call happens while an
  exception is being handled (inside an ``except`` block), the real exception traceback is
  attached — the most useful thing when something breaks.
* ``withStacktrace`` (an ``int``): attach the current *call stack* (via :func:`where_am_i`)
  showing where the log call was made, even when there is no exception. ``0`` disables it;
  any value ``> 0`` enables it and is the number of most-recent frames to include.

If both are requested, an active exception traceback wins.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from enum import Enum
from typing import Optional

from . import context
from .records import LogRecord


class ErrorLevel(str, Enum):
    """Log severity levels (names match what the Java receiver understands)."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# DUUI level -> stdlib logging level for *local display*. stdlib has no TRACE, so TRACE is
# surfaced at INFO (kept visible under a normal INFO config); this only affects what the
# container prints — the record buffered for Java keeps its true DUUI level.
_DISPLAY_LEVEL = {
    ErrorLevel.TRACE.value: logging.INFO,
    ErrorLevel.DEBUG.value: logging.DEBUG,
    ErrorLevel.INFO.value: logging.INFO,
    ErrorLevel.WARN.value: logging.WARNING,
    ErrorLevel.ERROR.value: logging.ERROR,
    ErrorLevel.CRITICAL.value: logging.CRITICAL,
}


def _echo(level_name: str, logger_name: str, message: str, stacktrace: Optional[str]) -> None:
    """Show a record in the container's own output via the stdlib :mod:`logging` framework.

    Routes through ``logging.getLogger(logger_name)`` so tools can filter and format these
    like any other log. The emission is tagged so the :class:`DUUICollectHandler` ignores it
    (the caller already buffered the precise record for Java). When no logging handler is
    configured — a standalone run that never called :func:`install` or ``basicConfig`` — it
    falls back to a plain stderr print so the line still shows.
    """
    text = message if not stacktrace else f"{message}\n{stacktrace}"
    py_logger = logging.getLogger(logger_name or "duui")
    if py_logger.hasHandlers():
        py_logger.log(
            _DISPLAY_LEVEL.get(level_name, logging.INFO),
            text,
            extra={context.SKIP_COLLECT_ATTR: True},
        )
    else:
        print(f"[{level_name}] {logger_name}: {text}", file=sys.stderr, flush=True)


def where_am_i(depth: int = 1, _skip: int = 0) -> str:
    """Return the current call stack (innermost first), excluding this frame.

    :param depth: how many of the most recent frames to include; ``<= 0`` means all.
    :param _skip: internal — extra caller frames to drop (used when called via ``_emit``).
    """
    frames = traceback.extract_stack()[: -(1 + _skip)]  # drop where_am_i (+ internal wrappers)
    if depth and depth > 0:
        frames = frames[-depth:]
    return "\n".join(f"{f.name} ({f.filename}:{f.lineno})" for f in reversed(frames))


def current_exception_trace() -> Optional[str]:
    """Return the traceback of the exception currently being handled, or ``None``."""
    exc = sys.exc_info()[1]
    if exc is None:
        return None
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ).rstrip()


def _resolve_timestamp(withTimeStamp: "bool | int | None") -> Optional[int]:
    """Turn the ``withTimeStamp`` argument into an epoch-millis value or ``None``.

    ``True`` means "now"; ``False``/``None`` means no timestamp; any other number is used
    verbatim as an epoch-millis value (letting the caller set a custom timestamp).

    ``bool`` is a subclass of ``int`` in Python, so booleans are checked with ``is`` before
    the numeric branch — otherwise ``True`` would be treated as the timestamp ``1``.
    """
    if withTimeStamp is True:
        return int(time.time() * 1000)
    if withTimeStamp is False or withTimeStamp is None:
        return None
    return int(withTimeStamp)


def _emit(
    level: ErrorLevel,
    message: str,
    *,
    withTimeStamp: "bool | int | None",
    withStacktrace: int,
    withException: bool,
    logger: str = "",
) -> LogRecord:
    """Build, echo and buffer a single record. Shared by every ``log_*`` helper.

    ``withStacktrace`` is an ``int``: ``0`` (or negative) means no call stack; any value
    ``> 0`` attaches that many of the most-recent frames.
    """
    stacktrace: Optional[str] = None
    if withException:
        stacktrace = current_exception_trace()
    if stacktrace is None and withStacktrace > 0:
        stacktrace = where_am_i(withStacktrace, _skip=1)  # drop the _emit frame

    # No explicit logger: fall back to the process-wide default (the file that installed
    # the middleware, if it used add_logging(); otherwise "duui").
    if not logger:
        logger = context.get_default_logger()

    record = LogRecord(
        level=level.value,
        message=message,
        logger=logger,
        stacktrace=stacktrace,
        timestamp=_resolve_timestamp(withTimeStamp),
    )

    # Buffered for return to Java on the response (no-op outside a collecting request). Uses
    # the true DUUI level, so TRACE stays TRACE regardless of how it is displayed below.
    context.collect(record)

    # Local visibility via the stdlib logging framework (mapped level; deduped for Java).
    _echo(record.level, logger, message, stacktrace)

    return record


def log_trace(message: str = "", withTimeStamp: "bool | int" = True, withException: bool = False, withStacktrace: int = 20,
              logger: str = "") -> LogRecord:
    """Log a trace message."""
    return _emit(ErrorLevel.TRACE, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)


def log_debug(message: str, withTimeStamp: "bool | int" = True, withException: bool = False, withStacktrace: int = 0,
              logger: str = "") -> LogRecord:
    """Log a debug message."""
    return _emit(ErrorLevel.DEBUG, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)


def log_info(message: str, withTimeStamp: "bool | int" = True, withException: bool = False, withStacktrace: int = 0,
             logger: str = "") -> LogRecord:
    """Log an info message."""
    return _emit(ErrorLevel.INFO, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)


def log_warn(message: str, withTimeStamp: "bool | int" = True, withException: bool = False, withStacktrace: int = 0,
             logger: str = "") -> LogRecord:
    """Log a warning message."""
    return _emit(ErrorLevel.WARN, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)


# Alias for callers that prefer the full word.
log_warning = log_warn


def log_error(message: str, withTimeStamp: "bool | int" = True, withException: bool = True, withStacktrace: int = 0,
              logger: str = "") -> LogRecord:
    """Log an error. Inside an ``except`` block the exception traceback is attached."""
    return _emit(ErrorLevel.ERROR, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)


def log_critical(message: str, withTimeStamp: "bool | int" = True, withException: bool = True, withStacktrace: int = 20,
                logger: str = "") -> LogRecord:
    """Log a critical error. Attaches the exception traceback if one is active."""
    return _emit(ErrorLevel.CRITICAL, message, withTimeStamp=withTimeStamp,
                 withStacktrace=withStacktrace, withException=withException, logger=logger)
