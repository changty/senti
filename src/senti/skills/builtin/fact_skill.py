"""Fact storage skill: save, retrieve, list, delete facts."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class FactSkill(BaseSkill):
    """In-process skill for managing user facts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "facts"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "save_fact",
                    "description": "Save a key-value fact for the user. Use this to remember information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Fact key (e.g. 'birthday', 'favorite_color')",
                            },
                            "value": {
                                "type": "string",
                                "description": "Fact value",
                            },
                        },
                        "required": ["key", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_fact",
                    "description": "Retrieve a stored fact by key.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Fact key to look up",
                            },
                        },
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_facts",
                    "description": "List all stored facts for the user.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_fact",
                    "description": "Delete a stored fact by key.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "description": "Fact key to delete",
                            },
                        },
                        "required": ["key"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        # fact_store and user_id are injected by the tool router
        fact_store = kwargs.get("fact_store")
        user_id = kwargs.get("user_id", 0)

        if fact_store is None:
            return "Fact store not available."

        if function_name == "save_fact":
            return await fact_store.save_fact(user_id, arguments["key"], arguments["value"])
        elif function_name == "get_fact":
            return await fact_store.get_fact(user_id, arguments["key"])
        elif function_name == "list_facts":
            facts = await fact_store.list_facts(user_id)
            if not facts:
                return "No facts stored."
            return "\n".join(f"- {k}: {v}" for k, v in facts.items())
        elif function_name == "delete_fact":
            return await fact_store.delete_fact(user_id, arguments["key"])

        return f"Unknown function: {function_name}"
