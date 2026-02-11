"""CRUD for the user_skills table."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from senti.memory.database import Database

logger = logging.getLogger(__name__)

MAX_SKILLS_PER_USER = 50


class UserSkillStore:
    """Async CRUD for user-created skills."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        user_id: int,
        name: str,
        description: str,
        parameters_json: str,
        code: str,
    ) -> dict[str, Any]:
        """Insert a new user skill and return its row as a dict."""
        count = await self.count(user_id)
        if count >= MAX_SKILLS_PER_USER:
            raise ValueError(f"Skill limit reached ({MAX_SKILLS_PER_USER})")

        # Check name uniqueness for this user
        existing = await self.get_by_name(user_id, name)
        if existing:
            raise ValueError(f"Skill '{name}' already exists")

        async with self._db.conn.execute(
            """INSERT INTO user_skills
               (user_id, name, description, parameters_json, code)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, name, description, parameters_json, code),
        ) as cursor:
            skill_id = cursor.lastrowid
        await self._db.conn.commit()

        return {
            "id": skill_id,
            "user_id": user_id,
            "name": name,
            "description": description,
            "parameters_json": parameters_json,
            "code": code,
            "enabled": 1,
            "trusted": 0,
        }

    async def get_by_name(self, user_id: int, name: str) -> dict[str, Any] | None:
        """Return a skill by name for a given user, or None."""
        async with self._db.conn.execute(
            "SELECT * FROM user_skills WHERE user_id = ? AND name = ? AND enabled = 1",
            (user_id, name),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """Return all enabled skills for a given user."""
        async with self._db.conn.execute(
            "SELECT * FROM user_skills WHERE user_id = ? AND enabled = 1 ORDER BY id",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_all_enabled(self) -> list[dict[str, Any]]:
        """Return all enabled skills (for startup reload)."""
        async with self._db.conn.execute(
            "SELECT * FROM user_skills WHERE enabled = 1 ORDER BY id",
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete(self, name: str, user_id: int) -> bool:
        """Soft-delete a skill by name, scoped to user. Returns True if deleted."""
        async with self._db.conn.execute(
            "UPDATE user_skills SET enabled = 0 WHERE name = ? AND user_id = ? AND enabled = 1",
            (name, user_id),
        ) as cursor:
            updated = cursor.rowcount > 0
        await self._db.conn.commit()
        return updated

    async def set_trusted(self, name: str, user_id: int, trusted: bool) -> bool:
        """Set or unset the trusted flag for a skill."""
        async with self._db.conn.execute(
            "UPDATE user_skills SET trusted = ? WHERE name = ? AND user_id = ? AND enabled = 1",
            (1 if trusted else 0, name, user_id),
        ) as cursor:
            updated = cursor.rowcount > 0
        await self._db.conn.commit()
        return updated

    async def count(self, user_id: int) -> int:
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM user_skills WHERE user_id = ? AND enabled = 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0
