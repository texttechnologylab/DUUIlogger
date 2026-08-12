"""Bridge the standard-library :mod:`logging` framework into the DUUI collect buffer.

Two things stay out of scope, by nature of the mechanism:

* **Raw ``print(...)`` / direct writes to stdout** bypass the logging framework entirely,
  so there is nothing to hook — they remain container-local only.
* **Logs emitted outside a collect-enabled request** — one Java marked with the
  ``DUUI-Log-Collect`` header, e.g. ``/v1/process`` — happen with no active buffer (import
  time, startup), so ``context.collect`` no-ops and they stay in container stderr only.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from . import context
from .records import LogRecord

# stdlib logging has no CRITICAL-vs-ERROR-vs... string; map by numeric level, most severe
# first, so custom/in-between levels still resolve to the nearest DUUI level.
_LEVEL_THRESHOLDS = (
    (logging.CRITICAL, "CRITICAL"),
    (logging.ERROR, "ERROR"),
    (logging.WARNING, "WARN"),
    (logging.INFO, "INFO"),
    (logging.DEBUG, "DEBUG"),
)

# Formats exc_info tuples the same way logging itself would.
_EXC_FORMATTER = logging.Formatter()


def _level_name(levelno: int) -> str:
    """Map a numeric stdlib level to the closest DUUI level name."""
    for threshold, name in _LEVEL_THRESHOLDS:
        if levelno >= threshold:
            return name
    return "TRACE"


class DUUICollectHandler(logging.Handler):
    """Forward stdlib log records into the current request's DUUI buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        # Records the log_* helpers emitted for local display only: they already buffered
        # their own precise record, so re-collecting here would duplicate them (at a
        # possibly-remapped level). Skip them.
        if getattr(record, context.SKIP_COLLECT_ATTR, False):
            return
        try:
            stacktrace: Optional[str] = None
            if record.exc_info:
                stacktrace = _EXC_FORMATTER.formatException(record.exc_info)

            context.collect(
                LogRecord(
                    level=_level_name(record.levelno),
                    message=record.getMessage(),
                    logger=record.name,
                    stacktrace=stacktrace,
                    timestamp=int(record.created * 1000),
                )
            )
        except Exception:  # never let logging bring the request down
            self.handleError(record)


def install(
    level: int = logging.INFO,
    *,
    capture_warnings: bool = True,
    keep_stderr: bool = True,
) -> DUUICollectHandler:
    """Route stdlib logging (and optionally :mod:`warnings`) into the DUUI buffer.

    Call once at tool startup.

    :param level: minimum level the root logger will process (records below it never reach
        any handler, ours included).
    :param capture_warnings: also route :func:`warnings.warn` through logging (the classic
        "deprecated / out of date version" path) via :func:`logging.captureWarnings`.
    :param keep_stderr: print the collected logs to container stderr as well as forwarding them to Java.
    :returns: the installed :class:`DUUICollectHandler`.
    """
    root = logging.getLogger()

    existing = next(
        (h for h in root.handlers if isinstance(h, DUUICollectHandler)), None
    )
    handler = existing or DUUICollectHandler()

    if existing is None:
        if keep_stderr and not root.handlers:
            root.addHandler(logging.StreamHandler(sys.stderr))
        root.addHandler(handler)

    # Lower the root level if it would otherwise swallow the records we want.
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)

    if capture_warnings:
        logging.captureWarnings(True)

    return handler


def uninstall() -> None:
    """Remove any :class:`DUUICollectHandler` from the root logger (mainly for tests)."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, DUUICollectHandler)]:
        root.removeHandler(handler)
