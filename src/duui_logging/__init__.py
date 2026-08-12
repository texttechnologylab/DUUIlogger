"""duui_logging — return a Python component's logs to the DUUI Java composer.

Logs are *piggybacked* on the ``/v1/process`` response: while handling a request the tool
buffers everything it logs, and the middleware returns it in a ``DUUI-Logs`` response
header that the Java driver reads. No connection back to Java is opened, so running N tools
in parallel costs zero extra connections.

Typical use in a FastAPI-based DUUI tool::

    from fastapi import FastAPI
    import duui_logging

    app = FastAPI()
    app.add_middleware(duui_logging.DUUILoggingMiddleware)

    @app.post("/v1/process")
    def process(...):
        duui_logging.log_info("started")
        duui_logging.log_warn("careful")
        try:
            ...
        except Exception:
            duui_logging.log_error("boom")   # attaches the exception traceback

The tool only collects/returns logs when Java asks (the ``DUUI-Log-Collect`` request
header); otherwise the helpers just echo to stderr, so the same code runs fine standalone.

To also forward logs emitted by third-party libraries through the stdlib :mod:`logging`
module (and warnings via :mod:`warnings`), call :func:`duui_logging.install` once at
startup — see :mod:`duui_logging.stdlib`.
"""

from __future__ import annotations

from .integration import DUUILoggingMiddleware, add_logging
from .duui_logger import (
    ErrorLevel,
    current_exception_trace,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_trace,
    log_warn,
    log_warning,
    where_am_i,
)
from .records import LogRecord
from .stdlib import DUUICollectHandler, install, uninstall

__all__ = [
    # Prefab logging helpers (primary API)
    "log_trace",
    "log_debug",
    "log_info",
    "log_warn",
    "log_warning",
    "log_error",
    "log_critical",
    "ErrorLevel",
    "where_am_i",
    "current_exception_trace",
    # FastAPI integration
    "DUUILoggingMiddleware",
    "add_logging",
    # stdlib logging bridge (forwards third-party library logs)
    "DUUICollectHandler",
    "install",
    "uninstall",
    # record model
    "LogRecord",
]
