"""Search and fetch sandbox runner.

Protocol: SENTI_INPUT env var (JSON) → process → JSON on stdout.
Supports: web_search (Brave API), web_fetch (URL content extraction).
"""

import gzip
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser

MAX_FETCH_BYTES = 512_000  # 512 KB max download
MAX_TEXT_CHARS = 8_000     # truncate extracted text


# --- SSRF protection ---

def _is_private_ip(hostname: str) -> bool:
    """Block requests to private/internal IPs."""
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                return True
    except (socket.gaierror, ValueError):
        return True  # can't resolve → block
    return False


def _validate_url(url: str) -> str | None:
    """Return an error message if the URL is not safe to fetch, else None."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked: only http/https allowed, got {parsed.scheme}"
    hostname = parsed.hostname or ""
    if not hostname:
        return "Blocked: no hostname in URL"
    if _is_private_ip(hostname):
        return f"Blocked: {hostname} resolves to a private/internal address"
    return None


# --- HTML to text extraction ---

class _TextExtractor(HTMLParser):
    """Simple HTML → text extractor that skips script/style tags."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag.lower() in ("br", "p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag.lower() in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_text(html: str) -> str:
    """Extract readable text from HTML."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


# --- web_search ---

def do_search(args: dict) -> str:
    query = args.get("query", "")
    count = min(args.get("count", 5), 10)

    api_key = os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return "BRAVE_API_KEY not configured."

    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": count}
    )

    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            data = json.loads(body.decode("utf-8"))
    except Exception as exc:
        return f"Search failed: {exc}"

    results = []
    for item in data.get("web", {}).get("results", [])[:count]:
        results.append(
            f"**{item.get('title', '')}**\n{item.get('url', '')}\n{item.get('description', '')}"
        )

    return "\n\n---\n\n".join(results) if results else "No results found."


# --- web_fetch ---

def do_fetch(args: dict) -> str:
    url = args.get("url", "")
    if not url:
        return "No URL provided."

    # SSRF protection
    err = _validate_url(url)
    if err:
        return err

    req = urllib.request.Request(url, headers={
        "User-Agent": "Senti/1.0 (AI assistant; content extraction)",
        "Accept": "text/html,application/xhtml+xml,text/plain",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read(MAX_FETCH_BYTES)

            # Decompress if needed
            encoding = resp.headers.get("Content-Encoding", "")
            if encoding == "gzip":
                body = gzip.decompress(body)

            # Determine charset
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()

            text = body.decode(charset, errors="replace")

            # Extract text from HTML
            if "html" in content_type:
                text = extract_text(text)

            # Truncate
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n\n...[content truncated]..."

            return text if text.strip() else "Page returned no readable content."

    except Exception as exc:
        return f"Fetch failed: {exc}"


# --- main ---

def main() -> None:
    raw = os.environ.get("SENTI_INPUT", "{}")
    request = json.loads(raw)
    function = request.get("function", "")
    args = request.get("arguments", {})

    if function == "web_search":
        result = do_search(args)
    elif function == "web_fetch":
        result = do_fetch(args)
    else:
        result = f"Unknown function: {function}"

    json.dump({"result": result}, sys.stdout)


if __name__ == "__main__":
    main()
