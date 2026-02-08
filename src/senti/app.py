"""Bootstrap: wires all subsystems together."""

from __future__ import annotations

import logging

from senti.config import Settings, get_settings
from senti.controller.llm_client import LLMClient
from senti.controller.orchestrator import Orchestrator
from senti.controller.redaction import Redactor
from senti.controller.token_guard import TokenGuard
from senti.controller.tool_router import ToolRouter
from senti.gateway.bot import build_bot
from senti.gateway.hitl import HITLManager
from senti.logging_config import setup_logging
from senti.memory.conversation import ConversationMemory
from senti.memory.database import Database
from senti.memory.fact_store import FactStore
from senti.sandbox.executor import SandboxExecutor
from senti.scheduler.engine import SchedulerEngine
from senti.scheduler.jobs import register_jobs
from senti.security.audit import AuditLogger
from senti.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


async def create_app():
    """Wire everything and return the Telegram Application."""
    settings = get_settings()
    setup_logging(settings)

    logger.info("Starting Senti...")

    # Database
    db = Database(settings.db_path)
    await db.initialize()

    # Memory
    conversation = ConversationMemory(db, window_size=settings.conversation_window_size)
    fact_store = FactStore(db)

    # LLM
    llm = LLMClient(settings)

    # Skills
    registry = SkillRegistry(settings)
    registry.discover()

    # Redaction
    redactor = Redactor(settings)

    # Token guard
    token_guard = TokenGuard(settings)

    # Audit
    audit = AuditLogger(db)

    # HITL
    hitl = HITLManager()

    # Sandbox
    try:
        sandbox = SandboxExecutor()
    except Exception:
        logger.warning("Docker not available — sandbox skills will be disabled")
        sandbox = None

    # Tool router
    tool_router = ToolRouter(
        registry, fact_store=fact_store, sandbox=sandbox, hitl=hitl, settings=settings
    )

    # Scheduler
    scheduler = SchedulerEngine()

    # Orchestrator
    orchestrator = Orchestrator(
        settings=settings,
        llm=llm,
        conversation=conversation,
        fact_store=fact_store,
        registry=registry,
        tool_router=tool_router,
        redactor=redactor,
        token_guard=token_guard,
        audit=audit,
        scheduler=scheduler,
    )

    # Register scheduled jobs
    register_jobs(scheduler, orchestrator, settings)

    # Build Telegram bot
    app = build_bot(settings, orchestrator, hitl=hitl)

    # Start scheduler
    scheduler.start()

    logger.info("Senti ready.")
    return app
