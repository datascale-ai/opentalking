#!/usr/bin/env python3
"""Minimal WHEP headless receiver used by the local MediaMTX harness."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription


async def run(args: argparse.Namespace) -> int:
    pc = RTCPeerConnection()
    stats: dict[str, object] = {"video": 0, "audio": 0, "codecs": []}

    @pc.on("track")
    def on_track(track) -> None:
        async def consume() -> None:
            deadline = asyncio.get_running_loop().time() + max(1, args.seconds)
            while asyncio.get_running_loop().time() < deadline:
                try:
                    await asyncio.wait_for(track.recv(), timeout=2.0)
                except Exception:
                    break
                stats[track.kind] = int(stats.get(track.kind, 0)) + 1

        asyncio.create_task(consume())

    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
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
    await pc.setRemoteDescription(RTCSessionDescription(sdp=response.text, type="answer"))
    await asyncio.sleep(max(1, args.seconds))
    if args.stats:
        Path(args.stats).write_text(json.dumps(stats, indent=2), encoding="utf-8")
    await pc.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--stats", default="")
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
