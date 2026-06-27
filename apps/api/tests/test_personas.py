from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import personas as persona_routes
from opentalking.agent.knowledge_store import KnowledgeStore
from opentalking.persona.store import PersonaStore


def _write_package(path: Path) -> None:
    manifest = """
{
  "schema_version": "0.1",
  "id": "api-support-zh",
  "name": "API 客服",
  "description": "API 导入测试",
  "locale": "zh-CN",
  "avatar": {"id": "singer", "model": "mock"},
  "voice": {"provider": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"},
  "agent": {"memory_enabled": false, "knowledge_enabled": true},
  "runtime": {"stt_provider": "sensevoice", "tts_provider": "edge"},
  "safety": {"authorized_avatar": true, "authorized_voice": true, "content_label_required": true}
}
""".strip()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("persona.json", manifest)


def test_persona_import_list_delete_api(monkeypatch, tmp_path: Path) -> None:
    store = PersonaStore(tmp_path / "personas")
    knowledge_store = KnowledgeStore(
        db_path=tmp_path / "agent.sqlite",
        knowledge_root=tmp_path / "knowledge",
    )
    monkeypatch.setattr(persona_routes, "default_persona_store", lambda: store)
    monkeypatch.setattr(persona_routes, "default_knowledge_store", lambda: knowledge_store)

    app = FastAPI()
    app.include_router(persona_routes.router)
    package = tmp_path / "support.otpersona"
    _write_package(package)

    with TestClient(app) as client:
        response = client.post(
            "/personas/import",
            files={"file": ("support.otpersona", package.read_bytes(), "application/zip")},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["id"] == "api-support-zh"

        listed = client.get("/personas")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["personas"]] == ["api-support-zh"]

        detail = client.get("/personas/api-support-zh")
        assert detail.status_code == 200
        assert detail.json()["avatar"]["id"] == "singer"

        deleted = client.delete("/personas/api-support-zh")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}

        listed_after = client.get("/personas")
        assert listed_after.json()["personas"] == []


def test_persona_api_rejects_non_package(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(persona_routes, "default_persona_store", lambda: PersonaStore(tmp_path / "personas"))
    monkeypatch.setattr(
        persona_routes,
        "default_knowledge_store",
        lambda: SimpleNamespace(),
    )
    app = FastAPI()
    app.include_router(persona_routes.router)

    with TestClient(app) as client:
        response = client.post(
            "/personas/import",
            files={"file": ("bad.txt", b"x", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "persona package must be .otpersona or .zip"



def test_persona_md_api_reads_and_updates_file(monkeypatch, tmp_path: Path) -> None:
    store = PersonaStore(tmp_path / "personas")
    persona_dir = tmp_path / "personas" / "friend-li"
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.md").write_text("# Persona\n旧人设", encoding="utf-8")
    (persona_dir / "persona.json").write_text(
        """
{
  "schema_version": "0.1",
  "id": "friend-li",
  "name": "小李",
  "description": "微信导入生成的 Persona",
  "locale": "zh-CN",
  "avatar": {"id": "custom-friend-li", "model": "mock"},
  "agent": {"persona_prompt": "persona.md", "memory_enabled": true, "knowledge_enabled": false},
  "safety": {"authorized_avatar": true, "authorized_voice": false, "content_label_required": true}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_routes, "default_persona_store", lambda: store)

    app = FastAPI()
    app.include_router(persona_routes.router)

    with TestClient(app) as client:
        loaded = client.get("/personas/friend-li/persona-md")
        assert loaded.status_code == 200
        assert loaded.json() == {"persona_id": "friend-li", "content": "# Persona\n旧人设"}

        updated = client.put(
            "/personas/friend-li/persona-md",
            json={"content": "# Persona\n新人设"},
        )
        assert updated.status_code == 200
        assert updated.json() == {"persona_id": "friend-li", "content": "# Persona\n新人设"}

        loaded_again = client.get("/personas/friend-li/persona-md")
        assert loaded_again.json()["content"] == "# Persona\n新人设"


def test_persona_md_api_rejects_path_escape(monkeypatch, tmp_path: Path) -> None:
    store = PersonaStore(tmp_path / "personas")
    persona_dir = tmp_path / "personas" / "bad"
    persona_dir.mkdir(parents=True)
    (persona_dir / "persona.json").write_text(
        '{"schema_version":"0.1","id":"bad","name":"bad","description":"bad","locale":"zh-CN","avatar":{"id":"a","model":"mock"},"agent":{"persona_prompt":"../escape.md"}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(persona_routes, "default_persona_store", lambda: store)
    app = FastAPI()
    app.include_router(persona_routes.router)

    with TestClient(app) as client:
        response = client.get("/personas/bad/persona-md")

    assert response.status_code == 400
