"""Tests for MemorySkill."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from senti.memory.database import Database
from senti.memory.memory_store import MemoryStore
from senti.skills.builtin.memory_skill import MemorySkill


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def memory_store(db: Database, tmp_path: Path):
    return MemoryStore(db, tmp_path / "memories")


@pytest.fixture
def skill():
    settings = MagicMock()
    return MemorySkill(settings)


USER_ID = 12345


class TestToolDefinitions:
    def test_has_all_tools(self, skill: MemorySkill):
        defs = skill.get_tool_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "save_memory" in names
        assert "search_memories" in names
        assert "list_memories" in names
        assert "update_memory" in names
        assert "delete_memory" in names

    def test_tool_count(self, skill: MemorySkill):
        assert len(skill.get_tool_definitions()) == 5

    def test_skill_name(self, skill: MemorySkill):
        assert skill.name == "memory"


class TestExecute:
    @pytest.mark.asyncio
    async def test_save_memory(self, skill: MemorySkill, memory_store: MemoryStore):
        result = await skill.execute(
            "save_memory",
            {"title": "color", "content": "Blue", "category": "preference"},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "Saved memory" in result
        assert "color" in result

    @pytest.mark.asyncio
    async def test_search_memories(self, skill: MemorySkill, memory_store: MemoryStore):
        await memory_store.save_memory(USER_ID, "hobby", "Playing guitar", category="preference")

        result = await skill.execute(
            "search_memories",
            {"query": "guitar"},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "guitar" in result.lower()

    @pytest.mark.asyncio
    async def test_search_not_found(self, skill: MemorySkill, memory_store: MemoryStore):
        result = await skill.execute(
            "search_memories",
            {"query": "nonexistent_thing_xyz"},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "No memories found" in result

    @pytest.mark.asyncio
    async def test_list_memories(self, skill: MemorySkill, memory_store: MemoryStore):
        await memory_store.save_memory(USER_ID, "fact1", "value1", category="fact")
        await memory_store.save_memory(USER_ID, "pref1", "value2", category="preference")

        result = await skill.execute(
            "list_memories",
            {},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "fact1" in result
        assert "pref1" in result

    @pytest.mark.asyncio
    async def test_list_empty(self, skill: MemorySkill, memory_store: MemoryStore):
        result = await skill.execute(
            "list_memories",
            {},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "No memories stored" in result

    @pytest.mark.asyncio
    async def test_update_memory(self, skill: MemorySkill, memory_store: MemoryStore):
        mem = await memory_store.save_memory(USER_ID, "color", "Blue", category="preference")

        result = await skill.execute(
            "update_memory",
            {"memory_id": mem["id"], "content": "Green"},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "Updated memory" in result

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, skill: MemorySkill, memory_store: MemoryStore):
        result = await skill.execute(
            "update_memory",
            {"memory_id": 9999},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_memory(self, skill: MemorySkill, memory_store: MemoryStore):
        mem = await memory_store.save_memory(USER_ID, "temp", "data", category="general")

        result = await skill.execute(
            "delete_memory",
            {"memory_id": mem["id"]},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "Deleted memory" in result

    @pytest.mark.asyncio
    async def test_no_memory_store(self, skill: MemorySkill):
        result = await skill.execute("save_memory", {"title": "x", "content": "y", "category": "fact"})
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_function(self, skill: MemorySkill, memory_store: MemoryStore):
        result = await skill.execute(
            "nonexistent_function",
            {},
            memory_store=memory_store,
            user_id=USER_ID,
        )
        assert "Unknown function" in result
