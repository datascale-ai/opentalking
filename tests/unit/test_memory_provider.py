from __future__ import annotations

import asyncio
import json
import logging

from opentalking.core.config import Settings
from opentalking.providers.memory.bm25 import memories_to_prompt, rank_items_bm25
from opentalking.providers.memory.decision_agent import MemoryDecisionAgent, MemoryLLMRecallJudge, RecallDecision
from opentalking.providers.memory.factory import _mem0_config
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


def test_memories_to_prompt_groups_digital_human_categories() -> None:
    prompt = memories_to_prompt(
        [
            MemoryItem(
                id="pref",
                text="用户喜欢温柔、少说教的陪伴方式。",
                metadata={"category": "user_preference"},
            ),
            MemoryItem(
                id="entity",
                text="小雨是用户的前女友。",
                metadata={"category": "entity_relation"},
            ),
            MemoryItem(
                id="goal",
                text="用户正在准备雅思口语。",
                metadata={"category": "goal_progress"},
            ),
            MemoryItem(
                id="feedback",
                text="用户反馈数字人刚才太像老师。",
                metadata={"category": "feedback_correction"},
            ),
        ]
    )

    assert "Relevant user memories:" in prompt
    assert "Preferences:" in prompt
    assert "Important people/entities:" in prompt
    assert "Goals and progress:" in prompt
    assert "Interaction feedback:" in prompt
    assert prompt.index("Preferences:") < prompt.index("Important people/entities:")


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


def test_decision_agent_realtime_write_keeps_generic_prompts_out() -> None:
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

    assert len(generic) == 1
    assert generic[0].metadata["category"] == "mem0_candidate"
    assert len(preference) == 1
    assert preference[0].metadata["category"] == "mem0_candidate"
    assert preference[0].metadata["confidence"] == "unknown"


def test_decision_agent_routes_digital_human_write_scenarios_to_mem0() -> None:
    agent = MemoryDecisionAgent()

    for user_text in [
        "我喜欢你说话温柔一点。",
        "那以后每天晚上10点提醒我背单词。",
        "我今天背完50个单词了。",
        "我女朋友叫小雨。",
        "不是女朋友，是前女友。",
    ]:
        decision = agent.decide_conversation_write_decision(
            user_text=user_text,
            assistant_text="好的，我记住了。",
            interrupted=False,
        )

        assert decision.action == "mem0_infer"
        assert decision.category == "mem0_candidate"
        assert decision.confidence == "unknown"
        assert len(decision.items) == 1
        assert decision.items[0].metadata["category"] == "mem0_candidate"
        assert decision.items[0].metadata["source_type"] == "realtime_turn"


def test_decision_agent_writes_exam_preparation_goal() -> None:
    agent = MemoryDecisionAgent()

    decision = agent.decide_conversation_write_decision(
        user_text="我在准备雅思考试，想每天练口语。",
        assistant_text="好，我陪你练。",
        interrupted=False,
    )

    assert decision.action == "mem0_infer"
    assert decision.category == "mem0_candidate"
    assert decision.confidence == "unknown"
    assert decision.reason == "needs_smart_judgement"


def test_decision_agent_rejects_recall_style_questions_as_writes() -> None:
    agent = MemoryDecisionAgent()

    decision = agent.decide_conversation_write_decision(
        user_text="按我喜欢的回答方式，解释一下今天怎么练雅思口语？",
        assistant_text="今天建议你用3分钟热身+10分钟自由对话+7分钟复盘模式练习。",
        interrupted=False,
    )

    assert decision.action == "reject"
    assert decision.reason == "recall_question"


def test_memory_runtime_does_not_summary_buffer_recall_questions() -> None:
    class FakeProvider:
        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            raise AssertionError("recall questions should not be written or summarized")

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    runtime = MemoryRuntime(
        scope=MemoryScope(
            enabled=True,
            profile_id="default",
            character_id="avatar-a",
            library_id="default",
        ),
        provider=FakeProvider(),
        settings=Settings(memory_summary_enabled=True),
    )

    runtime.schedule_write(
        user_text="按我喜欢的回答方式，解释一下今天怎么练雅思口语？",
        assistant_text="今天建议你用3分钟热身+10分钟自由对话+7分钟复盘模式练习。",
        interrupted=False,
    )

    assert runtime._summary_turn_buffer == []  # noqa: SLF001


def test_decision_agent_rejects_memory_check_questions_even_with_memory_markers() -> None:
    agent = MemoryDecisionAgent()

    for user_text in [
        "你记得我叫什么吗？",
        "你还记得我喜欢什么聊天风格吗？",
        "把我刚才这几轮的重点记住了吗？",
    ]:
        decision = agent.decide_conversation_write_decision(
            user_text=user_text,
            assistant_text="我来确认一下。",
            interrupted=False,
        )

        assert decision.action == "reject"
        assert decision.reason == "memory_check_question"


def test_decision_agent_routes_low_value_and_risky_inputs() -> None:
    agent = MemoryDecisionAgent()

    summary_only = agent.decide_conversation_write_decision(
        user_text="我今天有点累，想随便聊聊。",
        assistant_text="我陪你慢慢聊。",
        interrupted=False,
    )
    greeting = agent.decide_conversation_write_decision(
        user_text="你好",
        assistant_text="你好呀。",
        interrupted=False,
    )
    secret = agent.decide_conversation_write_decision(
        user_text="我的 API key 是 sk-test-123。",
        assistant_text="收到。",
        interrupted=False,
    )

    assert summary_only.action == "mem0_infer"
    assert summary_only.category == "mem0_candidate"
    assert greeting.action == "reject"
    assert greeting.reason == "low_value"
    assert secret.action == "reject"
    assert secret.reason == "sensitive"


def test_decision_agent_recall_is_conditional() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("你好").should_recall is False
    assert agent.decide_recall("介绍一下这个项目？").should_recall is False
    assert agent.decide_recall("继续上次的话题").should_recall is True


def test_decision_agent_recall_understands_digital_human_contexts() -> None:
    agent = MemoryDecisionAgent()

    comfort = agent.decide_recall("我今天压力很大，你陪我聊聊。")
    learning = agent.decide_recall("今晚提醒我继续背单词。")
    shopping = agent.decide_recall("帮我看看适合我的衣服。")

    assert comfort.should_recall is True
    assert comfort.reason == "comfort_context"
    assert "user_preference" in comfort.categories
    assert "feedback_correction" in comfort.categories
    assert learning.should_recall is True
    assert learning.reason == "goal_context"
    assert "goal_progress" in learning.categories
    assert shopping.should_recall is True
    assert shopping.reason == "preference_context"
    assert "user_preference" in shopping.categories


def test_decision_agent_recalls_user_owned_memory_questions() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("我的测试目标是什么？").should_recall is True
    assert agent.decide_recall("我现在在做的项目是什么？").should_recall is True
    assert agent.decide_recall("我叫什么？").should_recall is True
    assert agent.decide_recall("我叫什么？").reason == "user_owned"


def test_decision_agent_recalls_named_entity_questions() -> None:
    agent = MemoryDecisionAgent()

    decision = agent.decide_recall("小雨是谁？")

    assert decision.should_recall is True
    assert decision.reason == "named_entity_question"
    assert "entity_relation" in decision.categories


def test_decision_agent_rule_score_triggers_without_models() -> None:
    agent = MemoryDecisionAgent()

    assert agent.decide_recall("上次我们决定的部署方案是什么？").reason == "explicit_recall"
    assert agent.decide_recall("146服务器上执行部署前检查一下").should_recall is False
    assert agent.decide_recall("连接 203.0.113.146 看一下服务状态").reason == "fact_entity"
    assert agent.decide_recall("按我的习惯回答这个问题").reason == "user_owned"
    assert agent.decide_recall("介绍一下这个项目？").should_recall is False
    assert agent.decide_recall("删除 /srv/opentalking/data/cache 前检查一下").should_recall is False


def test_bm25_tokenizes_fact_entities_for_memory_lookup() -> None:
    items = [
        MemoryItem(id="server-146", text="146服务器指的是203.0.113.146。"),
        MemoryItem(id="server-86", text="86服务器指的是203.0.113.86。"),
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
                MemoryItem(id="1", text="146服务器指的是203.0.113.146。"),
                MemoryItem(id="2", text="86服务器指的是203.0.113.86。"),
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

        assert "146服务器指的是203.0.113.146" in prompt
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


def test_mem0_config_keeps_local_qdrant_path_persistent() -> None:
    config = _mem0_config(
        Settings(
            memory_mem0_config=json.dumps(
                {
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {
                            "collection_name": "opentalking_memories",
                            "path": "./data/mem0_qdrant",
                            "embedding_model_dims": 1024,
                        },
                    }
                }
            )
        )
    )

    assert config["vector_store"]["config"]["on_disk"] is True


def test_mem0_config_can_be_built_from_split_env_settings() -> None:
    config = _mem0_config(
        Settings(
            memory_mem0_config="",
            memory_mem0_llm_provider="openai",
            memory_mem0_llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            memory_mem0_llm_api_key="llm-key",
            memory_mem0_llm_model="qwen-flash",
            memory_mem0_embedder_provider="openai",
            memory_mem0_embedder_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            memory_mem0_embedder_api_key="embedding-key",
            memory_mem0_embedder_model="text-embedding-v4",
        )
    )

    assert config["llm"] == {
        "provider": "openai",
        "config": {
            "model": "qwen-flash",
            "api_key": "llm-key",
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    }
    assert config["embedder"] == {
        "provider": "openai",
        "config": {
            "model": "text-embedding-v4",
            "api_key": "embedding-key",
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "embedding_dims": 1024,
        },
    }
    assert config["vector_store"] == {
        "provider": "qdrant",
        "config": {
            "collection_name": "opentalking_memories",
            "path": "./data/mem0_qdrant",
            "embedding_model_dims": 1024,
            "on_disk": True,
        },
    }


def test_mem0_json_config_overrides_split_env_settings() -> None:
    config = _mem0_config(
        Settings(
            memory_mem0_config=json.dumps({"llm": {"provider": "custom", "config": {"model": "custom-model"}}}),
            memory_mem0_llm_provider="openai",
            memory_mem0_llm_model="qwen-flash",
        )
    )

    assert config == {"llm": {"provider": "custom", "config": {"model": "custom-model"}}}


def test_mem0_provider_wraps_text_payload_for_mem0_clients_that_accept_strings() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []

        def add(self, messages: object, **kwargs: object) -> None:
            self.add_calls.append((messages, kwargs))

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            items=[MemoryItem(id="item_1", text="User likes tea.")],
        )

        assert imported == 1
        assert fake.add_calls[0][0] == [{"role": "user", "content": "User likes tea."}]

    asyncio.run(run())


def test_mem0_provider_raw_items_use_direct_memory_create_when_available() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.created: list[tuple[str, dict[str, object], dict[str, object]]] = []
            self.add_calls = 0

        def _create_memory(
            self,
            data: str,
            existing_embeddings: dict[str, object],
            metadata: dict[str, object] | None = None,
        ) -> str:
            self.created.append((data, existing_embeddings, dict(metadata or {})))
            return "mem0_raw_1"

        def add(self, _messages: object, **_kwargs: object) -> dict[str, object]:
            self.add_calls += 1
            return {"results": []}

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            items=[MemoryItem(id="item_1", text="User likes tea.")],
        )

        assert imported == 1
        assert fake.add_calls == 0
        assert fake.created == [
            (
                "User likes tea.",
                {},
                {
                    "user_id": "default",
                    "agent_id": "avatar-a",
                    "library_id": "default",
                    "profile_id": "default",
                    "character_id": "avatar-a",
                    "type": "note",
                    "opentalking_memory_id": "item_1",
                    "created_at": fake.created[0][2]["created_at"],
                },
            )
        ]

    asyncio.run(run())


def test_mem0_provider_searches_with_scope_and_filters_library() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.search_calls: list[tuple[str, dict[str, object]]] = []

        def search(self, query: str, **kwargs: object) -> dict[str, object]:
            self.search_calls.append((query, kwargs))
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
                            "type": "preference",
                        },
                    },
                    {
                        "id": "mem0_2",
                        "memory": "User likes coffee.",
                        "metadata": {
                            "opentalking_memory_id": "item_2",
                            "library_id": "other",
                            "profile_id": kwargs["user_id"],
                            "character_id": kwargs["agent_id"],
                            "type": "preference",
                        },
                    },
                ]
            }

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        results = await provider.search_items(
            query="tea",
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            limit=3,
        )

        assert [item.id for item in results] == ["item_1"]
        assert fake.search_calls == [
            (
                "tea",
                {
                    "user_id": "default",
                    "agent_id": "avatar-a",
                    "limit": 3,
                },
            )
        ]

    asyncio.run(run())


def test_mem0_provider_smart_write_defaults_to_user_only_messages() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []

        def add(self, payload: object, **kwargs: object) -> None:
            self.add_calls.append((payload, kwargs))

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_conversation_turns(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            turns=[
                {"role": "user", "content": "Remember that I like tea."},
                {"role": "assistant", "content": "Got it."},
            ],
        )

        payload, kwargs = fake.add_calls[0]
        assert imported == 1
        assert payload == [{"role": "user", "content": "Remember that I like tea."}]
        assert kwargs["infer"] is True
        assert kwargs["metadata"]["library_id"] == "default"
        assert kwargs["metadata"]["source"] == "session"

    asyncio.run(run())


def test_mem0_provider_smart_write_can_include_assistant_context_when_confirmed() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []

        def add(self, payload: object, **kwargs: object) -> None:
            self.add_calls.append((payload, kwargs))

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_conversation_turns(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            turns=[
                {"role": "assistant", "content": "今天建议用3分钟热身+10分钟自由对话+7分钟复盘。"},
                {"role": "user", "content": "好，以后就按这个方式练。"},
            ],
            include_assistant_context=True,
        )

        payload, kwargs = fake.add_calls[0]
        assert imported == 1
        assert payload == [
            {"role": "assistant", "content": "今天建议用3分钟热身+10分钟自由对话+7分钟复盘。"},
            {"role": "user", "content": "好，以后就按这个方式练。"},
        ]
        assert kwargs["infer"] is True

    asyncio.run(run())


def test_mem0_provider_smart_write_counts_noop_result_as_zero() -> None:
    class FakeMem0:
        def add(self, _payload: object, **_kwargs: object) -> dict[str, object]:
            return {
                "results": [
                    {
                        "id": "0",
                        "memory": "我在准备雅思考试，想每天练口语。",
                        "event": "NONE",
                    }
                ]
            }

    async def run() -> None:
        provider = Mem0MemoryProvider(client=FakeMem0())

        imported = await provider.add_conversation_turns(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            turns=[
                {"role": "user", "content": "我在准备雅思考试，想每天练口语。"},
                {"role": "assistant", "content": "好，我陪你练。"},
            ],
        )

        assert imported == 0

    asyncio.run(run())


def test_mem0_provider_suppresses_mem0_root_logs_with_memory_text(caplog) -> None:
    class FakeMem0:
        def add(self, _payload: object, **_kwargs: object) -> dict[str, object]:
            logging.info("Creating memory with data='我在准备雅思考试，想每天练口语。'")
            logging.info("{'id': '0', 'text': '我在准备雅思考试，想每天练口语。', 'event': 'NONE'}")
            logging.info("NOOP for Memory.")
            return {"results": [{"id": "0", "text": "我在准备雅思考试，想每天练口语。", "event": "NONE"}]}

    async def run() -> None:
        caplog.set_level(logging.INFO)
        provider = Mem0MemoryProvider(client=FakeMem0())

        imported = await provider.add_conversation_turns(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            turns=[
                {"role": "user", "content": "我在准备雅思考试，想每天练口语。"},
                {"role": "assistant", "content": "好，我陪你练。"},
            ],
        )

        assert imported == 0
        messages = [record.getMessage() for record in caplog.records]
        assert all("雅思" not in message for message in messages)
        assert all("NOOP for Memory" not in message for message in messages)

    asyncio.run(run())


def test_mem0_provider_omits_infer_for_older_mem0_clients() -> None:
    class FakeOlderMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []

        def add(
            self,
            messages: object,
            *,
            user_id: str,
            agent_id: str,
            metadata: dict[str, object],
        ) -> None:
            self.add_calls.append(
                (
                    messages,
                    {
                        "user_id": user_id,
                        "agent_id": agent_id,
                        "metadata": metadata,
                    },
                )
            )

    async def run() -> None:
        fake = FakeOlderMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_items(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            items=[MemoryItem(id="item_1", text="User likes tea.")],
        )

        assert imported == 1
        assert fake.add_calls[0][0] == [{"role": "user", "content": "User likes tea."}]
        assert "infer" not in fake.add_calls[0][1]

    asyncio.run(run())


def test_mem0_provider_summary_write_uses_infer_false_metadata() -> None:
    class FakeMem0:
        def __init__(self) -> None:
            self.add_calls: list[tuple[object, dict[str, object]]] = []

        def add(self, payload: object, **kwargs: object) -> None:
            self.add_calls.append((payload, kwargs))

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        imported = await provider.add_summary(
            library_id="default",
            profile_id="default",
            character_id="avatar-a",
            summary="The user prefers concise Chinese answers.",
            metadata={"turn_count": 8},
        )

        payload, kwargs = fake.add_calls[0]
        assert imported == 1
        assert payload == [{"role": "user", "content": "The user prefers concise Chinese answers."}]
        assert kwargs["infer"] is False
        assert kwargs["metadata"]["source_type"] == "session_summary"
        assert kwargs["metadata"]["layer"] == "episodic"
        assert kwargs["metadata"]["turn_count"] == 8

    asyncio.run(run())


def test_mem0_provider_close_closes_nested_vector_store_client() -> None:
    class FakeVectorClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeVectorStore:
        def __init__(self) -> None:
            self.client = FakeVectorClient()

    class FakeMem0:
        def __init__(self) -> None:
            self.vector_store = FakeVectorStore()

    async def run() -> None:
        fake = FakeMem0()
        provider = Mem0MemoryProvider(client=fake)

        await provider.close()

        assert fake.vector_store.client.closed is True

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


def test_memory_runtime_hybrid_recall_uses_provider_search_first() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.search_calls = 0
            self.list_calls = 0

        async def search_items(self, **kwargs):
            self.search_calls += 1
            assert kwargs["query"] == "按我的习惯回答这个问题"
            return [MemoryItem(id="smart", text="用户喜欢简洁回答。")]

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            self.list_calls += 1
            return [MemoryItem(id="raw", text="用户喜欢冗长回答。")]

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
            settings=Settings(
                memory_recall_backend="hybrid",
                memory_recall_limit=3,
                memory_recall_timeout_ms=1000,
            ),
        )

        prompt = await runtime.retrieve_prompt("按我的习惯回答这个问题")

        assert "用户喜欢简洁回答" in prompt
        assert "用户喜欢冗长回答" not in prompt
        assert provider.search_calls == 1
        assert provider.list_calls == 0

    asyncio.run(run())


def test_memory_runtime_hybrid_recall_falls_back_to_bm25_on_search_error() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.search_calls = 0
            self.list_calls = 0

        async def search_items(self, **_kwargs):
            self.search_calls += 1
            raise RuntimeError("search unavailable")

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            self.list_calls += 1
            return [
                MemoryItem(id="1", text="用户喜欢简洁回答。"),
                MemoryItem(id="2", text="用户喜欢热闹的音乐。"),
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
            settings=Settings(
                memory_recall_backend="hybrid",
                memory_recall_limit=1,
                memory_recall_timeout_ms=1000,
            ),
        )

        prompt = await runtime.retrieve_prompt("按我的习惯回答这个问题")

        assert "用户喜欢简洁回答" in prompt
        assert "用户喜欢热闹的音乐" not in prompt
        assert provider.search_calls == 1
        assert provider.list_calls == 1

    asyncio.run(run())


def test_memory_runtime_hybrid_decision_uses_llm_judge_for_ambiguous_query() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.search_queries: list[str] = []

        async def search_items(self, **kwargs):
            self.search_queries.append(kwargs["query"])
            return [MemoryItem(id="usual-style", text="The user prefers concise answers.")]

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            raise AssertionError("hybrid decision should search Mem0 directly")

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    class FakeJudge:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def decide_recall(self, user_text: str) -> RecallDecision:
            self.queries.append(user_text)
            return RecallDecision(
                True,
                query="usual answer style preference",
                reason="llm_memory_reference",
            )

    async def run() -> None:
        provider = FakeProvider()
        judge = FakeJudge()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
            settings=Settings(
                memory_decision_mode="hybrid",
                memory_decision_timeout_ms=1000,
                memory_recall_backend="mem0",
                memory_recall_limit=3,
                memory_recall_timeout_ms=1000,
            ),
            decision_judge=judge,
        )

        prompt = await runtime.retrieve_prompt("Can you answer in the usual style?")

        assert "concise answers" in prompt
        assert judge.queries == ["Can you answer in the usual style?"]
        assert provider.search_queries == ["usual answer style preference"]

    asyncio.run(run())


def test_memory_llm_recall_judge_prompt_covers_deictic_style_references(monkeypatch) -> None:
    captured: list[list[dict[str, str]]] = []

    class FakeLLMClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def chat_stream(self, messages: list[dict[str, str]]):
            captured.append(messages)
            yield '{"should_recall": true, "query": "user answer style preference", "reason": "deictic_style"}'

    monkeypatch.setattr(
        "opentalking.providers.llm.openai_compatible.adapter.OpenAICompatibleLLMClient",
        FakeLLMClient,
    )

    async def run() -> None:
        judge = MemoryLLMRecallJudge(
            Settings(
                llm_base_url="http://llm.test",
                llm_api_key="test",
                llm_model="test-model",
            )
        )

        decision = await judge.decide_recall("就用那套风格回答：这次发布要注意什么？")

        assert decision == RecallDecision(
            True,
            query="user answer style preference",
            reason="deictic_style",
        )
        system_prompt = captured[0][0]["content"]
        assert "那套风格" in system_prompt
        assert "usual style" in system_prompt

    asyncio.run(run())


def test_memory_runtime_hybrid_decision_does_not_override_high_risk_reject() -> None:
    class FakeProvider:
        async def search_items(self, **_kwargs):
            raise AssertionError("high-risk rule reject must not search")

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            raise AssertionError("high-risk rule reject must not list")

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    class FailingJudge:
        async def decide_recall(self, _user_text: str) -> RecallDecision:
            raise AssertionError("high-risk rule reject must not call LLM judge")

    async def run() -> None:
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=FakeProvider(),
            settings=Settings(
                memory_decision_mode="hybrid",
                memory_decision_timeout_ms=1000,
                memory_recall_backend="mem0",
                memory_recall_timeout_ms=1000,
            ),
            decision_judge=FailingJudge(),
        )

        prompt = await runtime.retrieve_prompt("delete project-x before deployment")

        assert prompt == ""

    asyncio.run(run())


def test_memory_runtime_smart_write_uses_provider_conversation_turns() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.turn_calls: list[dict[str, object]] = []
            self.raw_calls = 0

        async def add_conversation_turns(self, **kwargs):
            self.turn_calls.append(kwargs)
            return 1

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            self.raw_calls += 1
            return 1

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
            settings=Settings(memory_smart_write_enabled=True, memory_write_mode="hybrid"),
        )

        runtime.schedule_write(
            user_text="记住，我喜欢简洁回答。",
            assistant_text="好的。",
            interrupted=False,
        )
        await runtime.drain()

        assert provider.raw_calls == 0
        assert provider.turn_calls[0]["turns"] == [
            {"role": "user", "content": "记住，我喜欢简洁回答。"},
        ]
        assert provider.turn_calls[0]["include_assistant_context"] is False

    asyncio.run(run())


def test_memory_runtime_smart_write_includes_recent_context_for_relation_correction() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.turn_calls: list[dict[str, object]] = []
            self.raw_items: list[MemoryItem] = []

        async def add_conversation_turns(self, **kwargs):
            self.turn_calls.append(kwargs)
            return 0

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **kwargs):
            self.raw_items.extend(kwargs["items"])
            return len(kwargs["items"])

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
            settings=Settings(memory_smart_write_enabled=True, memory_write_mode="hybrid"),
        )

        runtime.schedule_write(
            user_text="我女朋友叫小雨。",
            assistant_text="我记住了。",
            interrupted=False,
        )
        await runtime.drain()
        runtime.schedule_write(
            user_text="不是女朋友，是前女友。",
            assistant_text="明白，小雨是你的前女友。",
            interrupted=False,
        )
        await runtime.drain()

        second_turns = provider.turn_calls[-1]["turns"]
        assert {"role": "user", "content": "我女朋友叫小雨。"} in second_turns
        assert {"role": "user", "content": "不是女朋友，是前女友。"} in second_turns
        assert any(item.text == "小雨是用户的前女友。" for item in provider.raw_items)

    asyncio.run(run())


def test_memory_runtime_mem0_candidate_noop_does_not_fall_back_to_raw_item() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.turn_calls = 0
            self.raw_items: list[MemoryItem] = []

        async def add_conversation_turns(self, **_kwargs):
            self.turn_calls += 1
            return 0

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **kwargs):
            self.raw_items.extend(kwargs["items"])
            return len(kwargs["items"])

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
            settings=Settings(memory_smart_write_enabled=True, memory_write_mode="hybrid"),
        )

        runtime.schedule_write(
            user_text="我在准备雅思考试，想每天练口语。",
            assistant_text="好，我陪你练。",
            interrupted=False,
        )
        await runtime.drain()

        assert provider.turn_calls == 1
        assert provider.raw_items == []

    asyncio.run(run())


def test_memory_runtime_medium_mem0_candidate_does_not_raw_fallback() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.turn_calls = 0
            self.raw_calls = 0

        async def add_conversation_turns(self, **_kwargs):
            self.turn_calls += 1
            raise RuntimeError("mem0 unavailable")

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            self.raw_calls += 1
            return 1

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
            settings=Settings(memory_smart_write_enabled=True, memory_write_mode="hybrid"),
        )

        runtime.schedule_write(
            user_text="我最近可能会多聊英语学习。",
            assistant_text="好，我会尽量用轻松的方式陪你练。",
            interrupted=False,
        )
        await runtime.drain()

        assert provider.turn_calls == 1
        assert provider.raw_calls == 0

    asyncio.run(run())


def test_memory_runtime_summary_buffers_regular_context_when_write_is_rejected() -> None:
    class FakeSummaryAgent:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        async def summarize(self, turns: list[dict[str, str]], *, max_items: int) -> str:
            self.calls.append(turns)
            return "用户连续进行了两轮普通铺垫对话。"

    class FakeProvider:
        def __init__(self) -> None:
            self.summary_calls: list[dict[str, object]] = []

        async def add_summary(self, **kwargs):
            self.summary_calls.append(kwargs)
            return 1

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            return 0

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        provider = FakeProvider()
        summary_agent = FakeSummaryAgent()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
            settings=Settings(
                memory_summary_enabled=True,
                memory_summary_turn_window=2,
                memory_summary_max_items=2,
            ),
            summary_agent=summary_agent,
        )

        runtime.schedule_write(
            user_text="第一轮普通铺垫内容。",
            assistant_text="我听着。",
            interrupted=False,
        )
        runtime.schedule_write(
            user_text="第二轮普通铺垫内容。",
            assistant_text="继续说。",
            interrupted=False,
        )
        await runtime.drain()

        assert len(summary_agent.calls) == 1
        assert provider.summary_calls[0]["summary"] == "用户连续进行了两轮普通铺垫对话。"

    asyncio.run(run())


def test_memory_runtime_emits_structured_info_logs_without_user_text(caplog) -> None:
    class FakeProvider:
        async def add_conversation_turns(self, **_kwargs):
            return 1

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            return 1

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        caplog.set_level(logging.INFO, logger="opentalking.providers.memory.runtime")
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=FakeProvider(),
            settings=Settings(memory_smart_write_enabled=True, memory_write_mode="hybrid"),
        )

        runtime.schedule_write(
            user_text="我在准备雅思考试。",
            assistant_text="我会陪你练习。",
            interrupted=False,
        )
        await runtime.drain()

        messages = [record.getMessage() for record in caplog.records]
        assert any(
            "memory.write decision action=mem0_infer category=mem0_candidate confidence=unknown reason=needs_smart_judgement"
            in message
            for message in messages
        )
        assert any("memory.write stored count=1 provider=mem0" in message for message in messages)
        assert all("我在准备雅思考试" not in message for message in messages)

    asyncio.run(run())


def test_memory_runtime_summary_buffers_turns_and_writes_summary() -> None:
    class FakeSummaryAgent:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        async def summarize(self, turns: list[dict[str, str]], *, max_items: int) -> str:
            self.calls.append(turns)
            assert max_items == 2
            return "用户喜欢简洁回答，并且正在优化记忆库。"

    class FakeProvider:
        def __init__(self) -> None:
            self.summary_calls: list[dict[str, object]] = []

        async def add_summary(self, **kwargs):
            self.summary_calls.append(kwargs)
            return 1

        async def list_libraries(self, **_kwargs):
            return []

        async def create_library(self, **_kwargs):
            raise AssertionError("not used")

        async def get_library(self, **_kwargs):
            return None

        async def list_items(self, **_kwargs):
            return []

        async def add_items(self, **_kwargs):
            return 1

        async def delete_item(self, **_kwargs):
            return False

        async def close(self):
            return None

    async def run() -> None:
        provider = FakeProvider()
        summary_agent = FakeSummaryAgent()
        runtime = MemoryRuntime(
            scope=MemoryScope(
                enabled=True,
                profile_id="default",
                character_id="avatar-a",
                library_id="default",
            ),
            provider=provider,
            settings=Settings(
                memory_summary_enabled=True,
                memory_summary_turn_window=2,
                memory_summary_max_items=2,
                memory_smart_write_enabled=False,
            ),
            summary_agent=summary_agent,
        )

        runtime.schedule_write(user_text="第一轮普通聊天", assistant_text="好的。", interrupted=False)
        runtime.schedule_write(
            user_text="第二轮：记住，我喜欢简洁回答。",
            assistant_text="记住了。",
            interrupted=False,
        )
        await runtime.drain()

        assert len(summary_agent.calls) == 1
        assert provider.summary_calls[0]["summary"] == "用户喜欢简洁回答，并且正在优化记忆库。"
        assert provider.summary_calls[0]["metadata"]["source_type"] == "session_summary"
        assert provider.summary_calls[0]["metadata"]["layer"] == "episodic"
        assert provider.summary_calls[0]["metadata"]["category"] == "episode_summary"
        assert provider.summary_calls[0]["metadata"]["turn_count"] == 2

    asyncio.run(run())
