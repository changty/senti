"""Content sanitizer: HTML → Markdown, script stripping."""

from __future__ import annotations

import re

from markdownify import markdownify


def sanitize_html(html: str) -> str:
    """Convert HTML to Markdown and strip dangerous content."""
    # Remove script and style tags with their content
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove hidden elements
    html = re.sub(
        r'<[^>]+(?:display\s*:\s*none|visibility\s*:\s*hidden)[^>]*>.*?</[^>]+>',
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove iframes, objects, embeds
    for tag in ["iframe", "object", "embed", "applet"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(rf"<{tag}[^>]*/>", "", html, flags=re.IGNORECASE)

    # Remove event handler attributes
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)

    # Convert to markdown
    md = markdownify(html, heading_style="ATX", strip=["img"])

    # Clean up excessive whitespace
    md = re.sub(r"\n{3,}", "\n\n", md)

    return md.strip()
