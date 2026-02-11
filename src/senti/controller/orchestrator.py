"""Main message processing pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
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
    from senti.memory.memory_store import MemoryStore
    from senti.scheduler.engine import SchedulerEngine
    from senti.scheduler.job_store import JobStore
    from senti.security.audit import AuditLogger
    from senti.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
You are a memory extraction assistant. Analyze the latest user/assistant exchange and decide what's worth remembering long-term about the user.

Existing memory titles (avoid duplicates):
{existing_titles}

Latest exchange:
User: {user_text}
Assistant: {assistant_text}

Return a JSON array of memories to save. Each object should have:
- "title": short descriptive title
- "content": the information to remember
- "category": one of "preference", "fact", "people", "goal", "general"
- "importance": 1-10 (how important is this to remember?)
- "update_title": (optional) if this updates an existing memory, put the existing title here

If nothing is worth remembering, return an empty array: []
Return ONLY valid JSON, no other text."""

SESSION_SUMMARY_PROMPT = """\
Summarize this conversation session concisely. Focus on:
- Key topics discussed
- Decisions made
- Tasks completed or requested
- Any important context for future conversations

Conversation:
{conversation}

Write a brief, factual summary (2-5 sentences)."""


class Orchestrator:
    """Central brain that wires gateway, LLM, tools, and memory."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        conversation: ConversationMemory | None = None,
        memory_store: MemoryStore | None = None,
        registry: SkillRegistry | None = None,
        tool_router: ToolRouter | None = None,
        redactor: Redactor | None = None,
        token_guard: TokenGuard | None = None,
        audit: AuditLogger | None = None,
        scheduler: SchedulerEngine | None = None,
        job_store: JobStore | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._conversation = conversation
        self._memory_store = memory_store
        self._registry = registry
        self._tool_router = tool_router
        self._redactor = redactor
        self._token_guard = token_guard
        self._audit = audit
        self._scheduler = scheduler
        self._job_store = job_store
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        path = self._settings.personality_path
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return "You are Senti, a helpful AI assistant."

    async def _build_system_prompt(self, user_id: int) -> str:
        """Build system prompt with injected memories and scheduled jobs."""
        parts = [self._system_prompt]

        # Inject memories
        if self._memory_store:
            context = await self._memory_store.get_context_memories(
                user_id, self._settings.memory_context_tokens
            )
            if context:
                parts.append(context)

        # Inject scheduled jobs
        if self._job_store:
            jobs = await self._job_store.list_for_user(user_id)
            if jobs:
                lines = [
                    f"- #{j['id']}: {j['description']} (cron: {j['cron_expression']}, tz: {j['timezone']})"
                    for j in jobs
                ]
                parts.append("\n## User's Scheduled Jobs\n" + "\n".join(lines))

        return "\n".join(parts)

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
        images: list[dict[str, str]] | None = None,
        update: Update | None = None,
    ) -> str:
        """Full message processing pipeline."""
        # 0. Check session boundary (generate summary if idle too long)
        if self._memory_store:
            await self._check_session_boundary(user_id)

        # 1. Redact user input
        if self._redactor:
            text = self._redactor.redact(text)

        # 2. Load conversation history
        history: list[dict[str, str]] = []
        if self._conversation:
            history = await self._conversation.get_history(user_id)

        # 3. Build messages
        if images:
            content: list[dict[str, Any]] = []
            for img in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime_type']};base64,{img['base64']}"},
                })
            content.append({"type": "text", "text": text})
            user_message: dict[str, Any] = {"role": "user", "content": content}
        else:
            user_message = {"role": "user", "content": text}

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": await self._build_system_prompt(user_id)},
            *history,
            user_message,
        ]

        # 4. Get tool definitions
        tools = self._get_tool_definitions()

        # 5. LLM completion
        response = await self._llm.complete(messages, tools=tools)

        # Track cumulative token usage across all LLM rounds
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model": ""}
        usage = response.get("usage", {})
        total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
        total_usage["total_tokens"] += usage.get("total_tokens", 0)
        total_usage["model"] = usage.get("model", "")

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
            usage = response.get("usage", {})
            total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
            total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
            total_usage["total_tokens"] += usage.get("total_tokens", 0)

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

        # 10. Log token usage
        if self._audit and total_usage["total_tokens"] > 0:
            await self._audit.log_llm_usage(
                user_id,
                total_usage["model"],
                total_usage["prompt_tokens"],
                total_usage["completion_tokens"],
                total_usage["total_tokens"],
            )

        # 11. Autonomous memory extraction (fire-and-forget)
        if self._memory_store and len(text) >= 10:
            asyncio.create_task(self._extract_memories(user_id, text, final_text))

        # 12. Update session tracker
        if self._memory_store:
            await self._memory_store.update_session_tracker(user_id)

        return final_text

    async def _extract_memories(self, user_id: int, user_text: str, assistant_text: str) -> None:
        """Background task: extract memories from the latest exchange."""
        try:
            existing_titles = await self._memory_store.get_memory_titles(user_id)
            titles_str = "\n".join(f"- {t}" for t in existing_titles) if existing_titles else "(none)"

            prompt = EXTRACTION_PROMPT.format(
                existing_titles=titles_str,
                user_text=user_text,
                assistant_text=assistant_text,
            )

            messages = [
                {"role": "system", "content": "You extract structured memories from conversations. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ]

            response = await self._llm.complete(messages, tools=None)
            raw = response.get("content", "").strip()

            # Try to parse JSON from the response
            # Handle cases where the LLM wraps JSON in markdown code blocks
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            memories = json.loads(raw)
            if not isinstance(memories, list):
                return

            for mem in memories:
                if not isinstance(mem, dict):
                    continue
                title = mem.get("title", "").strip()
                content = mem.get("content", "").strip()
                if not title or not content:
                    continue

                # If update_title is specified, find and update the existing memory
                update_title = mem.get("update_title", "").strip()
                if update_title:
                    from difflib import SequenceMatcher
                    existing = await self._memory_store.list_memories(user_id)
                    for ex in existing:
                        ratio = SequenceMatcher(None, update_title.lower(), ex["title"].lower()).ratio()
                        if ratio > 0.85:
                            await self._memory_store.update_memory(
                                ex["id"],
                                content=content,
                                title=title,
                                importance=mem.get("importance", 5),
                            )
                            break
                    continue

                await self._memory_store.save_memory(
                    user_id=user_id,
                    title=title,
                    content=content,
                    category=mem.get("category", "general"),
                    importance=mem.get("importance", 5),
                    source="auto",
                )

        except Exception:
            logger.debug("Memory extraction failed (non-critical)", exc_info=True)

    async def _check_session_boundary(self, user_id: int) -> None:
        """Check if session has been idle long enough to generate a summary."""
        try:
            session = await self._memory_store.get_session_info(user_id)
            if not session:
                return

            # Check conditions: idle > timeout, enough messages, not already summarized
            if session["session_summarized"] or session["message_count"] < 4:
                return

            last_msg = session["last_message_at"]
            if isinstance(last_msg, str):
                last_msg = datetime.fromisoformat(last_msg)
            if last_msg.tzinfo is None:
                last_msg = last_msg.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            idle_minutes = (now - last_msg).total_seconds() / 60

            if idle_minutes >= self._settings.session_idle_timeout_minutes:
                await self._generate_session_summary(user_id)

        except Exception:
            logger.debug("Session boundary check failed (non-critical)", exc_info=True)

    async def _generate_session_summary(self, user_id: int) -> None:
        """Generate a summary of the recent conversation session."""
        try:
            if not self._conversation:
                return

            history = await self._conversation.get_history(user_id)
            if not history:
                return

            # Format conversation for summarization
            conv_text = "\n".join(
                f"{msg['role'].title()}: {msg['content']}" for msg in history
            )

            prompt = SESSION_SUMMARY_PROMPT.format(conversation=conv_text)
            messages = [
                {"role": "system", "content": "You summarize conversations concisely."},
                {"role": "user", "content": prompt},
            ]

            response = await self._llm.complete(messages, tools=None)
            summary = response.get("content", "").strip()

            if summary:
                now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                await self._memory_store.save_memory(
                    user_id=user_id,
                    title=f"Session summary {now}",
                    content=summary,
                    category="session_summary",
                    importance=4,
                    source="auto",
                )
                await self._memory_store.mark_session_summarized(user_id)
                logger.info("Generated session summary for user %d", user_id)

        except Exception:
            logger.debug("Session summary generation failed (non-critical)", exc_info=True)

    async def undo(self, user_id: int) -> int:
        """Remove the last conversation turn. Returns rows deleted."""
        if self._conversation:
            return await self._conversation.undo(user_id)
        return 0

    async def reset_conversation(self, user_id: int) -> None:
        if self._conversation:
            await self._conversation.clear(user_id)

    async def list_memories(self, user_id: int) -> list[dict[str, Any]]:
        if self._memory_store:
            return await self._memory_store.list_memories(user_id)
        return []

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

    async def list_jobs(self, user_id: int) -> list[dict[str, Any]]:
        """Return persisted scheduled jobs for a user."""
        if self._job_store:
            return await self._job_store.list_for_user(user_id)
        return []

    def pause_scheduler(self) -> None:
        if self._scheduler:
            self._scheduler.pause()

    def resume_scheduler(self) -> None:
        if self._scheduler:
            self._scheduler.resume()

    async def get_usage_stats(self, user_id: int) -> str:
        """Return formatted token usage stats for a user."""
        if not self._audit:
            return "Usage tracking not available."
        today = await self._audit.get_usage_today(user_id)
        by_model = await self._audit.get_usage_by_model(user_id)
        alltime = await self._audit.get_usage_alltime(user_id)

        lines = [
            f"Today: {today['total']:,} tokens ({today['prompt']:,} prompt / {today['completion']:,} completion)",
        ]
        if by_model:
            lines.append("\nBy model:")
            for entry in by_model:
                lines.append(f"  {entry['model']}: {entry['total']:,} tokens")
        lines.append(f"\nAll time: {alltime:,} tokens")
        return "\n".join(lines)

    async def kill(self, user_id: int) -> None:
        """Emergency stop: clear memory, pause jobs, kill containers."""
        if self._conversation:
            await self._conversation.clear(user_id)
        if self._memory_store:
            await self._memory_store.clear(user_id)
        if self._scheduler:
            self._scheduler.pause()
        logger.warning("Kill switch activated by user %d", user_id)
