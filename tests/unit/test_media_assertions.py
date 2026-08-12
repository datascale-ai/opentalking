from __future__ import annotations

import json

import pytest

from scripts.streaming import assert_media_timeline, assert_whep_stats


def test_media_timeline_accepts_current_ffprobe_combined_shape(tmp_path, monkeypatch) -> None:
    payload = {
        "streams": [
            {"codec_name": "h264", "codec_type": "video", "duration": "1"},
            {"codec_name": "aac", "codec_type": "audio", "duration": "1"},
        ],
        "packets_and_frames": [
            {"type": "packet", "codec_type": "video", "pts_time": "0.0"},
            {"type": "packet", "codec_type": "video", "pts_time": "0.04"},
            {"type": "packet", "codec_type": "audio", "pts_time": "0.0"},
            {"type": "packet", "codec_type": "audio", "pts_time": "0.02"},
        ],
    }
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "assert_media_timeline",
            "--ffprobe-json",
            str(path),
            "--video-max-gap-ms",
            "120",
            "--audio-max-gap-ms",
            "60",
            "--av-drift-p95-ms",
            "100",
            "--av-drift-max-ms",
            "250",
        ],
    )
    assert assert_media_timeline.main() == 0


def test_whep_stats_checks_answer_codecs(tmp_path, monkeypatch) -> None:
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"video": 2, "audio": 2}), encoding="utf-8")
    answer = tmp_path / "answer.sdp"
    answer.write_text(
        "m=video 9 UDP/TLS/RTP/SAVPF 102\n"
        "a=rtpmap:102 H264/90000\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\n"
        "a=rtpmap:111 opus/48000/2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["assert_whep_stats", "--stats", str(stats), "--sdp", str(answer)],
    )
    assert assert_whep_stats.main() == 0


def test_whep_stats_rejects_missing_wire_codec(tmp_path, monkeypatch) -> None:
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"video": 2, "audio": 2}), encoding="utf-8")
    answer = tmp_path / "answer.sdp"
    answer.write_text(
        "m=video 9 UDP/TLS/RTP/SAVPF 96\n"
        "a=rtpmap:96 VP8/90000\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\n"
        "a=rtpmap:111 opus/48000/2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["assert_whep_stats", "--stats", str(stats), "--sdp", str(answer)],
    )
    with pytest.raises(SystemExit, match="H264"):
        assert_whep_stats.main()
