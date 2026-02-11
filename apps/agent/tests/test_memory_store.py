"""Tests for MemoryStore."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from senti.memory.database import Database
from senti.memory.fact_store import FactStore
from senti.memory.memory_store import MemoryStore


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def store(db: Database, tmp_path: Path):
    return MemoryStore(db, tmp_path / "memories")


@pytest_asyncio.fixture
async def fact_store(db: Database):
    return FactStore(db)


USER_ID = 12345


class TestCRUD:
    @pytest.mark.asyncio
    async def test_save_and_get(self, store: MemoryStore):
        mem = await store.save_memory(USER_ID, "favorite color", "Blue", category="preference")
        assert mem["id"] is not None
        assert mem["title"] == "favorite color"
        assert mem["content"] == "Blue"
        assert mem["category"] == "preference"

        fetched = await store.get_memory(mem["id"])
        assert fetched is not None
        assert fetched["title"] == "favorite color"

    @pytest.mark.asyncio
    async def test_update(self, store: MemoryStore):
        mem = await store.save_memory(USER_ID, "pet", "Dog named Max", category="fact")
        updated = await store.update_memory(mem["id"], content="Cat named Luna", importance=8)
        assert updated is not None
        assert updated["content"] == "Cat named Luna"
        assert updated["importance"] == 8

    @pytest.mark.asyncio
    async def test_delete(self, store: MemoryStore):
        mem = await store.save_memory(USER_ID, "temp", "temporary data", category="general")
        assert await store.delete_memory(mem["id"]) is True
        assert await store.get_memory(mem["id"]) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: MemoryStore):
        assert await store.delete_memory(9999) is False

    @pytest.mark.asyncio
    async def test_clear(self, store: MemoryStore):
        await store.save_memory(USER_ID, "a", "content a", category="fact")
        await store.save_memory(USER_ID, "b", "content b", category="fact")
        await store.clear(USER_ID)
        memories = await store.list_memories(USER_ID)
        assert len(memories) == 0

    @pytest.mark.asyncio
    async def test_invalid_category_defaults(self, store: MemoryStore):
        mem = await store.save_memory(USER_ID, "test", "data", category="invalid_cat")
        assert mem["category"] == "general"

    @pytest.mark.asyncio
    async def test_importance_clamped(self, store: MemoryStore):
        mem = await store.save_memory(USER_ID, "high", "data high", importance=99)
        assert mem["importance"] == 10
        mem2 = await store.save_memory(USER_ID, "low", "data low", importance=-5)
        assert mem2["importance"] == 1


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_by_keyword(self, store: MemoryStore):
        await store.save_memory(USER_ID, "favorite color", "Blue is my favorite", category="preference")
        await store.save_memory(USER_ID, "birthday", "January 15", category="fact")

        results = await store.search_memories(USER_ID, "blue")
        assert len(results) == 1
        assert results[0]["title"] == "favorite color"

    @pytest.mark.asyncio
    async def test_search_multiple_terms(self, store: MemoryStore):
        await store.save_memory(USER_ID, "work", "Software engineer at Acme Corp", category="fact")
        await store.save_memory(USER_ID, "hobby", "Likes software projects", category="preference")

        results = await store.search_memories(USER_ID, "software acme")
        assert len(results) == 1
        assert results[0]["title"] == "work"

    @pytest.mark.asyncio
    async def test_search_with_category_filter(self, store: MemoryStore):
        await store.save_memory(USER_ID, "color pref", "Blue", category="preference")
        await store.save_memory(USER_ID, "color fact", "Blue is calming", category="fact")

        results = await store.search_memories(USER_ID, "blue", category="preference")
        assert len(results) == 1
        assert results[0]["category"] == "preference"

    @pytest.mark.asyncio
    async def test_search_empty_query(self, store: MemoryStore):
        results = await store.search_memories(USER_ID, "")
        assert results == []


class TestContextInjection:
    @pytest.mark.asyncio
    async def test_get_context_memories(self, store: MemoryStore):
        await store.save_memory(USER_ID, "high prio", "Important info", importance=9, category="fact")
        await store.save_memory(USER_ID, "low prio", "Less important", importance=2, category="general")

        context = await store.get_context_memories(USER_ID, token_budget=1500)
        assert "high prio" in context
        assert "Important info" in context

    @pytest.mark.asyncio
    async def test_context_respects_token_budget(self, store: MemoryStore):
        # Save many memories
        for i in range(50):
            await store.save_memory(USER_ID, f"memory {i}", f"Content for memory number {i}" * 10, category="general")

        context = await store.get_context_memories(USER_ID, token_budget=100)
        # Should be truncated — not all 50 memories
        assert len(context) < 2000

    @pytest.mark.asyncio
    async def test_empty_context(self, store: MemoryStore):
        context = await store.get_context_memories(USER_ID)
        assert context == ""

    @pytest.mark.asyncio
    async def test_context_excludes_session_summaries(self, store: MemoryStore):
        await store.save_memory(USER_ID, "Session summary 2026-01-01", "Summary", category="session_summary")
        await store.save_memory(USER_ID, "real fact", "Real info", category="fact")

        context = await store.get_context_memories(USER_ID)
        assert "Session summary" not in context
        assert "real fact" in context


class TestMarkdownIO:
    @pytest.mark.asyncio
    async def test_markdown_file_created(self, store: MemoryStore, tmp_path: Path):
        mem = await store.save_memory(USER_ID, "test file", "hello world", category="fact")
        file_path = Path(mem["file_path"])
        assert file_path.exists()
        content = file_path.read_text()
        assert "---" in content
        assert "hello world" in content
        assert "test file" in content

    @pytest.mark.asyncio
    async def test_markdown_file_deleted(self, store: MemoryStore, tmp_path: Path):
        mem = await store.save_memory(USER_ID, "to delete", "data", category="fact")
        file_path = Path(mem["file_path"])
        assert file_path.exists()
        await store.delete_memory(mem["id"])
        assert not file_path.exists()


class TestDedup:
    @pytest.mark.asyncio
    async def test_exact_content_dedup(self, store: MemoryStore):
        mem1 = await store.save_memory(USER_ID, "color", "Blue", category="preference")
        mem2 = await store.save_memory(USER_ID, "color again", "Blue", category="preference")
        # Same content hash → should return existing memory
        assert mem1["id"] == mem2["id"]

    @pytest.mark.asyncio
    async def test_fuzzy_title_dedup(self, store: MemoryStore):
        mem1 = await store.save_memory(USER_ID, "favorite color", "Blue", category="preference")
        mem2 = await store.save_memory(USER_ID, "favourite color", "Green", category="preference")
        # Similar titles → should update the existing one
        assert mem1["id"] == mem2["id"]
        fetched = await store.get_memory(mem1["id"])
        assert fetched["content"] == "Green"


class TestMigration:
    @pytest.mark.asyncio
    async def test_migrate_from_facts(self, store: MemoryStore, fact_store: FactStore):
        await fact_store.save_fact(USER_ID, "birthday", "January 15")
        await fact_store.save_fact(USER_ID, "pet", "Dog")

        count = await store.migrate_from_facts(fact_store)
        assert count == 2

        memories = await store.list_memories(USER_ID)
        titles = [m["title"] for m in memories]
        assert "birthday" in titles
        assert "pet" in titles

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, store: MemoryStore, fact_store: FactStore):
        await fact_store.save_fact(USER_ID, "name", "Alice")
        count1 = await store.migrate_from_facts(fact_store)
        assert count1 == 1
        count2 = await store.migrate_from_facts(fact_store)
        assert count2 == 0  # Already migrated


class TestSessionTracker:
    @pytest.mark.asyncio
    async def test_update_and_get_session(self, store: MemoryStore):
        await store.update_session_tracker(USER_ID)
        session = await store.get_session_info(USER_ID)
        assert session is not None
        assert session["message_count"] == 1
        assert session["session_summarized"] == 0

    @pytest.mark.asyncio
    async def test_session_message_count_increments(self, store: MemoryStore):
        await store.update_session_tracker(USER_ID)
        await store.update_session_tracker(USER_ID)
        await store.update_session_tracker(USER_ID)
        session = await store.get_session_info(USER_ID)
        assert session["message_count"] == 3

    @pytest.mark.asyncio
    async def test_mark_session_summarized(self, store: MemoryStore):
        await store.update_session_tracker(USER_ID)
        await store.update_session_tracker(USER_ID)
        await store.mark_session_summarized(USER_ID)
        session = await store.get_session_info(USER_ID)
        assert session["session_summarized"] == 1
        assert session["message_count"] == 0

    @pytest.mark.asyncio
    async def test_session_not_found(self, store: MemoryStore):
        session = await store.get_session_info(99999)
        assert session is None
