from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routes import memory as memory_routes
from apps.api.routes import sessions as sessions_routes
from opentalking.core.config import Settings, get_settings
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.core.redis_keys import TASK_QUEUE
from opentalking.core.session_store import get_session_record
from opentalking.providers.memory import factory as memory_factory
from opentalking.providers.memory.mem0_provider import InMemoryMemoryProvider
from opentalking.providers.memory.noop import NoopMemoryProvider


def test_memory_api_import_list_delete(monkeypatch) -> None:
    provider = InMemoryMemoryProvider()
    monkeypatch.setattr(memory_routes, "build_memory_provider", lambda: provider)

    app = FastAPI()
    app.include_router(memory_routes.router)

    with TestClient(app) as client:
        created = client.post(
            "/memory/libraries",
            json={"id": "default", "name": "Default", "character_id": "avatar-a"},
        )
        assert created.status_code == 200
        assert created.json()["id"] == "default"

        imported = client.post(
            "/memory/libraries/default/import",
            json={
                "profile_id": "default",
                "character_id": "avatar-a",
                "source": "fixture",
                "turns": [
                    {"role": "user", "content": "Remember that I like green tea."},
                    {"role": "assistant", "content": "Noted."},
                ],
            },
        )
        assert imported.status_code == 200
        assert imported.json() == {"imported": 1}

        listed = client.get(
            "/memory/libraries/default/items",
            params={"profile_id": "default", "character_id": "avatar-a"},
        )
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert len(items) == 1
        assert items[0]["text"] == "Remember that I like green tea."

        libraries = client.get(
            "/memory/libraries",
            params={"profile_id": "default", "character_id": "avatar-a"},
        )
        assert libraries.status_code == 200
        assert libraries.json()["items"][0]["memory_count"] == 1

        deleted = client.delete(
            f"/memory/libraries/default/items/{items[0]['id']}",
            params={"profile_id": "default", "character_id": "avatar-a"},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}


def test_mem0_provider_without_credentials_uses_noop(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.setattr(
        memory_factory,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            memory_provider="mem0",
            memory_mem0_llm_api_key="",
            memory_mem0_embedder_api_key="",
            memory_mem0_config="",
        ),
    )
    memory_factory.build_memory_provider.cache_clear()
    try:
        provider = memory_factory.build_memory_provider()
    finally:
        memory_factory.build_memory_provider.cache_clear()

    assert isinstance(provider, NoopMemoryProvider)


def test_memory_api_generates_unique_library_ids_when_id_is_omitted(monkeypatch) -> None:
    provider = InMemoryMemoryProvider()
    monkeypatch.setattr(memory_routes, "build_memory_provider", lambda: provider)

    app = FastAPI()
    app.include_router(memory_routes.router)

    with TestClient(app) as client:
        first = client.post(
            "/memory/libraries",
            json={"name": "First", "character_id": "avatar-a"},
        )
        second = client.post(
            "/memory/libraries",
            json={"name": "Second", "character_id": "avatar-a"},
        )
        libraries = client.get(
            "/memory/libraries",
            params={"profile_id": "default", "character_id": "avatar-a"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["id"] != "default"
    assert second.json()["id"] != "default"
    assert libraries.status_code == 200
    assert len(libraries.json()["items"]) == 2


def test_memory_api_uses_configured_sqlite_provider(monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "opentalking.yaml"
    config_file.write_text(
        f"""
memory:
  provider: sqlite
  sqlite_path: {str(tmp_path / "memory.sqlite3")}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("OPENTALKING_MEMORY_PROVIDER", "sqlite")
    monkeypatch.setenv("OPENTALKING_MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite3"))
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(memory_routes.router)

    try:
        with TestClient(app) as client:
            created = client.post(
                "/memory/libraries",
                json={"id": "default", "name": "Default", "character_id": "avatar-a"},
            )
            imported = client.post(
                "/memory/libraries/default/import",
                json={
                    "profile_id": "default",
                    "character_id": "avatar-a",
                    "source": "fixture",
                    "turns": [{"role": "user", "content": "记住，我喜欢简洁回答。"}],
                },
            )
            listed = client.get(
                "/memory/libraries/default/items",
                params={"profile_id": "default", "character_id": "avatar-a"},
            )

        assert created.status_code == 200
        assert imported.status_code == 200
        assert listed.status_code == 200
        assert listed.json()["items"][0]["text"] == "记住，我喜欢简洁回答。"
    finally:
        get_settings.cache_clear()


def test_memory_api_and_session_scope_contract(monkeypatch, tmp_path) -> None:
    async def run() -> None:
        config_file = tmp_path / "opentalking.yaml"
        config_file.write_text(
            f"""
memory:
  provider: sqlite
  enabled: false
  sqlite_path: {str(tmp_path / "memory.sqlite3")}
models:
  mock:
    backend: mock
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENTALKING_CONFIG_FILE", str(config_file))
        monkeypatch.setenv("OPENTALKING_MEMORY_PROVIDER", "sqlite")
        monkeypatch.setenv("OPENTALKING_MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite3"))
        get_settings.cache_clear()
        settings = get_settings()
        redis = InMemoryRedis()

        app = FastAPI()
        app.state.redis = redis
        app.state.settings = settings
        app.include_router(memory_routes.router)
        app.include_router(sessions_routes.router)

        with TestClient(app) as client:
            created_library = client.post(
                "/memory/libraries",
                json={"id": "demo", "name": "Demo", "character_id": "singer"},
            )
            imported = client.post(
                "/memory/libraries/demo/import",
                json={
                    "profile_id": "default",
                    "character_id": "singer",
                    "source": "fixture",
                    "turns": [{"role": "user", "content": "记住，我喜欢简洁回答。"}],
                },
            )
            session = client.post(
                "/sessions",
                    json={
                        "avatar_id": "singer",
                        "model": "mock",
                        "stt_provider": "sensevoice",
                        "tts_provider": "edge",
                        "memory_enabled": True,
                        "memory_profile_id": "default",
                        "character_id": "singer",
                    "memory_library_id": "demo",
                },
            )

        assert created_library.status_code == 200
        assert imported.status_code == 200
        assert session.status_code == 200
        sid = session.json()["session_id"]
        rec = await get_session_record(redis, sid)
        assert rec is not None
        assert rec["memory_enabled"] in {"1", "true"}
        assert rec["memory_profile_id"] == "default"
        assert rec["character_id"] == "singer"
        assert rec["memory_library_id"] == "demo"

        popped = await redis.brpop(TASK_QUEUE, timeout=1)
        assert popped is not None
        task = json.loads(popped[1])
        assert task["memory_enabled"] is True
        assert task["memory_library_id"] == "demo"

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
