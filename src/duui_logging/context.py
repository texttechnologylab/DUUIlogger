"""Per-request log buffer.

With the piggyback transport there is no connection back to Java. Instead, each log
record produced while handling a ``/v1/process`` request is appended to a request-scoped
buffer; the middleware then serialises that buffer into a response header that the Java
driver reads off the HTTP response. The buffer lives in a :class:`~contextvars.ContextVar`
so concurrent requests never mix, and because a ``ContextVar`` copied into a threadpool
worker shares the *same* list object, records appended from a sync endpoint are still
visible to the middleware.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import List, Optional

from .records import LogRecord

# HTTP headers exchanged with the Java side (mirrors IDUUIInstantiatedPipelineComponent).
HEADER_LOG_COLLECT = "duui-log-collect"  # request: Java asks the tool to return its logs
HEADER_LOGS = "duui-logs"                # response: the tool's logs as a JSON array

# Marker attribute set (via ``extra=``) on the stdlib ``LogRecord``s the ``log_*`` helpers
# emit for *local display*. The helpers already buffer their own precise record for Java, so
# the DUUICollectHandler must ignore these to avoid a second, level-mapped copy (which would
# e.g. turn a TRACE into an INFO on the Java side).
SKIP_COLLECT_ATTR = "_duui_skip_collect"

# None means "not collecting" (no active request or Java didn't ask for logs).
_buffer: ContextVar[Optional[List[LogRecord]]] = ContextVar("duui_log_buffer", default=None)

# Process-wide fallback logger name, used by the log_* helpers when the caller passes no
# explicit ``logger=``. Set once at startup (typically to the component's module/file name;
# see :func:`duui_logging.add_logging`). Stays "duui" until something overrides it.
_default_logger: str = "duui"


def set_default_logger(name: Optional[str]) -> None:
    """Set the fallback logger name used when a ``log_*`` call omits ``logger=``.

    Ignores blank/``None`` so an accidental empty value never wipes a good default.
    """
    global _default_logger
    if name and name.strip():
        _default_logger = name.strip()


def get_default_logger() -> str:
    """Return the current fallback logger name (default ``"duui"``)."""
    return _default_logger


def start_buffer():
    """Begin collecting logs for the current request. Returns a reset token."""
    return _buffer.set([])


def reset_buffer(token) -> None:
    """Stop collecting, restoring the previous buffer state."""
    try:
        _buffer.reset(token)
    except (LookupError, ValueError):
        pass


def get_buffer() -> Optional[List[LogRecord]]:
    """Return the current request's buffer, or ``None`` if not collecting."""
    return _buffer.get()


def collect(record: LogRecord) -> None:
    """Append a record to the current request's buffer, if one is active."""
    buffer = _buffer.get()
    if buffer is not None:
        buffer.append(record)
