"""Audit logging to SQLite."""

from __future__ import annotations

import json
import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from senti.memory.database import Database

logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes audit events to the audit_log SQLite table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def log_event(self, user_id: int | None, event_type: str, detail: str) -> None:
        """Log a generic audit event."""
        await self._db.conn.execute(
            "INSERT INTO audit_log (user_id, event_type, detail) VALUES (?, ?, ?)",
            (user_id, event_type, detail),
        )
        await self._db.conn.commit()

    async def log_tool_call(
        self, user_id: int, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """Log a tool call event."""
        detail = json.dumps({"tool": tool_name, "arguments": arguments}, ensure_ascii=False)
        await self.log_event(user_id, "tool_call", detail)

    async def log_approval(
        self, user_id: int, tool_name: str, approved: bool
    ) -> None:
        """Log an approval decision."""
        detail = json.dumps({"tool": tool_name, "approved": approved}, ensure_ascii=False)
        await self.log_event(user_id, "approval", detail)

    async def log_kill(self, user_id: int) -> None:
        """Log a kill switch activation."""
        await self.log_event(user_id, "kill_switch", "activated")

    async def log_llm_usage(
        self,
        user_id: int | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """Record LLM token usage."""
        await self._db.conn.execute(
            "INSERT INTO llm_usage (user_id, model, prompt_tokens, completion_tokens, total_tokens) VALUES (?, ?, ?, ?, ?)",
            (user_id, model, prompt_tokens, completion_tokens, total_tokens),
        )
        await self._db.conn.commit()

    async def get_usage_today(self, user_id: int) -> dict[str, int]:
        """Get today's token usage for a user."""
        cursor = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                   COALESCE(SUM(completion_tokens), 0) AS completion,
                   COALESCE(SUM(total_tokens), 0) AS total
            FROM llm_usage
            WHERE user_id = ? AND DATE(created_at) = DATE('now')
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        return {"prompt": row["prompt"], "completion": row["completion"], "total": row["total"]}

    async def get_usage_by_model(self, user_id: int) -> list[dict[str, Any]]:
        """Get today's token usage broken down by model."""
        cursor = await self._db.conn.execute(
            """
            SELECT model, COALESCE(SUM(total_tokens), 0) AS total
            FROM llm_usage
            WHERE user_id = ? AND DATE(created_at) = DATE('now')
            GROUP BY model
            ORDER BY total DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [{"model": row["model"], "total": row["total"]} for row in rows]

    async def get_usage_alltime(self, user_id: int) -> int:
        """Get all-time total tokens for a user."""
        cursor = await self._db.conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) AS total FROM llm_usage WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["total"]
