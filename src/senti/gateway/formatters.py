"""Telegram message formatting utilities."""

from __future__ import annotations

import re

# Telegram MarkdownV2 requires escaping these characters
_ESCAPE_CHARS = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")

# Maximum Telegram message length
MAX_MESSAGE_LENGTH = 4096


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _ESCAPE_CHARS.sub(r"\\\1", text)


def truncate_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate a message to fit Telegram's limit, appending ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 4] + "\n..."


def format_response(text: str) -> str:
    """Prepare LLM response for Telegram. Send as plain text to avoid parse issues."""
    return truncate_message(text)
