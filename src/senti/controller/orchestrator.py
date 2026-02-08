"""Main message processing pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

from senti.config import Settings
from senti.controller.llm_client import LLMClient, ModelConfig
from senti.exceptions import LLMError, TokenLimitError

if TYPE_CHECKING:
    from telegram import Update

    from senti.controller.redaction import Redactor
    from senti.controller.token_guard import TokenGuard
    from senti.controller.tool_router import ToolRouter
    from senti.memory.conversation import ConversationMemory
    from senti.memory.fact_store import FactStore
    from senti.scheduler.engine import SchedulerEngine
    from senti.security.audit import AuditLogger
    from senti.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Orchestrator:
    """Central brain that wires gateway, LLM, tools, and memory."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        conversation: ConversationMemory | None = None,
        fact_store: FactStore | None = None,
        registry: SkillRegistry | None = None,
        tool_router: ToolRouter | None = None,
        redactor: Redactor | None = None,
        token_guard: TokenGuard | None = None,
        audit: AuditLogger | None = None,
        scheduler: SchedulerEngine | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._conversation = conversation
        self._fact_store = fact_store
        self._registry = registry
        self._tool_router = tool_router
        self._redactor = redactor
        self._token_guard = token_guard
        self._audit = audit
        self._scheduler = scheduler
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        path = self._settings.personality_path
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return "You are Senti, a helpful AI assistant."

    def _get_tool_definitions(self) -> list[dict[str, Any]] | None:
        if self._registry is None:
            return None
        defs = self._registry.tool_definitions()
        return defs if defs else None

    async def process_message(
        self,
        user_id: int,
        text: str,
        *,
        update: Update | None = None,
    ) -> str:
        """Full message processing pipeline."""
        # 1. Redact user input
        if self._redactor:
            text = self._redactor.redact(text)

        # 2. Load conversation history
        history: list[dict[str, str]] = []
        if self._conversation:
            history = await self._conversation.get_history(user_id)

        # 3. Build messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            *history,
            {"role": "user", "content": text},
        ]

        # 4. Get tool definitions
        tools = self._get_tool_definitions()

        # 5. LLM completion
        response = await self._llm.complete(messages, tools=tools)

        # 6. Tool-call loop
        rounds = 0
        max_rounds = self._settings.max_tool_rounds
        while "tool_calls" in response and self._tool_router:
            rounds += 1
            if self._token_guard and not self._token_guard.allow_round(rounds):
                raise TokenLimitError(f"Exceeded max tool rounds ({max_rounds})")

            # Append assistant message with tool calls
            messages.append(response)

            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}

                logger.info("Tool call: %s(%s)", fn_name, fn_args)

                # Audit
                if self._audit:
                    await self._audit.log_tool_call(user_id, fn_name, fn_args)

                # Execute
                result = await self._tool_router.execute(
                    fn_name, fn_args, user_id=user_id, update=update
                )

                # Truncate result
                if self._token_guard:
                    result = self._token_guard.truncate_result(result)

                # Redact tool output
                if self._redactor:
                    result = self._redactor.redact(result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

            # Re-call LLM with tool results
            response = await self._llm.complete(messages, tools=tools)

        # 7. Extract final text
        final_text = response.get("content", "")
        if not final_text:
            final_text = "I processed your request but have nothing to add."

        # 8. Redact outbound
        if self._redactor:
            final_text = self._redactor.redact(final_text)

        # 9. Save to conversation memory
        if self._conversation:
            await self._conversation.add_message(user_id, "user", text)
            await self._conversation.add_message(user_id, "assistant", final_text)

        return final_text

    async def reset_conversation(self, user_id: int) -> None:
        if self._conversation:
            await self._conversation.clear(user_id)

    async def list_facts(self, user_id: int) -> dict[str, str]:
        if self._fact_store:
            return await self._fact_store.list_facts(user_id)
        return {}

    def switch_model(self, name: str) -> ModelConfig:
        """Switch the active LLM model. Raises LLMError if not found."""
        return self._llm.switch_model(name)

    def list_models(self) -> dict[str, ModelConfig]:
        """Return all available models."""
        return self._llm.available_models

    @property
    def active_model_name(self) -> str:
        m = self._llm.active_model
        return m.name if m else "none"

    async def get_status(self) -> str:
        active = self._llm.active_model
        model_str = f"{active.name} ({active.model})" if active else "none"
        lines = [
            f"Model: {model_str}",
            f"Memory: {'active' if self._conversation else 'disabled'}",
            f"Skills: {len(self._registry.skills) if self._registry else 0} loaded",
            f"Scheduler: {'active' if self._scheduler and self._scheduler.running else 'disabled'}",
        ]
        return "\n".join(lines)

    def get_jobs_info(self) -> str:
        if self._scheduler:
            return self._scheduler.get_jobs_info()
        return "Scheduler not configured."

    def pause_scheduler(self) -> None:
        if self._scheduler:
            self._scheduler.pause()

    def resume_scheduler(self) -> None:
        if self._scheduler:
            self._scheduler.resume()

    async def kill(self, user_id: int) -> None:
        """Emergency stop: clear memory, pause jobs, kill containers."""
        if self._conversation:
            await self._conversation.clear(user_id)
        if self._fact_store:
            await self._fact_store.clear(user_id)
        if self._scheduler:
            self._scheduler.pause()
        logger.warning("Kill switch activated by user %d", user_id)
