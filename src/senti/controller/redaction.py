"""Scrubs secrets and sensitive data from prompts and responses."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml

from senti.config import Settings

logger = logging.getLogger(__name__)


class Redactor:
    """Redacts secrets and PII from text using regex patterns and literal .env values."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._patterns: list[tuple[re.Pattern, str]] = []
        self._load_patterns()
        self._sensitive_values = settings.sensitive_values()

    def _load_patterns(self) -> None:
        """Load regex patterns from redaction_patterns.yaml."""
        path = self._settings.redaction_config_path
        if not path.exists():
            logger.debug("No redaction patterns file at %s", path)
            return

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for entry in raw.get("patterns", []):
            try:
                pattern = re.compile(entry["regex"], re.IGNORECASE)
                replacement = entry.get("replacement", "[REDACTED]")
                self._patterns.append((pattern, replacement))
            except re.error:
                logger.warning("Invalid redaction regex: %s", entry.get("regex"))

    def redact(self, text: str) -> str:
        """Apply all redaction rules to the text."""
        # Literal .env values
        for val in self._sensitive_values:
            text = text.replace(val, "[REDACTED]")

        # Regex patterns
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)

        return text
