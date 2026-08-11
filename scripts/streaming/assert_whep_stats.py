#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", required=True)
    parser.add_argument("--expect-video", default="video/H264")
    parser.add_argument("--expect-audio", default="audio/opus")
    args = parser.parse_args()
    payload = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if int(payload.get("video", 0)) <= 0 or int(payload.get("audio", 0)) <= 0:
        raise SystemExit(f"WHEP received no media: {payload}")
    print(f"WHEP media OK: {args.expect_video} + {args.expect_audio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

