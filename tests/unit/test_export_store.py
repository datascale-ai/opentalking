from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentalking.export_store import (
    ExportTooLargeError,
    create_video_export,
    delete_video_export,
    get_video_export,
    list_video_exports,
)


def test_create_video_export_writes_file_and_metadata(tmp_path: Path) -> None:
    item = create_video_export(
        tmp_path,
        content=b"webm-bytes",
        mime_type="video/webm",
        kind="realtime_dialogue",
        title="Realtime clip",
        duration_sec=12.5,
        session_id="sess_1",
        avatar_id="anchor",
        model="fasterliveportrait",
        max_bytes=1024,
    )

    assert item["kind"] == "realtime_dialogue"
    assert item["title"] == "Realtime clip"
    assert item["duration_sec"] == 12.5
    assert item["size_bytes"] == len(b"webm-bytes")
    assert item["mime_type"] == "video/webm"
    assert item["session_id"] == "sess_1"
    assert item["avatar_id"] == "anchor"
    assert item["model"] == "fasterliveportrait"
    assert item["path"].endswith("recording.webm")
    assert Path(item["path"]).read_bytes() == b"webm-bytes"

    metadata = json.loads((Path(item["path"]).parent / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["id"] == item["id"]
    assert metadata["path"] == item["path"]


def test_create_video_export_accepts_video_creation_kind(tmp_path: Path) -> None:
    item = create_video_export(
        tmp_path,
        content=b"mp4-bytes",
        mime_type="video/mp4",
        kind="video_creation",
        title="Video creation clip",
        duration_sec=2.5,
        session_id=None,
        avatar_id="anchor",
        model="quicktalk",
        max_bytes=1024,
    )

    assert item["kind"] == "video_creation"
    assert item["title"] == "Video creation clip"
    assert item["avatar_id"] == "anchor"
    assert item["model"] == "quicktalk"
    assert item["path"].endswith("recording.mp4")


def test_list_video_exports_newest_first_and_filters_kind(tmp_path: Path) -> None:
    older = create_video_export(
        tmp_path,
        content=b"a",
        mime_type="video/webm",
        kind="realtime_dialogue",
        title="older",
        duration_sec=1.0,
        session_id="sess_old",
        avatar_id="anchor",
        model="flashtalk",
        max_bytes=1024,
        created_at="2026-06-02T01:00:00Z",
    )
    newer = create_video_export(
        tmp_path,
        content=b"b",
        mime_type="video/webm",
        kind="video_clone",
        title="newer",
        duration_sec=2.0,
        session_id=None,
        avatar_id="anchor",
        model="fasterliveportrait",
        max_bytes=1024,
        created_at="2026-06-02T02:00:00Z",
    )

    assert [item["id"] for item in list_video_exports(tmp_path)] == [newer["id"], older["id"]]
    assert [item["id"] for item in list_video_exports(tmp_path, kind="video_clone")] == [newer["id"]]


def test_get_and_delete_video_export(tmp_path: Path) -> None:
    item = create_video_export(
        tmp_path,
        content=b"x",
        mime_type="video/mp4",
        kind="video_clone",
        title="clip",
        duration_sec=None,
        session_id=None,
        avatar_id=None,
        model=None,
        max_bytes=1024,
    )

    assert get_video_export(tmp_path, item["id"])["id"] == item["id"]
    delete_video_export(tmp_path, item["id"])

    assert get_video_export(tmp_path, item["id"]) is None
    assert not Path(item["path"]).exists()


def test_create_video_export_rejects_oversized_content(tmp_path: Path) -> None:
    with pytest.raises(ExportTooLargeError):
        create_video_export(
            tmp_path,
            content=b"too-large",
            mime_type="video/webm",
            kind="realtime_dialogue",
            title="big",
            duration_sec=None,
            session_id=None,
            avatar_id=None,
            model=None,
            max_bytes=3,
        )

    assert list(tmp_path.rglob("metadata.json")) == []
