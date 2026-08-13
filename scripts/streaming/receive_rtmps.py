#!/usr/bin/env python3
"""Capture a local RTSP/RTMPS playback stream for ffprobe checks."""

from __future__ import annotations

import argparse
import os
import time
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import av


def _with_credentials(url: str, username: str, password: str) -> str:
    """Add RTSP credentials in-process without exposing them in argv/logs."""
    if not username and not password:
        return url
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError("receiver URL must not contain userinfo")
    if parsed.hostname is None:
        raise ValueError("receiver URL has no host")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _capture(url: str, output: Path, seconds: int) -> int:
    """Remux the authenticated RTSP packets without a child process.

    Keeping the reader in PyAV means runtime credentials stay in this Python
    process memory rather than appearing in an ffmpeg command line.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1, seconds)
    input_container: Any = None
    last_error = "unknown"
    while input_container is None:
        try:
            input_container = av.open(
                url,
                mode="r",
                options={"rtsp_transport": "tcp", "timeout": "2000000"},
            )
        except Exception as exc:  # noqa: BLE001 - retry transient ingest startup
            last_error = type(exc).__name__
            if time.monotonic() >= deadline:
                raise RuntimeError(f"RTSP receiver could not open playback ({last_error})") from None
            time.sleep(0.25)
    output_container = None
    try:
        video_input = next((stream for stream in input_container.streams if stream.type == "video"), None)
        audio_input = next((stream for stream in input_container.streams if stream.type == "audio"), None)
        selected = [stream for stream in (video_input, audio_input) if stream is not None]
        if not selected:
            raise RuntimeError("RTSP receiver found no audio/video streams")
        output_container = av.open(str(output), mode="w")
        output_video = None
        output_audio = None
        if video_input is not None:
            fps = float(video_input.average_rate or 25.0)
            output_video = output_container.add_stream(
                "libx264", rate=Fraction(str(fps)).limit_denominator(1000)
            )
            output_video.width = int(video_input.codec_context.width or 1)
            output_video.height = int(video_input.codec_context.height or 1)
            output_video.pix_fmt = "yuv420p"
            output_video.codec_context.max_b_frames = 0
        if audio_input is not None:
            sample_rate = int(audio_input.codec_context.sample_rate or 48_000)
            output_audio = output_container.add_stream("aac", rate=sample_rate)
            output_audio.layout = "stereo" if int(audio_input.codec_context.channels or 1) > 1 else "mono"
        output_streams = {
            **({video_input.index: output_video} if video_input is not None and output_video is not None else {}),
            **({audio_input.index: output_audio} if audio_input is not None and output_audio is not None else {}),
        }
        # RTSP readers can join between a video GOP and an audio packet.  The
        # demuxed frame timestamps are then not guaranteed to be a usable
        # encoder clock for a newly created output container.  Keep an
        # independent next-PTS clock for each media type so a late join or
        # cross-stream interleave cannot make the output muxer reject a
        # backwards timestamp.
        next_pts = {"video": 0, "audio": 0}
        for packet in input_container.demux(selected):
            if time.monotonic() >= deadline:
                break
            destination = output_streams.get(packet.stream.index)
            if destination is None:
                continue
            source = packet.stream
            for frame in packet.decode():
                if source.type == "video":
                    fps = float(source.average_rate or 25.0)
                    timestamp = float(frame.time or 0.0)
                    time_base = Fraction(1, max(1, int(round(fps))))
                    proposed_pts = max(0, int(round(timestamp * fps)))
                    frame_pts = max(proposed_pts, next_pts["video"])
                    frame.pts = frame_pts
                    frame.time_base = time_base
                    next_pts["video"] = frame_pts + 1
                else:
                    sample_rate = int(source.codec_context.sample_rate or 48_000)
                    timestamp = float(frame.time or 0.0)
                    time_base = Fraction(1, sample_rate)
                    proposed_pts = max(0, int(round(timestamp * sample_rate)))
                    frame_pts = max(proposed_pts, next_pts["audio"])
                    frame.pts = frame_pts
                    frame.time_base = time_base
                    next_pts["audio"] = frame_pts + max(1, int(frame.samples or 1))
                for encoded in destination.encode(frame):
                    output_container.mux(encoded)
        for destination in (output_video, output_audio):
            if destination is not None:
                for packet in destination.encode(None):
                    output_container.mux(packet)
    finally:
        if output_container is not None:
            output_container.close()
        input_container.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--username", default=os.environ.get("OPENTALKING_HARNESS_READ_USERNAME", ""))
    parser.add_argument("--password", default=os.environ.get("OPENTALKING_HARNESS_READ_PASSWORD", ""))
    args = parser.parse_args()
    authenticated_url = _with_credentials(args.url, args.username, args.password)
    return _capture(authenticated_url, Path(args.output), args.seconds)


if __name__ == "__main__":
    raise SystemExit(main())
