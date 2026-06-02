from __future__ import annotations

import asyncio

from opentalking.providers.memory.bm25 import rank_items_bm25
from opentalking.providers.memory.decision_agent import MemoryDecisionAgent
from opentalking.providers.memory.mem0_provider import Mem0MemoryProvider
from opentalking.providers.memory.runtime import MemoryRuntime, MemoryScope
from opentalking.providers.memory.schemas import MemoryItem
from opentalking.providers.memory.sqlite_provider import SQLiteMemoryProvider


def test_bm25_ranks_keyword_candidates_without_vector_search() -> None:
    items = [
        MemoryItem(id="1", text="User likes spicy Sichuan food."),
        MemoryItem(id="2", text="User prefers quiet morning meetings."),
    ]

    ranked = rank_items_bm25("What spicy food does the user like?", items, limit=1)

    assert [item.id for item in ranked] == ["1"]


def test_decision_agent_skips_assistant_and_empty_turns() -> None:
    agent = MemoryDecisionAgent()

    items = agent.decide_import(
        [
            {"role": "assistant", "content": "Sure."},
            {"role": "user", "content": "   "},
            {"role": "user", "content": "Remember that I prefer concise answers."},
        ],
        source="test",
    )

    assert len(items) == 1
    assert items[0].type == "preference"
    assert items[0].metadata["source"] == "test"


def test_decision_agent_realtime_write_requires_explicit_memory_signal() -> None:
    agent = MemoryDecisionAgent()

    generic = agent.decide_conversation_write(
        user_text="请帮我介绍一下这个项目的主要功能。",
        assistant_text="好的。",
        interrupted=False,
    )
    preference = agent.decide_conversation_write(
        user_text="记住，我喜欢回答简洁一点。",
        assistant_text="好的。",
        interrupted=False,
    )

    assert generic == []
    assert len(preference) == 1
    assert preference[0].type == "preference"


def test_decision_agent_recall_is_conditional() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("你好").should_recall is False
    assert agent.decide_recall("介绍一下这个项目？").should_recall is False
    assert agent.decide_recall("继续上次的话题").should_recall is True


def test_decision_agent_recalls_user_owned_memory_questions() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("我的测试目标是什么？").should_recall is True
    assert agent.decide_recall("我现在在做的项目是什么？").should_recall is True
    assert agent.decide_recall("我叫什么？").should_recall is True
    assert agent.decide_recall("我叫什么？").reason == "user_owned"


def test_decision_agent_rule_score_triggers_without_models() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("上次我们决定的部署方案是什么？").reason == "explicit_recall"
    assert agent.decide_recall("146服务器上执行部署前检查一下").should_recall is False
    assert agent.decide_recall("连接 8.92.9.146 看一下服务状态").reason == "fact_entity"
    assert agent.decide_recall("按我的习惯回答这个问题").reason == "user_owned"
    assert agent.decide_recall("介绍一下这个项目？").should_recall is False
    assert agent.decide_recall("删除 /data2/zcm/digital_human/opentalking/data/cache 前检查一下").should_recall is False


def test_bm25_tokenizes_fact_entities_for_memory_lookup() -> None:
    items = [
        MemoryItem(id="server-146", text="146服务器指的是8.92.9.146。"),
        MemoryItem(id="server-86", text="86服务器指的是8.92.7.86。"),
    ]

    ranked = rank_items_bm25("146服务器上部署", items, limit=1)

    assert [item.id for item in ranked] == ["server-146"]


def test_memory_runtime_fact_entity_trigger_retrieves_server_alias() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            self.list_calls += 1
            return [
                MemoryItem(id="1", text="146服务器指的是8.92.9.146。"),
                MemoryItem(id="2", text="86服务器指的是8.92.7.86。"),
            ]

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        provider = FakeProvider()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
        )

        prompt = await runtime.retrieve_prompt("146服务器上看一下服务")

        assert "146服务器指的是8.92.9.146" in prompt
        assert "86服务器" not in prompt
        assert provider.list_calls == 1

    asyncio.run(run())


def test_memory_runtime_recalls_user_name_question() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            self.list_calls += 1
            return [
                MemoryItem(id="question", text="你还记得我叫什么？"),
                MemoryItem(id="name", text="我叫小张"),
            ]

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        provider = FakeProvider()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
        )

        prompt = await runtime.retrieve_prompt("我叫什么？")

        assert "我叫小张" in prompt
        assert prompt.index("我叫小张") < prompt.index("你还记得我叫什么？")
        assert provider.list_calls == 1

    asyncio.run(run())


def test_mem0_provider_adds_with_infer_false_and_get_all_only_for_listing() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []
            self.search_calls = 0

        def add(self, payload: object, **kwargs: object) -> None:
            self.add_calls.append((payload, kwargs))

        def get_all(self, **kwargs: object) -> dict[str, object]:
            return {
                "results": [
                    {
                        "id": "mem0_1",
                        "memory": "User likes tea.",
                        "metadata": {
                            "opentalking_memory_id": "item_1",
                            "library_id": "default",
                            "profile_id": kwargs["user_id"],
                            "character_id": kwargs["agent_id"],
                            "type": "fact",
                        },
                    }
                ]
            }

        def search(self, *args: object, **kwargs: object) -> None:
            self.search_calls += 1

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)
        imported = await provider.add_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            items=[MemoryItem(id="item_1", text="User likes tea.")],
        )
        listed = await provider.list_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
        )

        assert imported == 1
        assert fake.add_calls[0][1]["infer"] is False
        assert fake.add_calls[0][1]["user_id"] == "default"
        assert fake.add_calls[0][1]["agent_id"] == "avatar-a"
        assert fake.search_calls == 0
        assert listed[0].id == "item_1"

    asyncio.run(run())


def test_sqlite_memory_provider_roundtrip(tmp_path) -> None:
    async def run() -> None:
        provider = SQLiteMemoryProvider(tmp_path / "memory.sqlite3")
        library = await provider.create_library(
            library_id="default",
            name="Default",
            profile_id="default",
            character_id="avatar-a",
        )
        imported = await provider.add_items(
            library_id=library.id,
            profile_id="default",
            character_id="avatar-a",
            items=[MemoryItem(id="item-a", text="记住，我喜欢简洁回答。", type="preference")],
        )
        libraries = await provider.list_libraries(
            profile_id="default",
            character_id="avatar-a",
        )
        items = await provider.list_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
        )
        deleted = await provider.delete_item(
            library_id="default",
            item_id="item-a",
            profile_id="default",
            character_id="avatar-a",
        )

        assert imported == 1
        assert libraries[0].memory_count == 1
        assert items[0].text == "记住，我喜欢简洁回答。"
        assert deleted is True

    asyncio.run(run())


def test_memory_runtime_does_not_retrieve_before_every_answer() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            self.list_calls += 1
            return [MemoryItem(id="1", text="用户喜欢简洁回答。")]

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        provider = FakeProvider()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
        )

        assert await runtime.retrieve_prompt("你好") == ""
        assert provider.list_calls == 0
        prompt = await runtime.retrieve_prompt("按我的习惯回答这个问题")
        assert "用户喜欢简洁回答" in prompt
        assert provider.list_calls == 1

    asyncio.run(run())


def test_memory_runtime_cross_session_roundtrip(tmp_path) -> None:
    async def run() -> None:
        provider = SQLiteMemoryProvider(tmp_path / "memory.sqlite3")
        first = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
        )
        first.schedule_write(
            user_text="记住，我喜欢简洁回答。",
            assistant_text="好的。",
            interrupted=False,
        )
        await first.drain()

        second = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
        )
        prompt = await second.retrieve_prompt("按我的习惯回答这个问题")

        assert "我喜欢简洁回答" in prompt

    asyncio.run(run())
