#!/usr/bin/env python3
"""GPU-free control-plane smoke for a running OpenTalking unified server."""

from __future__ import annotations

import argparse
import os
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--avatar", required=True)
    parser.add_argument("--model", default="mock")
    parser.add_argument("--tts-provider", default="mock")
    parser.add_argument("--control-token", default="")
    parser.add_argument("--rtmps-endpoint", required=True)
    parser.add_argument("--rtmps-stream-key", required=True)
    parser.add_argument("--rtmps-username", default=os.environ.get("OPENTALKING_HARNESS_RTMPS_USERNAME", ""))
    parser.add_argument("--rtmps-password", default=os.environ.get("OPENTALKING_HARNESS_RTMPS_PASSWORD", ""))
    parser.add_argument("--whip-endpoint", required=True)
    parser.add_argument("--whip-token", default=os.environ.get("OPENTALKING_HARNESS_WHIP_TOKEN", ""))
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.control_token}"} if args.control_token else {}
    with httpx.Client(base_url=args.api, timeout=30, trust_env=False) as client:
        session = client.post(
            "/sessions",
            json={
                "avatar_id": args.avatar,
                "model": args.model,
                "tts_provider": args.tts_provider,
                "stt_provider": "funasr",
            },
        )
        session.raise_for_status()
        sid = session.json()["session_id"]
        client.post(f"/sessions/{sid}/start").raise_for_status()
        for body in (
            {
                "type": "rtmps",
                "name": "local-rtmps",
                "auto_connect": True,
                "transport": {
                    "endpoint": args.rtmps_endpoint,
                    "stream_key": args.rtmps_stream_key,
                    **({"username": args.rtmps_username} if args.rtmps_username else {}),
                    **({"password": args.rtmps_password} if args.rtmps_password else {}),
                },
            },
            {
                "type": "whip",
                "name": "local-whip",
                "auto_connect": True,
                "transport": {"endpoint": args.whip_endpoint, "bearer_token": args.whip_token},
            },
        ):
            response = client.post(f"/sessions/{sid}/outputs", headers=headers, json=body)
            response.raise_for_status()
        speak = client.post(
            f"/sessions/{sid}/speak",
            headers={**headers, "Idempotency-Key": "streaming-e2e-say-1"},
            json={"text": "OpenTalking streaming smoke", "mode": "replace", "tts_provider": args.tts_provider},
        )
        speak.raise_for_status()
        deadline = time.time() + 10
        while time.time() < deadline:
            outputs = client.get(f"/sessions/{sid}/outputs", headers=headers).json()
            if outputs and all(item.get("connection_state") == "connected" for item in outputs):
                print(f"streaming control-plane OK: session={sid} outputs={len(outputs)}")
                return 0
            time.sleep(0.25)
    raise SystemExit("outputs did not become connected before timeout")


if __name__ == "__main__":
    raise SystemExit(main())
