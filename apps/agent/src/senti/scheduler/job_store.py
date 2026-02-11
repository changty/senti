"""CRUD for the scheduled_jobs table."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from senti.memory.database import Database

logger = logging.getLogger(__name__)

MAX_JOBS_PER_USER = 20


class JobStore:
    """Async CRUD for user-created scheduled jobs."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        user_id: int,
        chat_id: int,
        description: str,
        cron_expression: str,
        prompt: str,
        timezone: str = "UTC",
    ) -> dict[str, Any]:
        """Insert a new job and return its row as a dict."""
        count = await self.count(user_id)
        if count >= MAX_JOBS_PER_USER:
            raise ValueError(f"Job limit reached ({MAX_JOBS_PER_USER})")

        async with self._db.conn.execute(
            """INSERT INTO scheduled_jobs
               (user_id, chat_id, description, cron_expression, prompt, timezone)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, chat_id, description, cron_expression, prompt, timezone),
        ) as cursor:
            job_id = cursor.lastrowid
        await self._db.conn.commit()

        return {
            "id": job_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "description": description,
            "cron_expression": cron_expression,
            "prompt": prompt,
            "timezone": timezone,
            "enabled": True,
        }

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """Return all jobs for a given user."""
        async with self._db.conn.execute(
            "SELECT * FROM scheduled_jobs WHERE user_id = ? ORDER BY id",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, job_id: int, user_id: int) -> bool:
        """Delete a job by id, scoped to user. Returns True if deleted."""
        async with self._db.conn.execute(
            "DELETE FROM scheduled_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ) as cursor:
            deleted = cursor.rowcount > 0
        await self._db.conn.commit()
        return deleted

    async def count(self, user_id: int) -> int:
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM scheduled_jobs WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def list_all_enabled(self) -> list[dict[str, Any]]:
        """Return all enabled jobs (for startup reload)."""
        async with self._db.conn.execute(
            "SELECT * FROM scheduled_jobs WHERE enabled = 1 ORDER BY id",
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]
