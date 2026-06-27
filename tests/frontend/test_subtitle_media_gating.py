from __future__ import annotations

from pathlib import Path


def test_subtitle_chunks_wait_for_media_started_before_updating_chat_bubble() -> None:
    source = Path("apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert "const flushSubtitleMessage" in source
    assert "flushSubtitleMessage();" in source

    media_started_idx = source.index('if (ev === "speech.media_started")')
    chunk_idx = source.index('if (ev === "subtitle.chunk"')
    ended_idx = source.index('if (ev === "speech.ended")')
    media_started_block = source[media_started_idx:chunk_idx]
    chunk_block = source[chunk_idx:ended_idx]

    assert "flushSubtitleMessage();" in media_started_block
    assert "if (subtitleMediaReadyRef.current)" in chunk_block
    assert "setMessages((prev)" not in chunk_block
