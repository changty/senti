"""Telegram message formatting utilities — Markdown to Telegram HTML."""

from __future__ import annotations

import re
from html import escape as html_escape

# Maximum Telegram message length
MAX_MESSAGE_LENGTH = 4096

# Placeholder for stashed blocks (uses null byte, won't appear in normal text)
_PLACEHOLDER = "\x00{}\x00"


def _stash_code_blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract fenced and inline code, replacing with placeholders.

    Returns (modified text, list of (type, content)) where type is 'block' or 'inline'.
    """
    stash: list[tuple[str, str]] = []

    def _replace_block(m: re.Match) -> str:
        idx = len(stash)
        stash.append(("block", m.group(1)))
        return _PLACEHOLDER.format(idx)

    def _replace_inline(m: re.Match) -> str:
        idx = len(stash)
        stash.append(("inline", m.group(1)))
        return _PLACEHOLDER.format(idx)

    # Fenced code blocks first (```...```)
    text = re.sub(r"```(?:\w*)\n?(.*?)```", _replace_block, text, flags=re.DOTALL)
    # Inline code (`...`)
    text = re.sub(r"`([^`]+)`", _replace_inline, text)

    return text, stash


def _restore_stash(text: str, stash: list[tuple[str, str]]) -> str:
    """Restore stashed code blocks as HTML tags."""
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        kind, content = stash[idx]
        escaped = html_escape(content)
        if kind == "block":
            return f"<pre>{escaped}</pre>"
        return f"<code>{escaped}</code>"

    return re.sub(r"\x00(\d+)\x00", _restore, text)


def _convert_tables(text: str) -> str:
    """Convert markdown tables to readable key-value lists.

    Telegram doesn't support HTML tables, so we convert them to bold-label
    lists that render cleanly in chat.
    """
    lines = text.split("\n")
    result: list[str] = []
    table_lines: list[str] = []

    def _flush_table() -> None:
        if not table_lines:
            return
        # Parse cells: strip outer pipes and split by inner pipes
        rows = [
            [c.strip() for c in line.strip().strip("|").split("|")]
            for line in table_lines
        ]
        # Need at least a header + separator + one data row
        if len(rows) < 3:
            result.extend(table_lines)
            return
        headers = rows[0]
        # Skip separator row (row[1]) — contains dashes like "---"
        data_rows = [r for r in rows[2:] if any(c.strip() for c in r)]
        if not headers or not data_rows:
            result.extend(table_lines)
            return
        for row in data_rows:
            if len(headers) == 2:
                # Key-value pattern: <b>Key:</b> Value
                key = row[0] if len(row) > 0 else ""
                val = row[1] if len(row) > 1 else ""
                result.append(f"<b>{key}:</b> {val}")
            else:
                # Multi-column: <b>H1:</b> v1, <b>H2:</b> v2, ...
                parts = []
                for i, header in enumerate(headers):
                    val = row[i] if i < len(row) else ""
                    parts.append(f"<b>{header}:</b> {val}")
                result.append(", ".join(parts))

    for line in lines:
        stripped = line.strip()
        if "|" in stripped and stripped.startswith("|"):
            table_lines.append(line)
        else:
            _flush_table()
            table_lines = []
            result.append(line)

    _flush_table()
    return "\n".join(result)


def _md_to_telegram_html(text: str) -> str:
    """Convert markdown-ish text to Telegram-compatible HTML.

    Handles: bold, italic, strikethrough, links, headers, blockquotes.
    """
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_ (but not inside words with underscores)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Headers: # ... → bold line
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    # Blockquotes: > text (after html_escape, > becomes &gt;)
    text = re.sub(
        r"^(?:&gt;\s?(.+?)(?:\n|$))+",
        lambda m: "<blockquote>" + re.sub(r"^&gt;\s?", "", m.group(0), flags=re.MULTILINE).strip() + "</blockquote>",
        text,
        flags=re.MULTILINE,
    )
    return text


def _truncate_html(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate text to max_length without cutting inside HTML tags."""
    if len(text) <= max_length:
        return text

    limit = max_length - 4  # room for "\n..."
    # Walk backwards to avoid cutting inside a tag
    cut = limit
    # If we're inside a tag, back up
    last_open = text.rfind("<", 0, cut)
    last_close = text.rfind(">", 0, cut)
    if last_open > last_close:
        # We'd cut inside a tag — back up to before it
        cut = last_open

    return text[:cut] + "\n..."


def format_response(text: str) -> str:
    """Convert LLM markdown response to Telegram-safe HTML."""
    # 1. Stash code blocks and inline code
    text, stash = _stash_code_blocks(text)
    # 2. HTML-escape the remaining text
    text = html_escape(text)
    # 3. Convert markdown tables to lists (after escape; | is unaffected,
    #    and the <b> tags we emit won't be re-escaped)
    text = _convert_tables(text)
    # 4. Convert markdown to HTML tags
    text = _md_to_telegram_html(text)
    # 5. Restore code blocks
    text = _restore_stash(text, stash)
    # 6. Truncate safely
    text = _truncate_html(text)
    return text
