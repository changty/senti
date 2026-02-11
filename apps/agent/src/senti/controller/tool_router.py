"""Routes tool calls to the appropriate skill execution path."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from senti.exceptions import ApprovalDeniedError, ApprovalTimeoutError, ToolError

if TYPE_CHECKING:
    from telegram import Update

    from senti.config import Settings
    from senti.controller.orchestrator import Orchestrator
    from senti.gateway.hitl import HITLManager
    from senti.memory.memory_store import MemoryStore
    from senti.sandbox.executor import SandboxExecutor
    from senti.scheduler.engine import SchedulerEngine
    from senti.scheduler.job_store import JobStore
    from senti.skills.registry import SkillRegistry
    from senti.skills.user_skill_store import UserSkillStore

logger = logging.getLogger(__name__)


class ToolRouter:
    """Maps function names to skill execution, handling in-process vs sandboxed."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        memory_store: MemoryStore | None = None,
        sandbox: SandboxExecutor | None = None,
        hitl: HITLManager | None = None,
        settings: Settings | None = None,
        job_store: JobStore | None = None,
        scheduler: SchedulerEngine | None = None,
        user_skill_store: UserSkillStore | None = None,
    ) -> None:
        self._registry = registry
        self._memory_store = memory_store
        self._sandbox = sandbox
        self._hitl = hitl
        self._settings = settings
        self._job_store = job_store
        self._scheduler = scheduler
        self._user_skill_store = user_skill_store
        self._orchestrator: Orchestrator | None = None

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
        if defn and self._hitl and update:
            needs_approval = self._needs_approval(defn, function_name)
            if needs_approval:
                is_user_skill = defn.user_created
                try:
                    result = await self._hitl.request_approval(
                        update=update,
                        tool_name=function_name,
                        arguments=arguments,
                        is_user_skill=is_user_skill,
                    )
                    if result == "deny":
                        raise ApprovalDeniedError(f"User denied {function_name}")
                    if result == "trust" and is_user_skill:
                        await self._trust_skill(defn.name, user_id)
                except ApprovalTimeoutError:
                    return f"Approval for {function_name} timed out."
                except ApprovalDeniedError:
                    return f"User denied execution of {function_name}."

        # Route: sandboxed vs in-process
        try:
            if defn and defn.user_created and self._sandbox:
                # User skill: dispatch through python sandbox
                input_data = {
                    "function": "run_user_skill",
                    "arguments": {
                        "code": defn.user_skill_code,
                        "arguments": arguments,
                    },
                }
                return await self._sandbox.run(
                    image="senti-python:latest",
                    input_data=input_data,
                    network_mode="none",
                    environment={},
                )
            elif defn and defn.sandboxed and self._sandbox:
                # Check if orchestrator has a file upload to inject
                upload: tuple[str, bytes] | None = None
                sandbox_mem = "128m"
                if self._orchestrator and self._orchestrator._current_upload_path:
                    up = self._orchestrator._current_upload_path
                    name = self._orchestrator._current_upload_name
                    if up.is_file() and name:
                        upload = (name, up.read_bytes())
                        sandbox_mem = "256m"
                        logger.info("Upload for sandbox: %s (%d bytes)", name, len(upload[1]))

                result = await self._sandbox.run(
                    image=defn.sandbox_image,
                    input_data={"function": function_name, "arguments": arguments},
                    network_mode=defn.network,
                    environment=self._sandbox_env(defn.name),
                    upload_file=upload,
                    mem_limit=sandbox_mem,
                )
                return result
            else:
                # Derive chat_id from Telegram update if available
                chat_id = 0
                if update and hasattr(update, "effective_chat") and update.effective_chat:
                    chat_id = update.effective_chat.id

                return await skill.execute(
                    function_name,
                    arguments,
                    user_id=user_id,
                    chat_id=chat_id,
                    memory_store=self._memory_store,
                    job_store=self._job_store,
                    scheduler=self._scheduler,
                    orchestrator=self._orchestrator,
                    user_skill_store=self._user_skill_store,
                    registry=self._registry,
                    update=update,
                )
        except (ApprovalDeniedError, ApprovalTimeoutError):
            raise
        except Exception as exc:
            logger.exception("Tool execution failed: %s", function_name)
            raise ToolError(f"Tool {function_name} failed: {exc}") from exc

    def _needs_approval(self, defn, function_name: str) -> bool:
        """Determine if a tool call needs HITL approval."""
        # Trusted user skills skip approval
        if defn.user_created and defn.trusted:
            return False
        # Per-function approval list
        if defn.requires_approval_functions and function_name in defn.requires_approval_functions:
            return True
        # Blanket requires_approval flag
        if defn.requires_approval:
            return True
        return False

    async def _trust_skill(self, name: str, user_id: int) -> None:
        """Mark a user skill as trusted in both DB and registry."""
        if self._user_skill_store:
            await self._user_skill_store.set_trusted(name, user_id, True)
        self._registry.set_user_skill_trusted(name, True)

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
