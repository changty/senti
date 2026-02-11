"""Google Drive skill (sandboxed, write requires approval)."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class GDriveSkill(BaseSkill):
    """Google Drive file operations, executed in a sandbox container."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "gdrive"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "gdrive_list_files",
                    "description": "List files in Google Drive, optionally filtered by query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (Google Drive API format)",
                                "default": "",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of results",
                                "default": 10,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "gdrive_create_file",
                    "description": "Create a new text file in Google Drive. Requires approval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "File name",
                            },
                            "content": {
                                "type": "string",
                                "description": "File content (plain text)",
                            },
                            "mime_type": {
                                "type": "string",
                                "description": "MIME type",
                                "default": "text/plain",
                            },
                        },
                        "required": ["name", "content"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        return "Google Drive skill requires the sandbox container."
