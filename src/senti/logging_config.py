"""Structured logging with PII filtering and file rotation."""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senti.config import Settings

# Patterns that look like secrets / PII
_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # emails
    re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),  # phone numbers
]


class PIIFilter(logging.Filter):
    """Redacts PII patterns and known secret values from log records."""

    def __init__(self, sensitive_values: set[str] | None = None) -> None:
        super().__init__()
        self._sensitive = sensitive_values or set()

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for val in self._sensitive:
            msg = msg.replace(val, "[REDACTED]")
        for pat in _PII_PATTERNS:
            msg = pat.sub("[PII]", msg)
        record.msg = msg
        record.args = None
        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    """Configure root logger with console + rotating file handlers."""
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove any existing handlers
    root.handlers.clear()

    pii_filter = PIIFilter(settings.sensitive_values())

    # Console: human-readable
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    console.addFilter(pii_filter)
    root.addHandler(console)

    # File: JSON, rotating
    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_dir / "senti.log",
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    file_handler.addFilter(pii_filter)
    root.addHandler(file_handler)

    # Quieten noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
