#!/usr/bin/env python3
"""Minimal WHEP headless receiver used by the local MediaMTX harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRecorder
from aiortc.mediastreams import MediaStreamTrack


class _CountingTrack(MediaStreamTrack):
    def __init__(self, source: MediaStreamTrack, stats: dict[str, object]) -> None:
        super().__init__()
        self.kind = source.kind
        self._source = source
        self._stats = stats

    async def recv(self):
        frame = await self._source.recv()
        self._stats[self.kind] = int(self._stats.get(self.kind, 0)) + 1
        return frame


async def run(args: argparse.Namespace) -> int:
    pc = RTCPeerConnection()
    stats: dict[str, object] = {"video": 0, "audio": 0, "codecs": []}
    recorder = MediaRecorder(args.output) if args.output else None

    @pc.on("track")
    def on_track(track) -> None:
        counted = _CountingTrack(track, stats)
        if recorder is not None:
            recorder.addTrack(counted)
        else:
            async def drain() -> None:
                deadline = asyncio.get_running_loop().time() + max(1, args.seconds)
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        await asyncio.wait_for(counted.recv(), timeout=2.0)
                    except Exception:
                        return

            asyncio.create_task(drain())

    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    answer_sdp_path = Path(args.answer_sdp) if args.answer_sdp else None
    async with httpx.AsyncClient(
        verify=args.ca_file or True,
        follow_redirects=False,
        trust_env=False,
        timeout=15,
    ) as client:
        response = await client.post(
            args.url,
            headers={
                "Content-Type": "application/sdp",
                "Accept": "application/sdp",
                **({"Authorization": f"Bearer {args.bearer_token}"} if args.bearer_token else {}),
            },
            content=pc.localDescription.sdp.encode("utf-8"),
        )
        response.raise_for_status()
    if answer_sdp_path is not None:
        answer_sdp_path.parent.mkdir(parents=True, exist_ok=True)
        answer_sdp_path.write_text(response.text, encoding="utf-8")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=response.text, type="answer"))
    if recorder is not None:
        await recorder.start()
    await asyncio.sleep(max(1, args.seconds))
    if recorder is not None:
        await recorder.stop()
    if args.stats:
        Path(args.stats).write_text(json.dumps(stats, indent=2), encoding="utf-8")
    await pc.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca-file", default="")
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get(
            "OPENTALKING_HARNESS_WHEP_TOKEN",
            os.environ.get("OPENTALKING_HARNESS_READ_TOKEN", ""),
        ),
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--stats", default="")
    parser.add_argument("--answer-sdp", default="", help="Optional path for the received answer SDP")
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
