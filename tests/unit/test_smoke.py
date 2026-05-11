from __future__ import annotations

from pathlib import Path

import opentalking.models
from opentalking.avatar.manifest import parse_manifest
from opentalking.avatar.validator import validate_avatar_dir
from opentalking.providers.synthesis import list_available_synthesis


def test_list_models() -> None:
    keys = list_available_synthesis()
    assert "wav2lip" in keys
    assert "musetalk" in keys
    assert "flashtalk" in keys
    assert "flashhead" in keys
    assert "quicktalk" in opentalking.models.list_models()


def test_video_wav2lip_demo_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "singer"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_flashhead_demo_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "anchor"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_parse_video_wav2lip_demo_manifest() -> None:
    root = Path(__file__).resolve().parents[2]
    m = parse_manifest(root / "examples" / "avatars" / "singer" / "manifest.json")
    assert m.id == "singer"
    assert m.model_type == "wav2lip"


def test_anime_handsome_guy_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "anime-handsome-guy"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_ancient_beauty_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "ancient-beauty"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_laozi_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "laozi"
    errs = validate_avatar_dir(demo)
    assert errs == []


def test_office_woman_avatar_valid() -> None:
    root = Path(__file__).resolve().parents[2]
    demo = root / "examples" / "avatars" / "office-woman"
    errs = validate_avatar_dir(demo)
    assert errs == []
