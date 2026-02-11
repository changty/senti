"""Bootstrap: wires all subsystems together."""

from __future__ import annotations

import logging

from senti.config import get_settings
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
from senti.memory.memory_store import MemoryStore
from senti.sandbox.executor import SandboxExecutor
from senti.scheduler.engine import SchedulerEngine
from senti.scheduler.job_store import JobStore
from senti.scheduler.jobs import register_jobs, reload_user_jobs, set_bot
from senti.security.audit import AuditLogger
from senti.skills.registry import SkillRegistry
from senti.skills.user_skill_store import UserSkillStore

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
    memory_store = MemoryStore(db, settings.memories_dir)

    # Job store
    job_store = JobStore(db)

    # LLM
    llm = LLMClient(settings)

    # User skill store
    user_skill_store = UserSkillStore(db)

    # Skills
    registry = SkillRegistry(settings)
    registry.discover()

    # Load persisted user skills
    persisted_skills = await user_skill_store.list_all_enabled()
    registry.load_user_skills(persisted_skills)

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

    # Scheduler
    scheduler = SchedulerEngine()

    # Migrate facts to memories (idempotent)
    await memory_store.migrate_from_facts(fact_store)

    # Tool router (orchestrator back-linked below)
    tool_router = ToolRouter(
        registry,
        memory_store=memory_store,
        sandbox=sandbox,
        hitl=hitl,
        settings=settings,
        job_store=job_store,
        scheduler=scheduler,
        user_skill_store=user_skill_store,
    )

    # Orchestrator
    orchestrator = Orchestrator(
        settings=settings,
        llm=llm,
        conversation=conversation,
        memory_store=memory_store,
        registry=registry,
        tool_router=tool_router,
        redactor=redactor,
        token_guard=token_guard,
        audit=audit,
        scheduler=scheduler,
        job_store=job_store,
    )

    # Back-link orchestrator into tool_router (resolves circular dependency)
    tool_router._orchestrator = orchestrator

    # Register config-driven scheduled jobs
    register_jobs(scheduler, orchestrator, settings)

    # Build Telegram bot
    app = build_bot(settings, orchestrator, hitl=hitl)

    # Give scheduler access to the bot for delivering messages
    set_bot(app.bot)

    # Reload user-created jobs from DB
    await reload_user_jobs(scheduler, orchestrator, job_store)

    # Start scheduler
    scheduler.start()

    # Store db reference for graceful shutdown
    app.bot_data["db"] = db

    logger.info("Senti ready.")
    return app
