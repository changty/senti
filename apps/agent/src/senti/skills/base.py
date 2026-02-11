"""Abstract base skill and skill definition dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillDefinition:
    """Metadata for a skill loaded from skills.yaml."""

    name: str
    description: str
    module: str  # e.g. "senti.skills.builtin.fact_skill"
    class_name: str  # e.g. "FactSkill"
    sandboxed: bool = False
    sandbox_image: str = ""
    requires_approval: bool = False
    network: str = "none"  # "none" or an allowlist network name
    parameters: dict[str, Any] = field(default_factory=dict)
    user_created: bool = False
    user_skill_code: str = ""
    trusted: bool = False
    requires_approval_functions: list[str] = field(default_factory=list)


class BaseSkill(ABC):
    """Abstract base class for all skills."""

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible tool definitions for this skill."""
        ...

    @abstractmethod
    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        """Execute a tool function and return a string result."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill name."""
        ...
