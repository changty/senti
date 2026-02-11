"""Tests for UserSkillStore, SkillsmithSkill, and dynamic registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from senti.memory.database import Database
from senti.skills.user_skill_store import UserSkillStore


USER_ID = 12345


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def store(db: Database):
    return UserSkillStore(db)


# --- UserSkillStore CRUD ---


class TestUserSkillStore:
    @pytest.mark.asyncio
    async def test_create_and_get(self, store: UserSkillStore):
        skill = await store.create(
            user_id=USER_ID,
            name="celsius_to_f",
            description="Convert Celsius to Fahrenheit",
            parameters_json='{"type": "object", "properties": {"temp": {"type": "number"}}}',
            code='def run(args):\n    return str(args["temp"] * 9/5 + 32)',
        )
        assert skill["name"] == "celsius_to_f"
        assert skill["enabled"] == 1
        assert skill["trusted"] == 0

        fetched = await store.get_by_name(USER_ID, "celsius_to_f")
        assert fetched is not None
        assert fetched["description"] == "Convert Celsius to Fahrenheit"

    @pytest.mark.asyncio
    async def test_duplicate_name_raises(self, store: UserSkillStore):
        await store.create(USER_ID, "my_tool", "desc", "{}", "def run(a): pass")
        with pytest.raises(ValueError, match="already exists"):
            await store.create(USER_ID, "my_tool", "desc2", "{}", "def run(a): pass")

    @pytest.mark.asyncio
    async def test_list_for_user(self, store: UserSkillStore):
        await store.create(USER_ID, "tool_a", "A", "{}", "def run(a): pass")
        await store.create(USER_ID, "tool_b", "B", "{}", "def run(a): pass")
        skills = await store.list_for_user(USER_ID)
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert names == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_delete_soft(self, store: UserSkillStore):
        await store.create(USER_ID, "temp_tool", "T", "{}", "def run(a): pass")
        deleted = await store.delete("temp_tool", USER_ID)
        assert deleted is True
        fetched = await store.get_by_name(USER_ID, "temp_tool")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: UserSkillStore):
        deleted = await store.delete("nope", USER_ID)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_set_trusted(self, store: UserSkillStore):
        await store.create(USER_ID, "trust_me", "T", "{}", "def run(a): pass")
        result = await store.set_trusted("trust_me", USER_ID, True)
        assert result is True
        skill = await store.get_by_name(USER_ID, "trust_me")
        assert skill["trusted"] == 1

    @pytest.mark.asyncio
    async def test_count(self, store: UserSkillStore):
        assert await store.count(USER_ID) == 0
        await store.create(USER_ID, "c_one", "1", "{}", "def run(a): pass")
        await store.create(USER_ID, "c_two", "2", "{}", "def run(a): pass")
        assert await store.count(USER_ID) == 2

    @pytest.mark.asyncio
    async def test_list_all_enabled(self, store: UserSkillStore):
        await store.create(USER_ID, "alive", "A", "{}", "def run(a): pass")
        await store.create(USER_ID, "dead", "D", "{}", "def run(a): pass")
        await store.delete("dead", USER_ID)
        all_enabled = await store.list_all_enabled()
        assert len(all_enabled) == 1
        assert all_enabled[0]["name"] == "alive"


# --- SkillsmithSkill ---


class TestSkillsmithSkill:
    @pytest.mark.asyncio
    async def test_create_skill(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)
        registry = MagicMock()
        registry.register_user_skill = MagicMock()

        result = await skill.execute(
            "create_skill",
            {
                "name": "hello_world",
                "description": "Says hello",
                "code": 'def run(args):\n    return "Hello!"',
            },
            user_id=USER_ID,
            user_skill_store=store,
            registry=registry,
        )
        assert "created" in result
        registry.register_user_skill.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_skill_bad_name(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)

        result = await skill.execute(
            "create_skill",
            {"name": "A", "description": "bad", "code": "def run(a): pass"},
            user_id=USER_ID,
            user_skill_store=store,
            registry=MagicMock(),
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_create_skill_reserved_name(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)

        result = await skill.execute(
            "create_skill",
            {"name": "run_python", "description": "bad", "code": "def run(a): pass"},
            user_id=USER_ID,
            user_skill_store=store,
            registry=MagicMock(),
        )
        assert "reserved" in result

    @pytest.mark.asyncio
    async def test_create_skill_no_run(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)

        result = await skill.execute(
            "create_skill",
            {"name": "no_run", "description": "bad", "code": "x = 1"},
            user_id=USER_ID,
            user_skill_store=store,
            registry=MagicMock(),
        )
        assert "def run(" in result

    @pytest.mark.asyncio
    async def test_list_user_skills(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)

        await store.create(USER_ID, "tool_x", "X tool", "{}", "def run(a): pass")

        result = await skill.execute(
            "list_user_skills", {}, user_id=USER_ID, user_skill_store=store,
        )
        assert "tool_x" in result

    @pytest.mark.asyncio
    async def test_delete_skill(self, store: UserSkillStore):
        from senti.skills.builtin.skillsmith_skill import SkillsmithSkill

        settings = MagicMock()
        skill = SkillsmithSkill(settings)
        registry = MagicMock()

        await store.create(USER_ID, "bye_tool", "Bye", "{}", "def run(a): pass")

        result = await skill.execute(
            "delete_skill",
            {"name": "bye_tool"},
            user_id=USER_ID,
            user_skill_store=store,
            registry=registry,
        )
        assert "deleted" in result
        registry.unregister_user_skill.assert_called_once_with("bye_tool")


# --- Registry dynamic registration ---


class TestRegistryDynamic:
    def test_register_and_unregister(self):
        from senti.skills.registry import SkillRegistry

        settings = MagicMock()
        settings.skills_config_path = Path("/nonexistent")
        registry = SkillRegistry(settings)

        skill_data = {
            "name": "my_custom",
            "description": "Custom tool",
            "parameters_json": '{"type": "object", "properties": {}}',
            "code": "def run(args): return 'ok'",
            "trusted": 0,
        }
        registry.register_user_skill(skill_data)

        # Skill is registered
        assert registry.get_skill("my_custom") is not None
        defn = registry.get_definition("my_custom")
        assert defn is not None
        assert defn.user_created is True
        assert defn.trusted is False

        # Tool definitions include it
        tool_defs = registry.tool_definitions()
        names = {td["function"]["name"] for td in tool_defs}
        assert "my_custom" in names

        # Unregister
        registry.unregister_user_skill("my_custom")
        assert registry.get_skill("my_custom") is None

    def test_set_trusted(self):
        from senti.skills.registry import SkillRegistry

        settings = MagicMock()
        settings.skills_config_path = Path("/nonexistent")
        registry = SkillRegistry(settings)

        skill_data = {
            "name": "trustable",
            "description": "Trustable tool",
            "parameters_json": "{}",
            "code": "def run(args): return 'ok'",
            "trusted": 0,
        }
        registry.register_user_skill(skill_data)
        registry.set_user_skill_trusted("trustable", True)

        defn = registry.get_definition("trustable")
        assert defn.trusted is True

    def test_load_user_skills_bulk(self):
        from senti.skills.registry import SkillRegistry

        settings = MagicMock()
        settings.skills_config_path = Path("/nonexistent")
        registry = SkillRegistry(settings)

        skills = [
            {"name": "bulk_a", "description": "A", "parameters_json": "{}", "code": "def run(a): pass", "trusted": 0},
            {"name": "bulk_b", "description": "B", "parameters_json": "{}", "code": "def run(a): pass", "trusted": 1},
        ]
        registry.load_user_skills(skills)

        assert registry.get_skill("bulk_a") is not None
        assert registry.get_skill("bulk_b") is not None
        assert registry.get_definition("bulk_b").trusted is True


# --- UserSkillProxy tool definitions ---


class TestUserSkillProxy:
    def test_tool_definitions(self):
        from senti.skills.registry import UserSkillProxy

        proxy = UserSkillProxy({
            "name": "proxy_tool",
            "description": "A proxy",
            "parameters_json": json.dumps({
                "type": "object",
                "properties": {"x": {"type": "number"}},
                "required": ["x"],
            }),
            "code": "def run(args): return str(args['x'])",
        })

        assert proxy.name == "proxy_tool"
        defs = proxy.get_tool_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "proxy_tool"
        assert "x" in defs[0]["function"]["parameters"]["properties"]
