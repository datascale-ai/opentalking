from __future__ import annotations

import asyncio
import json
from pathlib import Path

from opentalking.persona import memory_builder
from opentalking.persona.store import PersonaStore
from opentalking.persona.wechat_import import WeChatImportJobRegistry
from opentalking.providers.memory.mem0_provider import InMemoryMemoryProvider


def write_group_export(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "chatlab": {"version": "0.0.2", "generator": "WeFlow"},
                "meta": {"name": "Project room", "platform": "wechat", "type": "group", "groupId": "room@chatroom"},
                "members": [
                    {"platformId": "wxid_li", "accountName": "Li", "groupNickname": "Li"},
                    {"platformId": "wxid_chen", "accountName": "Chen", "groupNickname": "Chen"},
                ],
                "messages": [
                    {
                        "sender": "wxid_li",
                        "accountName": "Li",
                        "groupNickname": "Li",
                        "timestamp": 1738713600,
                        "type": 0,
                        "content": "morning, breathe first. keep it small today.",
                        "platformMessageId": "1",
                    },
                    {
                        "sender": "wxid_chen",
                        "accountName": "Chen",
                        "groupNickname": "Chen",
                        "timestamp": 1738713660,
                        "type": 0,
                        "content": "ship it now, no need to wait.",
                        "platformMessageId": "2",
                    },
                    {
                        "sender": "wxid_li",
                        "accountName": "Li",
                        "groupNickname": "Li",
                        "timestamp": 1738713720,
                        "type": 0,
                        "content": "demo secret code is 8848 and should never be copied raw.",
                        "platformMessageId": "3",
                    },
                ],
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return path


def test_wechat_import_job_requires_speaker_selection(tmp_path: Path) -> None:
    registry = WeChatImportJobRegistry(
        persona_store=PersonaStore(tmp_path / "personas"),
        memory_provider=InMemoryMemoryProvider(),
    )

    job = registry.create_job(
        write_group_export(tmp_path / "weflow.json"),
        profile_id="default",
        memory_library_id="default",
        avatar_id="avatar-li",
        avatar_model="mock",
    )

    assert job.status == "needs_speaker_selection"
    assert [speaker.id for speaker in job.speakers] == ["wxid_li", "wxid_chen"]
    assert job.draft is None


def test_wechat_import_job_selects_speaker_and_commits_persona_and_memory(monkeypatch, tmp_path: Path) -> None:
    async def empty_complete(self, messages):
        return ""

    monkeypatch.setattr(memory_builder._ConfiguredPersonaLLM, "complete", empty_complete)

    provider = InMemoryMemoryProvider()
    store = PersonaStore(tmp_path / "personas")
    registry = WeChatImportJobRegistry(persona_store=store, memory_provider=provider)
    job = registry.create_job(
        write_group_export(tmp_path / "weflow.json"),
        profile_id="default",
        memory_library_id="default",
        avatar_id="avatar-li",
        avatar_model="mock",
    )

    ready = registry.select_speaker(job.id, "wxid_li")

    assert ready.status == "draft_ready"
    assert ready.selected_speaker_id == "wxid_li"
    assert ready.draft is not None
    assert "8848" not in ready.draft.persona_md

    result = asyncio.run(
        registry.commit(
            job.id,
            persona_id="friend-li",
            persona_name="Friend Li",
        )
    )

    assert result.persona_id == "friend-li"
    assert result.memory_imported == 3
    assert result.persona_md_bytes > 0
    record = store.get_persona("friend-li")
    assert record.manifest.avatar.id == "avatar-li"
    assert record.manifest.avatar.model == "mock"
    assert record.manifest.agent.persona_prompt == "persona.md"
    assert record.manifest.agent.memory_enabled is True
    assert (record.path / "persona.md").is_file()
    assert "8848" not in (record.path / "persona.md").read_text(encoding="utf-8")

    items = asyncio.run(
        provider.list_items(library_id="default", profile_id="default", character_id="avatar-li")
    )
    assert len(items) == 3
    assert {item.metadata["layer"] for item in items} == {"style", "semantic", "episodic"}
    assert all(item.metadata["source"] == "wechat_import" for item in items)
    assert all("8848" not in item.text for item in items)
