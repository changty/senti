"""Skillsmith skill: create, list, and delete user-defined tools."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from senti.config import Settings
from senti.skills.base import BaseSkill

logger = logging.getLogger(__name__)

MAX_CODE_CHARS = 10_000

RESERVED_NAMES = {
    "run_python",
    "web_search",
    "web_fetch",
    "save_memory",
    "search_memories",
    "list_memories",
    "delete_memory",
    "get_current_datetime",
    "gdrive_list_files",
    "gdrive_create_file",
    "email_list_inbox",
    "email_create_draft",
    "create_scheduled_job",
    "list_scheduled_jobs",
    "delete_scheduled_job",
    "create_skill",
    "list_user_skills",
    "delete_skill",
}

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class SkillsmithSkill(BaseSkill):
    """In-process skill for managing user-created tools."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "skillsmith"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_skill",
                    "description": (
                        "Create a reusable user-defined tool. The code must define a "
                        "'def run(args)' function that takes a dict of arguments and "
                        "returns a string result. The tool will be executed in a secure "
                        "Python sandbox with numpy and pandas available."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": (
                                    "Tool name: lowercase letters, digits, underscores. "
                                    "2-40 chars, must start with a letter."
                                ),
                            },
                            "description": {
                                "type": "string",
                                "description": "What this tool does (shown to the LLM)",
                            },
                            "parameters": {
                                "type": "object",
                                "description": (
                                    "JSON Schema for the tool's parameters. "
                                    "Must be an object with 'type': 'object' and 'properties'."
                                ),
                            },
                            "code": {
                                "type": "string",
                                "description": (
                                    "Python source code. Must define 'def run(args): ...' "
                                    "that takes a dict and returns a string."
                                ),
                            },
                        },
                        "required": ["name", "description", "code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_user_skills",
                    "description": "List all user-created tools.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_skill",
                    "description": "Delete a user-created tool by name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the skill to delete",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        user_skill_store = kwargs.get("user_skill_store")
        registry = kwargs.get("registry")
        user_id: int = kwargs.get("user_id", 0)

        if not user_skill_store:
            return "Skill management not available."

        if function_name == "create_skill":
            return await self._create(arguments, user_skill_store, registry, user_id)
        elif function_name == "list_user_skills":
            return await self._list(user_skill_store, user_id)
        elif function_name == "delete_skill":
            return await self._delete(arguments, user_skill_store, registry, user_id)

        return f"Unknown function: {function_name}"

    async def _create(self, args, user_skill_store, registry, user_id) -> str:
        name = args.get("name", "").strip()
        description = args.get("description", "").strip()
        code = args.get("code", "")
        parameters = args.get("parameters", {"type": "object", "properties": {}})

        # Validate name
        if not _NAME_PATTERN.match(name):
            return (
                f"Invalid skill name '{name}'. Must be 2-40 chars, "
                "lowercase letters/digits/underscores, starting with a letter."
            )

        if name in RESERVED_NAMES:
            return f"Name '{name}' is reserved and cannot be used."

        # Validate code
        if not code:
            return "No code provided."
        if len(code) > MAX_CODE_CHARS:
            return f"Code too long ({len(code)} chars, max {MAX_CODE_CHARS})."
        if "def run(" not in code:
            return "Code must define a 'def run(' function."

        # Validate parameters JSON
        params_json = json.dumps(parameters)

        try:
            skill_data = await user_skill_store.create(
                user_id=user_id,
                name=name,
                description=description,
                parameters_json=params_json,
                code=code,
            )
        except ValueError as exc:
            return str(exc)

        # Register dynamically in the registry
        if registry:
            registry.register_user_skill(skill_data)

        return f"Skill '{name}' created and registered. It will require approval on first use."

    async def _list(self, user_skill_store, user_id) -> str:
        skills = await user_skill_store.list_for_user(user_id)
        if not skills:
            return "No user-created skills."
        lines = []
        for s in skills:
            trusted = " (trusted)" if s.get("trusted") else ""
            lines.append(f"- {s['name']}: {s['description']}{trusted}")
        return "\n".join(lines)

    async def _delete(self, args, user_skill_store, registry, user_id) -> str:
        name = args.get("name", "").strip()
        if not name:
            return "Missing skill name."

        deleted = await user_skill_store.delete(name, user_id)
        if not deleted:
            return f"Skill '{name}' not found or not owned by you."

        # Unregister from registry
        if registry:
            registry.unregister_user_skill(name)

        return f"Skill '{name}' deleted."
