"""Built-in scheduled jobs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from senti.config import Settings
    from senti.controller.orchestrator import Orchestrator
    from senti.scheduler.engine import SchedulerEngine

logger = logging.getLogger(__name__)


async def self_reflect_job(orchestrator: Orchestrator, settings: Settings) -> None:
    """Periodic self-reflection: sends a synthetic message through the orchestrator."""
    # Use the first allowed user ID as the target for notifications
    if not settings.allowed_telegram_user_ids:
        return

    user_id = settings.allowed_telegram_user_ids[0]
    prompt = (
        "Reflect briefly on recent conversations. "
        "Summarize any pending tasks or things to follow up on. "
        "If there's nothing noteworthy, just say so."
    )

    try:
        response = await orchestrator.process_message(user_id, prompt)
        logger.info("Self-reflect completed: %s", response[:100])
    except Exception:
        logger.exception("Self-reflect job failed")


def register_jobs(
    scheduler: SchedulerEngine,
    orchestrator: Orchestrator,
    settings: Settings,
) -> None:
    """Register scheduled jobs from config/schedules.yaml."""
    path = settings.schedules_config_path
    if not path.exists():
        logger.debug("No schedules config at %s", path)
        return

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    for name, cfg in raw.get("jobs", {}).items():
        if not cfg.get("enabled", True):
            continue

        cron_expr = cfg.get("cron", "")
        if not cron_expr:
            continue

        parts = cron_expr.split()
        if len(parts) != 5:
            logger.warning("Invalid cron expression for job %s: %s", name, cron_expr)
            continue

        minute, hour, day, month, day_of_week = parts

        if name == "self_reflect":
            scheduler.scheduler.add_job(
                self_reflect_job,
                "cron",
                args=[orchestrator, settings],
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                name=name,
                id=name,
                replace_existing=True,
            )
            logger.info("Registered job: %s (cron: %s)", name, cron_expr)
        else:
            logger.warning("Unknown job type: %s", name)
