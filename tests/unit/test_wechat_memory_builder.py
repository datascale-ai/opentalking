from __future__ import annotations

from opentalking.persona import memory_builder
from opentalking.persona.memory_builder import build_wechat_persona_draft
from opentalking.persona.weflow_parser import WeFlowExport, WeFlowSpeaker, WeFlowTurn


def sample_export() -> WeFlowExport:
    return WeFlowExport(
        conversation_id="wxid_friend",
        detected_format="raw_json",
        source_metadata={"source_name": "weflow.json", "byte_size": 1234},
        speakers=[
            WeFlowSpeaker(id="wxid_friend", name="Li", message_count=4),
            WeFlowSpeaker(id="self_wxid", name="me", message_count=2, is_self=True),
        ],
        turns=[
            WeFlowTurn(
                message_id="1",
                speaker_id="wxid_friend",
                speaker_name="Li",
                content="morning, breathe first. keep it small today.",
                timestamp="2025-02-05T08:00:00+08:00",
            ),
            WeFlowTurn(
                message_id="2",
                speaker_id="self_wxid",
                speaker_name="me",
                content="I am nervous about the demo.",
                timestamp="2025-02-05T08:01:00+08:00",
                is_self=True,
            ),
            WeFlowTurn(
                message_id="3",
                speaker_id="wxid_friend",
                speaker_name="Li",
                content="then make one tiny checklist and ping me after lunch.",
                timestamp="2025-02-05T08:02:00+08:00",
            ),
            WeFlowTurn(
                message_id="4",
                speaker_id="wxid_friend",
                speaker_name="Li",
                content="no need to be heroic, steady is enough.",
                timestamp="2025-02-05T08:03:00+08:00",
            ),
            WeFlowTurn(
                message_id="5",
                speaker_id="wxid_friend",
                speaker_name="Li",
                content="demo secret code is 8848 and should never be copied raw.",
                timestamp="2025-02-05T08:04:00+08:00",
            ),
        ],
    )


def test_builder_filters_target_speaker_and_creates_safe_persona(monkeypatch) -> None:
    async def empty_complete(self, messages):
        return ""

    monkeypatch.setattr(memory_builder._ConfiguredPersonaLLM, "complete", empty_complete)

    draft = build_wechat_persona_draft(sample_export(), target_speaker_id="wxid_friend")

    assert draft.target_speaker.id == "wxid_friend"
    assert draft.target_speaker.name == "Li"
    assert draft.persona_name == "Li"
    assert "# Persona" in draft.persona_md
    assert "# Speaking Style" in draft.persona_md
    assert "wechat_import" in draft.source_metadata["source"]
    assert "I am nervous about the demo" not in draft.persona_md
    assert "8848" not in draft.persona_md
    assert "demo secret code" not in draft.persona_md


def test_builder_returns_layered_memory_items_without_raw_transcript_copy() -> None:
    draft = build_wechat_persona_draft(sample_export(), target_speaker_id="wxid_friend")

    types = {item.type for item in draft.memory_items}
    layers = {item.metadata["layer"] for item in draft.memory_items}
    assert {"preference", "summary", "note"}.issubset(types)
    assert {"style", "episodic", "semantic"}.issubset(layers)
    assert all(item.metadata["source"] == "wechat_import" for item in draft.memory_items)
    assert all(item.metadata["target_speaker_id"] == "wxid_friend" for item in draft.memory_items)
    assert all(item.metadata["confidence"] in {"low", "medium", "high"} for item in draft.memory_items)
    assert all("8848" not in item.text for item in draft.memory_items)
    assert all("demo secret code" not in item.text for item in draft.memory_items)


def test_builder_can_use_llm_client_json_response() -> None:
    class FakeLLM:
        async def complete(self, messages):
            assert messages[0]["role"] == "system"
            return '{"persona_md":"# Persona\\nLi is concise.","style_memories":["uses gentle imperative"],"semantic_memories":["prefers small checklists"],"episodic_summaries":["supported a demo preparation chat"],"confidence":"high"}'

    draft = build_wechat_persona_draft(
        sample_export(),
        target_speaker_id="wxid_friend",
        llm_client=FakeLLM(),
    )

    assert draft.persona_md == "# Persona\nLi is concise."
    assert {item.metadata["confidence"] for item in draft.memory_items} == {"high"}
    assert any(item.text == "uses gentle imperative" for item in draft.memory_items)
