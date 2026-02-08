"""Skill discovery and registration from config/skills.yaml."""

from __future__ import annotations

import importlib
import logging
from typing import Any

import yaml

from senti.config import Settings
from senti.skills.base import BaseSkill, SkillDefinition

logger = logging.getLogger(__name__)


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
