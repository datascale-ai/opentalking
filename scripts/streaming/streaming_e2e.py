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
    parser.add_argument(
        "--control-token",
        default=os.environ.get("OPENTALKING_STREAMING_CONTROL_TOKEN", ""),
    )
    parser.add_argument("--rtmps-endpoint", required=True)
    parser.add_argument("--rtmps-stream-key", required=True)
    parser.add_argument("--rtmps-username", default=os.environ.get("OPENTALKING_HARNESS_RTMPS_USERNAME", ""))
    parser.add_argument("--rtmps-password", default=os.environ.get("OPENTALKING_HARNESS_RTMPS_PASSWORD", ""))
    parser.add_argument("--whip-endpoint", required=True)
    parser.add_argument("--whip-token", default=os.environ.get("OPENTALKING_HARNESS_WHIP_TOKEN", ""))
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--wait-healthy-sec", type=float, default=30.0)
    parser.add_argument("--speak-text", default="OpenTalking streaming smoke")
    parser.add_argument("--keep", action="store_true", help="Keep the session/outputs for external receiver checks")
    parser.add_argument("--skip-idempotency-check", action="store_true")
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {args.control_token}"} if args.control_token else {}
    sid = ""
    with httpx.Client(base_url=args.api, timeout=30, trust_env=False) as client:
        try:
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
                json={"text": args.speak_text, "mode": "replace", "tts_provider": args.tts_provider},
            )
            speak.raise_for_status()
            if not args.skip_idempotency_check:
                duplicate = client.post(
                    f"/sessions/{sid}/speak",
                    headers={**headers, "Idempotency-Key": "streaming-e2e-say-1"},
                    json={"text": args.speak_text, "mode": "replace", "tts_provider": args.tts_provider},
                )
                duplicate.raise_for_status()
                if duplicate.json().get("status") not in {"duplicate", "command_in_progress"}:
                    raise SystemExit(f"speak idempotency failed: {duplicate.json()}")
            deadline = time.time() + max(1.0, args.wait_healthy_sec)
            while time.time() < deadline:
                outputs = client.get(f"/sessions/{sid}/outputs", headers=headers).json()
                if outputs and all(
                    item.get("connection_state") == "connected" and item.get("health") == "healthy"
                    for item in outputs
                ):
                    print(f"streaming control-plane OK: session={sid} outputs={len(outputs)} health=healthy")
                    return 0
                time.sleep(0.25)
            raise SystemExit("outputs did not become connected/healthy before timeout")
        finally:
            if not args.keep and sid:
                try:
                    client.delete(f"/sessions/{sid}")
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
