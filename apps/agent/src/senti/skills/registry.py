"""Skill discovery and registration from config/skills.yaml."""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any

import yaml

from senti.config import Settings
from senti.skills.base import BaseSkill, SkillDefinition

logger = logging.getLogger(__name__)


class UserSkillProxy(BaseSkill):
    """Lightweight proxy for a user-created skill.

    Provides tool definitions to the LLM. Actual execution is routed
    through the sandbox by ToolRouter.
    """

    def __init__(self, skill_data: dict[str, Any]) -> None:
        self._data = skill_data
        self._name = skill_data["name"]
        self._description = skill_data["description"]
        try:
            self._parameters = json.loads(skill_data.get("parameters_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            self._parameters = {}

    @property
    def name(self) -> str:
        return self._name

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        params = self._parameters or {
            "type": "object",
            "properties": {},
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": self._name,
                    "description": self._description,
                    "parameters": params,
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        return "User skill execution requires the sandbox container. Please ensure Docker is available."


class SkillRegistry:
    """Discovers, imports, and registers skills from YAML config."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._skills: dict[str, BaseSkill] = {}
        self._definitions: dict[str, SkillDefinition] = {}
        # Maps function_name → skill name
        self._function_map: dict[str, str] = {}

    @property
    def skills(self) -> dict[str, BaseSkill]:
        return self._skills

    def discover(self) -> None:
        """Load skill definitions from YAML and instantiate them."""
        path = self._settings.skills_config_path
        if not path.exists():
            logger.warning("Skills config not found at %s", path)
            return

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for name, cfg in raw.get("skills", {}).items():
            defn = SkillDefinition(
                name=name,
                description=cfg.get("description", ""),
                module=cfg["module"],
                class_name=cfg["class_name"],
                sandboxed=cfg.get("sandboxed", False),
                sandbox_image=cfg.get("sandbox_image", ""),
                requires_approval=cfg.get("requires_approval", False),
                network=cfg.get("network", "none"),
                parameters=cfg.get("parameters", {}),
                requires_approval_functions=cfg.get("requires_approval_functions", []),
            )
            self._definitions[name] = defn

            try:
                mod = importlib.import_module(defn.module)
                cls = getattr(mod, defn.class_name)
                instance = cls(self._settings)
                self._skills[name] = instance

                # Register function names
                for tool_def in instance.get_tool_definitions():
                    fn_name = tool_def["function"]["name"]
                    self._function_map[fn_name] = name

                logger.info("Registered skill: %s (%s)", name, defn.module)
            except Exception:
                logger.exception("Failed to load skill: %s", name)

    def get_skill(self, function_name: str) -> BaseSkill | None:
        """Look up the skill instance that owns a given function name."""
        skill_name = self._function_map.get(function_name)
        if skill_name:
            return self._skills.get(skill_name)
        return None

    def get_definition(self, function_name: str) -> SkillDefinition | None:
        """Look up the skill definition for a given function name."""
        skill_name = self._function_map.get(function_name)
        if skill_name:
            return self._definitions.get(skill_name)
        return None

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Return all tool definitions from all registered skills."""
        result: list[dict[str, Any]] = []
        for skill in self._skills.values():
            result.extend(skill.get_tool_definitions())
        return result

    def register_user_skill(self, skill_data: dict[str, Any]) -> None:
        """Dynamically register a user-created skill."""
        name = skill_data["name"]
        proxy = UserSkillProxy(skill_data)
        defn = SkillDefinition(
            name=name,
            description=skill_data["description"],
            module="",
            class_name="UserSkillProxy",
            sandboxed=True,
            sandbox_image="senti-python:latest",
            requires_approval=True,
            network="none",
            user_created=True,
            user_skill_code=skill_data["code"],
            trusted=bool(skill_data.get("trusted", 0)),
        )
        self._skills[name] = proxy
        self._definitions[name] = defn
        self._function_map[name] = name
        logger.info("Registered user skill: %s", name)

    def unregister_user_skill(self, name: str) -> None:
        """Remove a user-created skill from all registries."""
        self._skills.pop(name, None)
        self._definitions.pop(name, None)
        self._function_map.pop(name, None)
        logger.info("Unregistered user skill: %s", name)

    def load_user_skills(self, skills: list[dict[str, Any]]) -> None:
        """Bulk-load persisted user skills at startup."""
        for skill_data in skills:
            self.register_user_skill(skill_data)
        if skills:
            logger.info("Loaded %d user skills from DB", len(skills))

    def set_user_skill_trusted(self, name: str, trusted: bool) -> None:
        """Update the in-memory trusted flag for a user skill."""
        defn = self._definitions.get(name)
        if defn and defn.user_created:
            defn.trusted = trusted
            logger.info("User skill %s trusted=%s", name, trusted)
