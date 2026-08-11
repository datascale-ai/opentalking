from __future__ import annotations

import sqlite3

from opentalking.voice import store


def test_init_voice_store_removes_legacy_local_default_voice(tmp_path, monkeypatch):
    db_path = tmp_path / "voices.sqlite3"
    monkeypatch.setattr(store, "get_sqlite_path", lambda: db_path)

    store.init_voice_store()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tts_voice_entries
              (id, user_id, provider, voice_id, display_label, target_model, source)
            VALUES (901, 1, 'local_cosyvoice', 'local-default', '默认本地音色', NULL, 'system')
            """
        )

    store.init_voice_store()

    assert [v.voice_id for v in store.list_voices(provider="local_cosyvoice")] == []


def test_init_voice_store_preserves_minimax_entries(tmp_path, monkeypatch):
    db_path = tmp_path / "voices.sqlite3"
    monkeypatch.setattr(store, "get_sqlite_path", lambda: db_path)

    store.init_voice_store()
    entry_id = store.insert_clone(
        provider="minimax",
        voice_id="custom-minimax-voice",
        display_label="Custom MiniMax voice",
        target_model="speech-2.8-hd",
    )

    store.init_voice_store()

    entry = store.get_entry(entry_id)
    assert entry is not None
    assert entry["provider"] == "minimax"
