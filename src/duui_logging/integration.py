"""FastAPI/Starlette integration for the piggyback transport.

When Java wants logs it sets the ``DUUI-Log-Collect`` header on the ``/v1/process``
request. :class:`DUUILoggingMiddleware` then collects everything logged while handling
the request and writes it back as a ``DUUI-Logs`` response header (a JSON array), which
the Java driver reads off the HTTP response. No connection back to Java is opened — the
logs travel on the response the tool already returns.

Implemented as pure ASGI middleware so the request-scoped buffer set here is visible to
the endpoint (they share the same task/context, and a threadpool worker inherits a copy
that still points at the same list object).
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Callable, List, Optional

from . import context
from .records import LogRecord

# Keep the response header comfortably under common server/client limits.
DEFAULT_MAX_BYTES = 16_000


class DUUILoggingMiddleware:
    """Collect a request's logs and return them in the ``DUUI-Logs`` response header.

    :param default_logger: fallback logger name for ``log_*`` calls that omit ``logger=``.
        Prefer :func:`add_logging`, which fills this in automatically with the name of the
        file that installs the middleware. (Starlette constructs the middleware lazily, on
        the first request from inside its own frames, so the object cannot discover that
        file itself — it has to be told.)
    """

    def __init__(self, app: Callable, max_bytes: int = DEFAULT_MAX_BYTES,
                 default_logger: Optional[str] = None) -> None:
        self.app = app
        self.max_bytes = max_bytes
        context.set_default_logger(default_logger)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> Any:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        if not _is_truthy(headers.get(context.HEADER_LOG_COLLECT)):
            # Java didn't ask for logs: run normally, don't buffer or add a header.
            await self.app(scope, receive, send)
            return

        token = context.start_buffer()
        max_bytes = self.max_bytes

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                buffer = context.get_buffer() or []
                payload = _encode_logs(buffer, max_bytes)
                if payload:
                    message = dict(message)
                    message["headers"] = list(message.get("headers", [])) + [
                        (context.HEADER_LOGS.encode("latin-1"), payload.encode("latin-1"))
                    ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            context.reset_buffer(token)


def _caller_logger_name(depth: int = 1) -> Optional[str]:
    """Best-effort name for the module ``depth`` frames above this one.

    Prefers the caller's module ``__name__`` (e.g. ``letter_counter``), falling back to the
    file's base name without extension when that is unhelpful (``__main__`` or missing).
    """
    stack = inspect.stack()
    try:
        if depth >= len(stack):
            return None
        frame_info = stack[depth]
        name = frame_info.frame.f_globals.get("__name__")
        if name and name != "__main__":
            return name
        filename = frame_info.filename
        if filename:
            base = os.path.splitext(os.path.basename(filename))[0]
            return base or None
        return None
    finally:
        del stack  # break reference cycles held by frame objects


def add_logging(app, *, max_bytes: int = DEFAULT_MAX_BYTES,
                default_logger: Optional[str] = None) -> str:
    """Install :class:`DUUILoggingMiddleware` on ``app`` and pick a default logger name.

    Drop-in for ``app.add_middleware(DUUILoggingMiddleware)``. When ``default_logger`` is not
    given, the name of the file that made this call is used, so ``log_info("hi")`` (no
    ``logger=``) is tagged with the component's module instead of an empty string.

    :returns: the resolved default logger name.
    """
    if default_logger is None:
        # depth=2: skip _caller_logger_name (0) and add_logging (1) to land on the caller.
        default_logger = _caller_logger_name(depth=2)
    context.set_default_logger(default_logger)
    app.add_middleware(DUUILoggingMiddleware, max_bytes=max_bytes, default_logger=default_logger)
    return context.get_default_logger()


def _is_truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        value = value.decode("latin-1")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _encode_logs(records: List[LogRecord], max_bytes: int) -> str:
    """Serialise records to a compact ASCII JSON array, bounded by ``max_bytes``.

    Oversized payloads shed stacktraces first, then drop the oldest records, keeping the
    most recent ones.
    """
    if not records:
        return ""

    dicts = [r.model_dump(exclude_none=True) for r in records]
    payload = _dumps(dicts)
    if len(payload) <= max_bytes:
        return payload

    # 1) Drop stacktraces (usually the bulk of the size).
    for d in dicts:
        d.pop("stacktrace", None)
    payload = _dumps(dicts)
    if len(payload) <= max_bytes:
        return payload

    # 2) Keep the most recent records that fit, reserving room for a truncation marker.
    budget = max(max_bytes - 160, 0)
    kept: List[dict] = []
    for d in reversed(dicts):
        candidate = [d] + kept
        if len(_dumps(candidate)) > budget:
            break
        kept = candidate
    dropped = len(dicts) - len(kept)
    if dropped > 0:
        marker = {"level": "WARN", "message": f"[duui_logging] dropped {dropped} earlier log line(s) (size cap)"}
        kept = [marker] + kept
    return _dumps(kept)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
