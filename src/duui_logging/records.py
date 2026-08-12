"""The wire format shared with the Java side.

Each log record is one JSON object; the tool returns an array of them in the ``DUUI-Logs``
response header. The field names here must match what the Java ``DUUIComponentLog`` reads
(``level``, ``message``, ``logger``, ``stacktrace``, ``timestamp``). Correlation (which
component / which document) is added by Java, which already knows both, so the tool does
not send it.
"""

from __future__ import annotations

import time
from typing import Optional

from pydantic import BaseModel, Field


class LogRecord(BaseModel):
    """A single structured log record returned to the DUUI composer."""

    level: str
    message: str
    logger: Optional[str] = None
    stacktrace: Optional[str] = None
    timestamp: Optional[int] = Field(default_factory=lambda: int(time.time() * 1000))
