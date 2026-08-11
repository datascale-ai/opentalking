#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffprobe-json", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.ffprobe_json).read_text(encoding="utf-8"))
    streams = payload.get("streams") or []
    codecs = {str(stream.get("codec_name")) for stream in streams}
    if not {"h264", "aac"}.issubset(codecs):
        raise SystemExit(f"expected h264+aac, got {sorted(codecs)}")
    for stream in streams:
        if stream.get("codec_type") in {"video", "audio"} and float(stream.get("duration") or 0) <= 0:
            raise SystemExit("media stream has no positive duration")
    print("media timeline OK: h264 + aac")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

