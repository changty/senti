"""Web search skill using Brave Search API (sandboxed)."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class SearchSkill(BaseSkill):
    """Web search via Brave Search API, executed in a sandbox container."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "search"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for current information using Brave Search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query",
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of results (max 10)",
                                "default": 5,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": (
                        "Fetch the content of a web page and return it as clean text. "
                        "Use this after web_search to read the actual content of a result page."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL to fetch",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        # This skill is sandboxed — execution happens in the container.
        # This method is a fallback if sandbox is unavailable.
        return "Web search requires the sandbox container. Please ensure Docker is available."
