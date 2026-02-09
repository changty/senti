"""Scheduler skill: create, list, delete user-scheduled jobs."""

from __future__ import annotations

import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from senti.config import Settings
from senti.skills.base import BaseSkill

logger = logging.getLogger(__name__)


def _validate_cron(expr: str) -> str | None:
    """Validate a 5-field cron expression. Returns error message or None."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return f"Expected 5 fields (minute hour day month weekday), got {len(parts)}"
    return None


class SchedulerSkill(BaseSkill):
    """In-process skill for managing user-created scheduled jobs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return "scheduler"

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_scheduled_job",
                    "description": (
                        "Create a scheduled job that will run a prompt at the specified times. "
                        "Convert the user's natural language schedule to a 5-field cron expression "
                        "(minute hour day month weekday). The prompt will be sent through the AI "
                        "and the result delivered to the user."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "Human-readable description of the job",
                            },
                            "cron": {
                                "type": "string",
                                "description": "5-field cron expression (minute hour day month weekday)",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The prompt to execute on each trigger",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone (e.g. 'Europe/Helsinki'). Defaults to UTC.",
                            },
                        },
                        "required": ["description", "cron", "prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_jobs",
                    "description": "List all scheduled jobs for the current user.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_scheduled_job",
                    "description": "Delete a scheduled job by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_id": {
                                "type": "integer",
                                "description": "The ID of the job to delete",
                            },
                        },
                        "required": ["job_id"],
                    },
                },
            },
        ]

    async def execute(self, function_name: str, arguments: dict[str, Any], **kwargs: Any) -> str:
        job_store = kwargs.get("job_store")
        scheduler = kwargs.get("scheduler")
        orchestrator = kwargs.get("orchestrator")
        user_id: int = kwargs.get("user_id", 0)
        chat_id: int = kwargs.get("chat_id", 0)

        if not job_store:
            return "Scheduler not available."

        if function_name == "create_scheduled_job":
            return await self._create(
                arguments, job_store, scheduler, orchestrator, user_id, chat_id,
            )
        elif function_name == "list_scheduled_jobs":
            return await self._list(job_store, user_id)
        elif function_name == "delete_scheduled_job":
            return await self._delete(arguments, job_store, scheduler, user_id)

        return f"Unknown function: {function_name}"

    async def _create(self, args, job_store, scheduler, orchestrator, user_id, chat_id) -> str:
        cron = args.get("cron", "").strip()
        err = _validate_cron(cron)
        if err:
            return f"Invalid cron expression: {err}"

        tz = args.get("timezone", "UTC")
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, KeyError):
            return f"Unknown timezone: {tz}"

        description = args.get("description", "")
        prompt = args.get("prompt", "")

        try:
            job = await job_store.create(
                user_id=user_id,
                chat_id=chat_id,
                description=description,
                cron_expression=cron,
                prompt=prompt,
                timezone=tz,
            )
        except ValueError as exc:
            return str(exc)

        # Register with APScheduler
        if scheduler and orchestrator:
            from senti.scheduler.jobs import add_user_job
            add_user_job(scheduler, orchestrator, job)

        return f"Job #{job['id']} created: {description} (cron: {cron}, tz: {tz})"

    async def _list(self, job_store, user_id) -> str:
        jobs = await job_store.list_for_user(user_id)
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            status = "enabled" if j.get("enabled") else "disabled"
            lines.append(
                f"#{j['id']}: {j['description']} — cron: {j['cron_expression']} "
                f"(tz: {j['timezone']}, {status})"
            )
        return "\n".join(lines)

    async def _delete(self, args, job_store, scheduler, user_id) -> str:
        job_id = args.get("job_id")
        if job_id is None:
            return "Missing job_id."

        deleted = await job_store.delete(int(job_id), user_id)
        if not deleted:
            return f"Job #{job_id} not found or not owned by you."

        # Remove from APScheduler
        if scheduler:
            from senti.scheduler.jobs import remove_user_job
            remove_user_job(scheduler, int(job_id))

        return f"Job #{job_id} deleted."
