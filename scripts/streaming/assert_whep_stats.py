#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", required=True)
    parser.add_argument("--expect-video", default="video/H264")
    parser.add_argument("--expect-audio", default="audio/opus")
    parser.add_argument("--sdp", default="", help="Optional answer SDP used to verify wire codecs")
    args = parser.parse_args()
    payload = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if int(payload.get("video", 0)) <= 0 or int(payload.get("audio", 0)) <= 0:
        raise SystemExit(f"WHEP received no media: {payload}")
    if args.sdp:
        sdp = Path(args.sdp).read_text(encoding="utf-8")
        section = ""
        video_codecs: set[str] = set()
        audio_codecs: set[str] = set()
        for line in sdp.splitlines():
            if line.startswith("m="):
                section = line.split("=", 1)[1].split(" ", 1)[0].lower()
            match = re.match(r"a=rtpmap:\d+\s+([^/\s]+)/", line, re.IGNORECASE)
            if not match:
                continue
            if section == "video":
                video_codecs.add(match.group(1).lower())
            elif section == "audio":
                audio_codecs.add(match.group(1).lower())
        if "h264" not in video_codecs or "opus" not in audio_codecs:
            raise SystemExit(f"WHEP SDP codecs do not contain H264+opus: video={sorted(video_codecs)} audio={sorted(audio_codecs)}")
    print(f"WHEP media OK: {args.expect_video} + {args.expect_audio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
