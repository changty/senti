"""Telegram command and message handlers."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from senti.exceptions import LLMError
from senti.gateway.formatters import format_response

if TYPE_CHECKING:
    from senti.controller.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def make_handlers(orchestrator: Orchestrator):
    """Create handler callbacks bound to the given orchestrator."""

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Hello! I'm Senti, your AI assistant. Send me a message and I'll do my best to help."
        )

    async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "Available commands:\n"
            "/start - Greeting\n"
            "/help - Show this help\n"
            "/model - List models or switch: /model <name>\n"
            "/reset - Clear conversation history\n"
            "/facts - List stored facts\n"
            "/status - System status\n"
            "/jobs - List scheduled jobs\n"
            "/undo - Remove last conversation turn\n"
            "/usage - Token usage stats\n"
            "/pause - Pause scheduler\n"
            "/resume - Resume scheduler\n"
            "/kill - Emergency stop"
        )
        await update.message.reply_text(text)

    async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        await orchestrator.reset_conversation(user_id)
        await update.message.reply_text("Conversation history cleared.")

    async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        deleted = await orchestrator.undo(user_id)
        if deleted:
            await update.message.reply_text("Last turn removed.")
        else:
            await update.message.reply_text("Nothing to undo.")

    async def cmd_facts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        facts = await orchestrator.list_facts(user_id)
        if not facts:
            await update.message.reply_text("No facts stored yet.")
            return
        lines = [f"- {k}: {v}" for k, v in facts.items()]
        await update.message.reply_text("Stored facts:\n" + "\n".join(lines))

    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        status = await orchestrator.get_status()
        await update.message.reply_text(status)

    async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        info = orchestrator.get_jobs_info()
        await update.message.reply_text(info or "No scheduled jobs.")

    async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        orchestrator.pause_scheduler()
        await update.message.reply_text("Scheduler paused.")

    async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        orchestrator.resume_scheduler()
        await update.message.reply_text("Scheduler resumed.")

    async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args
        models = orchestrator.list_models()

        if not args:
            # List available models
            active = orchestrator.active_model_name
            lines = []
            for name, cfg in models.items():
                marker = " (active)" if name == active else ""
                lines.append(f"  {name} — {cfg.description}{marker}")
            text = "Available models:\n" + "\n".join(lines) + "\n\nSwitch with: /model <name>"
            await update.message.reply_text(text)
            return

        name = args[0].strip()
        try:
            cfg = orchestrator.switch_model(name)
            await update.message.reply_text(f"Switched to {cfg.name} ({cfg.model})")
        except LLMError as exc:
            await update.message.reply_text(str(exc))

    async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        stats = await orchestrator.get_usage_stats(user_id)
        await update.message.reply_text(stats)

    async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        await orchestrator.kill(user_id)
        await update.message.reply_text("Kill switch activated. Memory cleared, jobs paused.")

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        text = update.message.text or ""
        if not text.strip():
            return

        logger.info("Message from user %d: %s", user_id, text[:80])
        try:
            response = await orchestrator.process_message(user_id, text, update=update)
            await update.message.reply_text(format_response(response))
        except Exception:
            logger.exception("Error processing message")
            await update.message.reply_text("Sorry, something went wrong. Please try again.")

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        caption = update.message.caption or "Describe this image."

        logger.info("Photo from user %d, caption: %s", user_id, caption[:80])
        try:
            photo = update.message.photo[-1]  # largest size
            file = await photo.get_file()
            data = await file.download_as_bytearray()
            encoded = base64.b64encode(bytes(data)).decode("ascii")
            image_dict = {"mime_type": "image/jpeg", "base64": encoded}

            response = await orchestrator.process_message(
                user_id, caption, images=[image_dict], update=update,
            )
            await update.message.reply_text(format_response(response))
        except Exception:
            logger.exception("Error processing photo")
            await update.message.reply_text("Sorry, something went wrong. Please try again.")

    return {
        "start": cmd_start,
        "help": cmd_help,
        "model": cmd_model,
        "reset": cmd_reset,
        "undo": cmd_undo,
        "facts": cmd_facts,
        "status": cmd_status,
        "usage": cmd_usage,
        "jobs": cmd_jobs,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "kill": cmd_kill,
        "message": handle_message,
        "photo": handle_photo,
    }
