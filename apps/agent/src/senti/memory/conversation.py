"""Sliding-window conversation buffer backed by SQLite."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senti.memory.database import Database

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Per-user sliding window of recent messages."""

    def __init__(self, db: Database, window_size: int = 20) -> None:
        self._db = db
        self._window = window_size

    async def add_message(self, user_id: int, role: str, content: str) -> None:
        """Append a message and evict oldest if over window size."""
        await self._db.conn.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await self._db.conn.commit()

        # Evict old messages beyond window
        await self._db.conn.execute(
            """
            DELETE FROM conversations
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM conversations
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (user_id, user_id, self._window),
        )
        await self._db.conn.commit()

    async def get_history(self, user_id: int) -> list[dict[str, str]]:
        """Return the most recent messages for a user."""
        cursor = await self._db.conn.execute(
            """
            SELECT role, content FROM conversations
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        # Only return the last window_size messages
        rows = rows[-self._window:]
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    async def undo(self, user_id: int, turns: int = 1) -> int:
        """Remove the last N turns (each turn = 1 user + 1 assistant message).

        Returns the number of rows deleted.
        """
        limit = turns * 2
        cursor = await self._db.conn.execute(
            """
            DELETE FROM conversations
            WHERE id IN (
                SELECT id FROM conversations
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (user_id, limit),
        )
        await self._db.conn.commit()
        deleted = cursor.rowcount
        logger.info("Undo: removed %d messages for user %d", deleted, user_id)
        return deleted

    async def clear(self, user_id: int) -> None:
        """Delete all conversation history for a user."""
        await self._db.conn.execute(
            "DELETE FROM conversations WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.commit()
        logger.info("Cleared conversation for user %d", user_id)
