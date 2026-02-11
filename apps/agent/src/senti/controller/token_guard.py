"""Token limits and loop detection."""

from __future__ import annotations

import logging

from senti.config import Settings

logger = logging.getLogger(__name__)


class TokenGuard:
    """Enforces max tool rounds and result size limits."""

    def __init__(self, settings: Settings) -> None:
        self._max_rounds = settings.max_tool_rounds
        self._max_chars = settings.max_result_chars

    def allow_round(self, current_round: int) -> bool:
        """Returns True if we haven't exceeded the max tool rounds."""
        if current_round > self._max_rounds:
            logger.warning("Tool round limit reached: %d/%d", current_round, self._max_rounds)
            return False
        return True

    def truncate_result(self, result: str) -> str:
        """Truncate a tool result to the max allowed size."""
        if len(result) <= self._max_chars:
            return result
        truncated = result[: self._max_chars - 20] + "\n...[TRUNCATED]..."
        logger.debug("Truncated tool result from %d to %d chars", len(result), len(truncated))
        return truncated
