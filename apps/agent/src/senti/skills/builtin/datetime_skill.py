"""Date and time skill."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class DateTimeSkill(BaseSkill):
    """In-process skill for getting the current date and time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "datetime"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_current_datetime",
                    "description": "Get the current date and time in UTC.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        if function_name == "get_current_datetime":
            now = datetime.now(timezone.utc)
            return now.strftime("%Y-%m-%d %H:%M:%S UTC (%A)")
        return f"Unknown function: {function_name}"
