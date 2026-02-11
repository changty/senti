"""Rich memory storage with markdown files + SQLite metadata."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from senti.memory.database import Database
    from senti.memory.fact_store import FactStore

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"preference", "fact", "people", "goal", "session_summary", "general"}


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "memory"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode()).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


class MemoryStore:
    """Dual-layer memory: markdown files on disk + SQLite metadata."""

    def __init__(self, db: Database, memories_dir: Path) -> None:
        self._db = db
        self._memories_dir = memories_dir

    def _user_dir(self, user_id: int, category: str) -> Path:
        return self._memories_dir / str(user_id) / category

    def _write_markdown(self, memory: dict[str, Any]) -> Path:
        """Write a memory as a markdown file with YAML frontmatter."""
        category = memory["category"]
        user_id = memory["user_id"]
        mem_id = memory["id"]
        slug = _slugify(memory["title"])

        dir_path = self._user_dir(user_id, category)
        dir_path.mkdir(parents=True, exist_ok=True)

        file_path = dir_path / f"{slug}-{mem_id}.md"

        frontmatter = {
            "id": mem_id,
            "category": category,
            "title": memory["title"],
            "importance": memory["importance"],
            "source": memory["source"],
            "created": memory["created_at"],
            "updated": memory["updated_at"],
        }

        content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n{memory['content']}\n"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def _delete_markdown(self, file_path: str) -> None:
        """Delete a markdown file if it exists."""
        p = Path(file_path)
        if p.exists():
            p.unlink()

    async def _find_similar_title(self, user_id: int, title: str, category: str) -> dict[str, Any] | None:
        """Find an existing memory with a similar title (SequenceMatcher > 0.85)."""
        cursor = await self._db.conn.execute(
            "SELECT id, title, content, category, importance, source, file_path, "
            "content_hash, created_at, updated_at FROM memories "
            "WHERE user_id = ? AND category = ?",
            (user_id, category),
        )
        rows = await cursor.fetchall()
        for row in rows:
            ratio = SequenceMatcher(None, title.lower(), row["title"].lower()).ratio()
            if ratio > 0.85:
                return dict(row)
        return None

    async def save_memory(
        self,
        user_id: int,
        title: str,
        content: str,
        category: str = "general",
        importance: int = 5,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Save a new memory. Deduplicates by content hash and fuzzy title match."""
        if category not in VALID_CATEGORIES:
            category = "general"
        importance = max(1, min(10, importance))

        c_hash = _content_hash(content)

        # Check exact content duplicate
        cursor = await self._db.conn.execute(
            "SELECT id FROM memories WHERE user_id = ? AND content_hash = ?",
            (user_id, c_hash),
        )
        existing = await cursor.fetchone()
        if existing:
            # Content already stored, just update access time
            await self._db.conn.execute(
                "UPDATE memories SET last_accessed = CURRENT_TIMESTAMP, "
                "access_count = access_count + 1 WHERE id = ?",
                (existing["id"],),
            )
            await self._db.conn.commit()
            return await self.get_memory(existing["id"])

        # Check fuzzy title match — update instead of duplicate
        similar = await self._find_similar_title(user_id, title, category)
        if similar:
            return await self.update_memory(
                similar["id"],
                content=content,
                title=title,
                importance=importance,
            )

        # Insert new
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.conn.execute(
            "INSERT INTO memories (user_id, category, title, content, content_hash, "
            "file_path, importance, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, category, title, content, c_hash, "", importance, source, now, now),
        )
        await self._db.conn.commit()
        mem_id = cursor.lastrowid

        memory = {
            "id": mem_id,
            "user_id": user_id,
            "category": category,
            "title": title,
            "content": content,
            "importance": importance,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }

        # Write markdown file and update file_path in DB
        file_path = self._write_markdown(memory)
        await self._db.conn.execute(
            "UPDATE memories SET file_path = ? WHERE id = ?",
            (str(file_path), mem_id),
        )
        await self._db.conn.commit()
        memory["file_path"] = str(file_path)

        logger.info("Saved memory #%d for user %d: %s", mem_id, user_id, title)
        return memory

    async def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        """Get a single memory by ID."""
        cursor = await self._db.conn.execute(
            "SELECT id, user_id, category, title, content, importance, source, "
            "file_path, created_at, updated_at, last_accessed, access_count "
            "FROM memories WHERE id = ?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None

    async def update_memory(
        self,
        memory_id: int,
        *,
        content: str | None = None,
        title: str | None = None,
        importance: int | None = None,
    ) -> dict[str, Any] | None:
        """Update an existing memory."""
        memory = await self.get_memory(memory_id)
        if not memory:
            return None

        updates: list[str] = []
        params: list[Any] = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
            updates.append("content_hash = ?")
            params.append(_content_hash(content))
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if importance is not None:
            importance = max(1, min(10, importance))
            updates.append("importance = ?")
            params.append(importance)

        if not updates:
            return memory

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)

        await self._db.conn.execute(
            f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.conn.commit()

        # Re-fetch and rewrite markdown
        updated = await self.get_memory(memory_id)
        if updated:
            # Delete old file if path changed
            old_path = memory.get("file_path", "")
            new_path = self._write_markdown(updated)
            if old_path and old_path != str(new_path):
                self._delete_markdown(old_path)
            await self._db.conn.execute(
                "UPDATE memories SET file_path = ? WHERE id = ?",
                (str(new_path), memory_id),
            )
            await self._db.conn.commit()
            updated["file_path"] = str(new_path)

        logger.info("Updated memory #%d", memory_id)
        return updated

    async def delete_memory(self, memory_id: int) -> bool:
        """Delete a memory by ID."""
        memory = await self.get_memory(memory_id)
        if not memory:
            return False

        self._delete_markdown(memory.get("file_path", ""))

        await self._db.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await self._db.conn.commit()
        logger.info("Deleted memory #%d", memory_id)
        return True

    async def search_memories(
        self,
        user_id: int,
        query: str,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories using LIKE with AND logic across terms."""
        terms = query.lower().split()
        if not terms:
            return []

        conditions = ["user_id = ?"]
        params: list[Any] = [user_id]

        if category and category in VALID_CATEGORIES:
            conditions.append("category = ?")
            params.append(category)

        for term in terms:
            conditions.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])

        sql = (
            "SELECT id, user_id, category, title, content, importance, source, "
            "created_at, updated_at FROM memories WHERE "
            + " AND ".join(conditions)
            + " ORDER BY importance DESC, updated_at DESC LIMIT 20"
        )

        cursor = await self._db.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def list_memories(
        self,
        user_id: int,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all memories for a user, optionally filtered by category."""
        if category and category in VALID_CATEGORIES:
            cursor = await self._db.conn.execute(
                "SELECT id, category, title, importance, source, created_at, updated_at "
                "FROM memories WHERE user_id = ? AND category = ? "
                "ORDER BY category, importance DESC",
                (user_id, category),
            )
        else:
            cursor = await self._db.conn.execute(
                "SELECT id, category, title, importance, source, created_at, updated_at "
                "FROM memories WHERE user_id = ? ORDER BY category, importance DESC",
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_context_memories(self, user_id: int, token_budget: int = 1500) -> str:
        """Select top memories by importance/recency and format for system prompt."""
        cursor = await self._db.conn.execute(
            "SELECT id, category, title, content, importance FROM memories "
            "WHERE user_id = ? AND category != 'session_summary' "
            "ORDER BY importance DESC, updated_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return ""

        # Build context string within token budget
        by_category: dict[str, list[str]] = {}
        used_tokens = 0
        included_ids: list[int] = []

        for row in rows:
            line = f"- {row['title']}: {row['content']}"
            line_tokens = _estimate_tokens(line)
            if used_tokens + line_tokens > token_budget:
                break
            cat = row["category"]
            by_category.setdefault(cat, []).append(line)
            used_tokens += line_tokens
            included_ids.append(row["id"])

        if not included_ids:
            return ""

        # Update access stats for included memories
        placeholders = ",".join("?" * len(included_ids))
        await self._db.conn.execute(
            f"UPDATE memories SET last_accessed = CURRENT_TIMESTAMP, "
            f"access_count = access_count + 1 WHERE id IN ({placeholders})",
            included_ids,
        )
        await self._db.conn.commit()

        # Format by category
        category_labels = {
            "preference": "Preferences",
            "fact": "Facts",
            "people": "People",
            "goal": "Goals",
            "general": "General",
        }
        parts: list[str] = []
        for cat, items in by_category.items():
            label = category_labels.get(cat, cat.title())
            parts.append(f"### {label}")
            parts.extend(items)

        return "\n## Memories About This User\n" + "\n".join(parts)

    async def get_memory_titles(self, user_id: int) -> list[str]:
        """Return list of existing memory titles for dedup checks."""
        cursor = await self._db.conn.execute(
            "SELECT title FROM memories WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [r["title"] for r in rows]

    async def clear(self, user_id: int) -> None:
        """Delete all memories for a user (DB + files)."""
        cursor = await self._db.conn.execute(
            "SELECT file_path FROM memories WHERE user_id = ?", (user_id,)
        )
        rows = await cursor.fetchall()
        for row in rows:
            self._delete_markdown(row["file_path"])

        await self._db.conn.execute(
            "DELETE FROM memories WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.execute(
            "DELETE FROM session_tracker WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.commit()

        # Remove user directory
        user_dir = self._memories_dir / str(user_id)
        if user_dir.exists():
            import shutil
            shutil.rmtree(user_dir, ignore_errors=True)

    async def migrate_from_facts(self, fact_store: FactStore) -> int:
        """One-time idempotent migration of facts into memories. Returns count migrated."""
        # Get all user_ids that have facts
        cursor = await self._db.conn.execute(
            "SELECT DISTINCT user_id FROM facts"
        )
        user_rows = await cursor.fetchall()
        count = 0

        for user_row in user_rows:
            uid = user_row["user_id"]
            facts = await fact_store.list_facts(uid)
            for key, value in facts.items():
                # Check if already migrated (by title match)
                existing = await self._db.conn.execute(
                    "SELECT id FROM memories WHERE user_id = ? AND title = ? AND source = 'migrated_fact'",
                    (uid, key),
                )
                if await existing.fetchone():
                    continue

                await self.save_memory(
                    user_id=uid,
                    title=key,
                    content=value,
                    category="fact",
                    importance=5,
                    source="migrated_fact",
                )
                count += 1

        if count:
            logger.info("Migrated %d facts into memories", count)
        return count

    # --- Session tracker helpers ---

    async def get_session_info(self, user_id: int) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            "SELECT user_id, last_message_at, message_count, session_summarized "
            "FROM session_tracker WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_session_tracker(self, user_id: int) -> None:
        """Update session tracker: bump message count and last_message_at."""
        await self._db.conn.execute(
            "INSERT INTO session_tracker (user_id, last_message_at, message_count, session_summarized) "
            "VALUES (?, CURRENT_TIMESTAMP, 1, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "last_message_at = CURRENT_TIMESTAMP, "
            "message_count = message_count + 1, "
            "session_summarized = 0",
            (user_id,),
        )
        await self._db.conn.commit()

    async def mark_session_summarized(self, user_id: int) -> None:
        """Mark the current session as summarized and reset message count."""
        await self._db.conn.execute(
            "UPDATE session_tracker SET session_summarized = 1, message_count = 0 "
            "WHERE user_id = ?",
            (user_id,),
        )
        await self._db.conn.commit()
