"""Telegram bot application builder and handler registration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from senti.gateway.filters import AllowedUserFilter
from senti.gateway.handlers import make_handlers

if TYPE_CHECKING:
    from senti.config import Settings
    from senti.controller.orchestrator import Orchestrator
    from senti.gateway.hitl import HITLManager

logger = logging.getLogger(__name__)


def build_bot(
    settings: Settings,
    orchestrator: Orchestrator,
    hitl: HITLManager | None = None,
):
    """Build and configure the Telegram bot application."""
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )

    user_filter = AllowedUserFilter(settings.allowed_telegram_user_ids)
    h = make_handlers(orchestrator)

    # Register command handlers (filtered to allowed users)
    for cmd_name in ["start", "help", "model", "reset", "undo", "memories", "facts", "status", "usage", "jobs", "pause", "resume", "kill"]:
        app.add_handler(CommandHandler(cmd_name, h[cmd_name], filters=user_filter))

    # Register text message handler
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & user_filter, h["message"])
    )

    # Register photo handler
    app.add_handler(
        MessageHandler(filters.PHOTO & user_filter, h["photo"])
    )

    # Register document handler
    app.add_handler(
        MessageHandler(filters.Document.ALL & user_filter, h["document"])
    )

    # Register HITL callback handler
    if hitl:
        app.add_handler(hitl.get_callback_handler())

    return app
