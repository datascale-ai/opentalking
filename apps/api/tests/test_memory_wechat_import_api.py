from __future__ import annotations

import json
from pathlib import Path

from opentalking.persona import memory_builder
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import memory as memory_routes
from opentalking.persona.store import PersonaStore
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
                    {"sender": "wxid_li", "accountName": "Li", "groupNickname": "Li", "timestamp": 1738713600, "type": 0, "content": "calm small steps.", "platformMessageId": "1"},
                    {"sender": "wxid_chen", "accountName": "Chen", "groupNickname": "Chen", "timestamp": 1738713660, "type": 0, "content": "ship now.", "platformMessageId": "2"},
                    {"sender": "wxid_li", "accountName": "Li", "groupNickname": "Li", "timestamp": 1738713720, "type": 0, "content": "demo secret code is 8848 and should never be copied raw.", "platformMessageId": "3"},
                ],
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    return path


def test_memory_api_wechat_import_upload_select_commit(monkeypatch, tmp_path: Path) -> None:
    async def empty_complete(self, messages):
        return ""

    monkeypatch.setattr(memory_builder._ConfiguredPersonaLLM, "complete", empty_complete)

    provider = InMemoryMemoryProvider()
    store = PersonaStore(tmp_path / "personas")
    monkeypatch.setattr(memory_routes, "build_memory_provider", lambda: provider)

    app = FastAPI()
    app.state.persona_store = store
    app.include_router(memory_routes.router)
    export_path = write_group_export(tmp_path / "weflow.json")

    with TestClient(app) as client:
        with export_path.open("rb") as file:
            created = client.post(
                "/memory/wechat-import",
                data={
                    "profile_id": "default",
                    "memory_library_id": "default",
                    "avatar_id": "avatar-li",
                    "avatar_model": "mock",
                },
                files={"file": ("weflow.json", file, "application/json")},
            )
        assert created.status_code == 200
        payload = created.json()
        assert payload["status"] == "needs_speaker_selection"
        assert [speaker["id"] for speaker in payload["speakers"]] == ["wxid_li", "wxid_chen"]

        job_id = payload["id"]
        selected = client.post(f"/memory/wechat-import/{job_id}/speaker", json={"target_speaker_id": "wxid_li"})
        assert selected.status_code == 200
        assert selected.json()["status"] == "draft_ready"
        assert "8848" not in selected.json()["persona_md"]

        committed = client.post(
            f"/memory/wechat-import/{job_id}/commit",
            json={"persona_id": "friend-li", "persona_name": "Friend Li"},
        )
        assert committed.status_code == 200
        assert committed.json()["persona_id"] == "friend-li"
        assert committed.json()["memory_imported"] == 3

    record = store.get_persona("friend-li")
    assert record.manifest.avatar.id == "avatar-li"
    assert (record.path / "persona.md").is_file()


def test_memory_api_wechat_import_rejects_api_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(memory_routes, "build_memory_provider", lambda: InMemoryMemoryProvider())
    app = FastAPI()
    app.state.persona_store = PersonaStore(tmp_path / "personas")
    app.include_router(memory_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/memory/wechat-import",
            data={
                "source_url": "http://127.0.0.1:5031/api/v1/messages?talker=wxid_xxx",
                "avatar_id": "avatar-li",
                "avatar_model": "mock",
            },
        )

    assert response.status_code == 400
    assert "upload" in response.json()["detail"]
