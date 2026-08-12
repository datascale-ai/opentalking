#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffprobe-json", required=True)
    parser.add_argument("--video-max-gap-ms", type=float, default=None)
    parser.add_argument("--audio-max-gap-ms", type=float, default=None)
    parser.add_argument("--av-drift-p95-ms", type=float, default=None)
    parser.add_argument("--av-drift-max-ms", type=float, default=None)
    args = parser.parse_args()
    payload = json.loads(Path(args.ffprobe_json).read_text(encoding="utf-8"))
    streams = payload.get("streams") or []
    codecs = {str(stream.get("codec_name")) for stream in streams}
    if not {"h264", "aac"}.issubset(codecs):
        raise SystemExit(f"expected h264+aac, got {sorted(codecs)}")
    for stream in streams:
        if stream.get("codec_type") in {"video", "audio"} and float(stream.get("duration") or 0) <= 0:
            raise SystemExit("media stream has no positive duration")

    # ffprobe emits packet timestamps as seconds.  The checks below are
    # intentionally optional so the existing lightweight smoke remains
    # useful, while the roadmap's stricter capture gate can opt in.
    # `ffprobe -show_packets -show_frames` uses the combined
    # `packets_and_frames` key on current releases.  Accept the older
    # separate `packets` shape as well so the checker works across images.
    packets = payload.get("packets") or [
        item for item in (payload.get("packets_and_frames") or [])
        if item.get("type") == "packet"
    ]
    by_type: dict[str, list[float]] = {"video": [], "audio": []}
    for packet in packets:
        kind = str(packet.get("codec_type") or "")
        if kind not in by_type:
            continue
        raw = packet.get("pts_time", packet.get("dts_time"))
        try:
            timestamp = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp):
            by_type[kind].append(timestamp)

    def max_gap_ms(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return max(0.0, max(b - a for a, b in zip(values, values[1:])) * 1000.0)

    for kind, limit in (("video", args.video_max_gap_ms), ("audio", args.audio_max_gap_ms)):
        values = by_type[kind]
        if any(later < earlier for earlier, later in zip(values, values[1:])):
            raise SystemExit(f"{kind} packet timestamps are not monotonic")
        if limit is None:
            continue
        if not values:
            raise SystemExit(f"no {kind} packet timestamps available")
        observed = max_gap_ms(values)
        if observed > limit:
            raise SystemExit(f"{kind} packet gap {observed:.1f}ms exceeds {limit:.1f}ms")

    if args.av_drift_p95_ms is not None or args.av_drift_max_ms is not None:
        video = by_type["video"]
        audio = by_type["audio"]
        if not video or not audio:
            raise SystemExit("audio/video packet timestamps are required for A/V drift")
        drifts = []
        audio_idx = 0
        for timestamp in video:
            while audio_idx + 1 < len(audio) and audio[audio_idx + 1] <= timestamp:
                audio_idx += 1
            drifts.append(abs(timestamp - audio[audio_idx]) * 1000.0)
        drifts.sort()
        p95 = drifts[min(len(drifts) - 1, max(0, math.ceil(len(drifts) * 0.95) - 1))]
        maximum = max(drifts)
        if args.av_drift_p95_ms is not None and p95 > args.av_drift_p95_ms:
            raise SystemExit(f"A/V drift P95 {p95:.1f}ms exceeds {args.av_drift_p95_ms:.1f}ms")
        if args.av_drift_max_ms is not None and maximum > args.av_drift_max_ms:
            raise SystemExit(f"A/V drift max {maximum:.1f}ms exceeds {args.av_drift_max_ms:.1f}ms")
    print("media timeline OK: h264 + aac")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
