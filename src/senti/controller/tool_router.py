"""Routes tool calls to the appropriate skill execution path."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from senti.exceptions import ApprovalDeniedError, ApprovalTimeoutError, ToolError

if TYPE_CHECKING:
    from telegram import Update

    from senti.config import Settings
    from senti.gateway.hitl import HITLManager
    from senti.memory.fact_store import FactStore
    from senti.sandbox.executor import SandboxExecutor
    from senti.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class ToolRouter:
    """Maps function names to skill execution, handling in-process vs sandboxed."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        fact_store: FactStore | None = None,
        sandbox: SandboxExecutor | None = None,
        hitl: HITLManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._registry = registry
        self._fact_store = fact_store
        self._sandbox = sandbox
        self._hitl = hitl
        self._settings = settings

    async def execute(
        self,
        function_name: str,
        arguments: dict[str, Any],
        *,
        user_id: int = 0,
        update: Any | None = None,
    ) -> str:
        """Execute a tool call, routing to the correct execution path."""
        skill = self._registry.get_skill(function_name)
        if skill is None:
            return f"Unknown tool: {function_name}"

        defn = self._registry.get_definition(function_name)

        # HITL approval gate
        if defn and defn.requires_approval and self._hitl and update:
            try:
                approved = await self._hitl.request_approval(
                    update=update,
                    tool_name=function_name,
                    arguments=arguments,
                )
                if not approved:
                    raise ApprovalDeniedError(f"User denied {function_name}")
            except ApprovalTimeoutError:
                return f"Approval for {function_name} timed out."
            except ApprovalDeniedError:
                return f"User denied execution of {function_name}."

        # Route: sandboxed vs in-process
        try:
            if defn and defn.sandboxed and self._sandbox:
                result = await self._sandbox.run(
                    image=defn.sandbox_image,
                    input_data={"function": function_name, "arguments": arguments},
                    network_mode=defn.network,
                    environment=self._sandbox_env(defn.name),
                )
                return result
            else:
                return await skill.execute(
                    function_name,
                    arguments,
                    user_id=user_id,
                    fact_store=self._fact_store,
                    update=update,
                )
        except (ApprovalDeniedError, ApprovalTimeoutError):
            raise
        except Exception as exc:
            logger.exception("Tool execution failed: %s", function_name)
            raise ToolError(f"Tool {function_name} failed: {exc}") from exc

    def _sandbox_env(self, skill_name: str) -> dict[str, str]:
        """Return environment variables a sandboxed skill needs (secrets only)."""
        if self._settings is None:
            return {}
        s = self._settings
        envs: dict[str, dict[str, str]] = {
            "search": {"BRAVE_API_KEY": s.brave_api_key},
            "gdrive": {
                "GOOGLE_CLIENT_ID": s.google_client_id,
                "GOOGLE_CLIENT_SECRET": s.google_client_secret,
                "GOOGLE_REFRESH_TOKEN": s.google_refresh_token,
            },
            "email": {
                "GOOGLE_CLIENT_ID": s.google_client_id,
                "GOOGLE_CLIENT_SECRET": s.google_client_secret,
                "GMAIL_REFRESH_TOKEN": s.gmail_refresh_token,
                "GMAIL_LABEL": s.gmail_label,
            },
        }
        return {k: v for k, v in envs.get(skill_name, {}).items() if v}
