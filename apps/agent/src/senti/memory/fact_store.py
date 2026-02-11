"""Key-value fact storage backed by SQLite."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senti.memory.database import Database

logger = logging.getLogger(__name__)


class FactStore:
    """Per-user key-value fact store."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_fact(self, user_id: int, key: str, value: str) -> str:
        """Save or update a fact. Returns confirmation message."""
        await self._db.conn.execute(
            """
            INSERT INTO facts (user_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, key.lower().strip(), value.strip()),
        )
        await self._db.conn.commit()
        logger.info("Saved fact for user %d: %s", user_id, key)
        return f"Saved: {key} = {value}"

    async def get_fact(self, user_id: int, key: str) -> str:
        """Retrieve a fact by key."""
        cursor = await self._db.conn.execute(
            "SELECT value FROM facts WHERE user_id = ? AND key = ?",
            (user_id, key.lower().strip()),
        )
        row = await cursor.fetchone()
        if row:
            return row["value"]
        return f"No fact found for '{key}'."

    async def list_facts(self, user_id: int) -> dict[str, str]:
        """List all facts for a user."""
        cursor = await self._db.conn.execute(
            "SELECT key, value FROM facts WHERE user_id = ? ORDER BY key",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def delete_fact(self, user_id: int, key: str) -> str:
        """Delete a fact by key."""
        result = await self._db.conn.execute(
            "DELETE FROM facts WHERE user_id = ? AND key = ?",
            (user_id, key.lower().strip()),
        )
        await self._db.conn.commit()
        if result.rowcount > 0:
            return f"Deleted fact: {key}"
        return f"No fact found for '{key}'."

    async def clear(self, user_id: int) -> None:
        """Delete all facts for a user."""
        await self._db.conn.execute(
            "DELETE FROM facts WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.commit()
