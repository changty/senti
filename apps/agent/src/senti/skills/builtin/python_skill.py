"""Python execution skill (sandboxed)."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class PythonSkill(BaseSkill):
    """Execute Python code in a sandboxed Docker container."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "python_runner"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": (
                        "Execute Python code in a secure sandbox. "
                        "Has numpy and pandas available. "
                        "Use print() to produce output. "
                        "When the user uploads a file, it's available at /data/upload/<filename>. "
                        "No network access. Max 10K chars of code, 8K chars of output."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code to execute",
                            },
                        },
                        "required": ["code"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        return "Python execution requires the sandbox container. Please ensure Docker is available."
