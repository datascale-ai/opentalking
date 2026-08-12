#!/usr/bin/env python3
"""Capture a local RTSP/RTMPS playback stream for ffprobe checks."""

from __future__ import annotations

import argparse
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-rtsp_transport",
        "tcp",
        "-i",
        args.url,
        "-t",
        str(max(1, args.seconds)),
        "-c",
        "copy",
        args.output,
    ]
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
