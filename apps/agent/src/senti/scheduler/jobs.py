"""Built-in and user-created scheduled jobs."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from telegram import Bot

    from senti.config import Settings
    from senti.controller.orchestrator import Orchestrator
    from senti.scheduler.engine import SchedulerEngine
    from senti.scheduler.job_store import JobStore

logger = logging.getLogger(__name__)

# Module-level bot reference, set via set_bot()
_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    """Store the Telegram Bot instance for delivering scheduled messages."""
    global _bot
    _bot = bot


async def self_reflect_job(orchestrator: Orchestrator, settings: Settings) -> None:
    """Periodic self-reflection: sends result to Telegram."""
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
        if _bot and settings.allowed_telegram_user_ids:
            from senti.gateway.formatters import format_response
            try:
                await _bot.send_message(
                    chat_id=user_id,
                    text=format_response(response),
                    parse_mode="HTML",
                )
            except Exception:
                await _bot.send_message(chat_id=user_id, text=response[:4096])
        logger.info("Self-reflect completed: %s", response[:100])
    except Exception:
        logger.exception("Self-reflect job failed")


async def execute_user_job(
    orchestrator: Orchestrator,
    job: dict[str, Any],
) -> None:
    """Execute a user-created scheduled job and deliver results via Telegram."""
    user_id = job["user_id"]
    chat_id = job["chat_id"]
    prompt = job["prompt"]
    job_id = job["id"]

    logger.info("Executing user job #%d for user %d", job_id, user_id)
    try:
        response = await orchestrator.process_message(user_id, prompt)
        if _bot:
            from senti.gateway.formatters import format_response
            try:
                await _bot.send_message(
                    chat_id=chat_id,
                    text=format_response(response),
                    parse_mode="HTML",
                )
            except Exception:
                await _bot.send_message(chat_id=chat_id, text=response[:4096])
    except Exception:
        logger.exception("User job #%d failed", job_id)
        if _bot:
            try:
                await _bot.send_message(
                    chat_id=chat_id,
                    text=f"Scheduled job #{job_id} failed. Check logs for details.",
                )
            except Exception:
                logger.exception("Failed to notify user about job #%d failure", job_id)


def _user_job_id(job_id: int) -> str:
    """APScheduler job id for a user job."""
    return f"user_job_{job_id}"


def add_user_job(
    scheduler: SchedulerEngine,
    orchestrator: Orchestrator,
    job: dict[str, Any],
) -> None:
    """Register a single user job with APScheduler."""
    cron = job["cron_expression"].split()
    if len(cron) != 5:
        logger.warning("Invalid cron for job #%d: %s", job["id"], job["cron_expression"])
        return

    minute, hour, day, month, day_of_week = cron
    tz = job.get("timezone", "UTC")

    from apscheduler.triggers.cron import CronTrigger

    trigger = CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week,
        timezone=tz,
    )

    scheduler.scheduler.add_job(
        execute_user_job,
        trigger,
        args=[orchestrator, job],
        name=f"user: {job.get('description', '')}",
        id=_user_job_id(job["id"]),
        replace_existing=True,
    )
    logger.info("Registered user job #%d (cron: %s, tz: %s)", job["id"], job["cron_expression"], tz)


def remove_user_job(scheduler: SchedulerEngine, job_id: int) -> None:
    """Remove a user job from APScheduler."""
    apid = _user_job_id(job_id)
    try:
        scheduler.scheduler.remove_job(apid)
        logger.info("Removed user job #%d from scheduler", job_id)
    except Exception:
        logger.debug("Job %s not found in scheduler (already removed?)", apid)


async def reload_user_jobs(
    scheduler: SchedulerEngine,
    orchestrator: Orchestrator,
    job_store: JobStore,
) -> None:
    """Load all enabled user jobs from DB and register with APScheduler."""
    jobs = await job_store.list_all_enabled()
    for job in jobs:
        add_user_job(scheduler, orchestrator, job)
    if jobs:
        logger.info("Reloaded %d user jobs from database", len(jobs))


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
