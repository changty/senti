"""Memory skill: save, search, list, update, delete memories."""

from __future__ import annotations

from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill


class MemorySkill(BaseSkill):
    """In-process skill for managing user memories."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "memory"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "save_memory",
                    "description": (
                        "Save a new memory about the user. Use an appropriate category: "
                        "preference, fact, people, goal, or general."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short title for the memory (e.g. 'favorite color', 'wife name')",
                            },
                            "content": {
                                "type": "string",
                                "description": "The memory content to save",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["preference", "fact", "people", "goal", "general"],
                                "description": "Memory category",
                            },
                            "importance": {
                                "type": "integer",
                                "description": "Importance 1-10 (default 5). Higher = more likely to be recalled",
                            },
                        },
                        "required": ["title", "content", "category"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_memories",
                    "description": "Search through stored memories by keyword. Use this to find relevant information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (keywords)",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["preference", "fact", "people", "goal", "general"],
                                "description": "Optional: filter by category",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_memories",
                    "description": "List all stored memories, optionally filtered by category.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["preference", "fact", "people", "goal", "general", "session_summary"],
                                "description": "Optional: filter by category",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_memory",
                    "description": "Update an existing memory by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "memory_id": {
                                "type": "integer",
                                "description": "ID of the memory to update",
                            },
                            "content": {
                                "type": "string",
                                "description": "New content",
                            },
                            "title": {
                                "type": "string",
                                "description": "New title",
                            },
                            "importance": {
                                "type": "integer",
                                "description": "New importance (1-10)",
                            },
                        },
                        "required": ["memory_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_memory",
                    "description": "Delete a stored memory by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "memory_id": {
                                "type": "integer",
                                "description": "ID of the memory to delete",
                            },
                        },
                        "required": ["memory_id"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        memory_store = kwargs.get("memory_store")
        user_id = kwargs.get("user_id", 0)

        if memory_store is None:
            return "Memory store not available."

        if function_name == "save_memory":
            mem = await memory_store.save_memory(
                user_id=user_id,
                title=arguments["title"],
                content=arguments["content"],
                category=arguments.get("category", "general"),
                importance=arguments.get("importance", 5),
                source="tool",
            )
            return f"Saved memory #{mem['id']}: {mem['title']} [{mem['category']}]"

        elif function_name == "search_memories":
            results = await memory_store.search_memories(
                user_id=user_id,
                query=arguments["query"],
                category=arguments.get("category"),
            )
            if not results:
                return "No memories found matching that query."
            lines = []
            for m in results:
                lines.append(f"- #{m['id']} [{m['category']}] {m['title']}: {m['content']}")
            return "\n".join(lines)

        elif function_name == "list_memories":
            memories = await memory_store.list_memories(
                user_id=user_id,
                category=arguments.get("category"),
            )
            if not memories:
                return "No memories stored."
            lines = []
            current_cat = None
            for m in memories:
                if m["category"] != current_cat:
                    current_cat = m["category"]
                    lines.append(f"\n[{current_cat}]")
                lines.append(f"  #{m['id']}: {m['title']} (importance: {m['importance']})")
            return "\n".join(lines)

        elif function_name == "update_memory":
            updated = await memory_store.update_memory(
                arguments["memory_id"],
                content=arguments.get("content"),
                title=arguments.get("title"),
                importance=arguments.get("importance"),
            )
            if updated:
                return f"Updated memory #{updated['id']}: {updated['title']}"
            return "Memory not found."

        elif function_name == "delete_memory":
            deleted = await memory_store.delete_memory(arguments["memory_id"])
            if deleted:
                return f"Deleted memory #{arguments['memory_id']}."
            return "Memory not found."

        return f"Unknown function: {function_name}"
