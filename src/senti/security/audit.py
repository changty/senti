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
