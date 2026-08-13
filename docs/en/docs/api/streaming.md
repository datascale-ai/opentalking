# Streaming outputs

OpenTalking can copy a running real-time digital-human session to external ingest endpoints. RTMPS is intended for live-platform or RTMP ingest, while WHIP is intended for WebRTC ingest. Both carry media only; `speak`, `interrupt`, and other controls remain OpenTalking HTTP API calls.

The feature is disabled by default. When enabled, output APIs require:

```text
Authorization: Bearer $OPENTALKING_STREAMING_CONTROL_TOKEN
```

The local test profile may explicitly enable `OPENTALKING_STREAMING_ALLOW_LOCAL_TARGETS=1` and the test bypass. Do not enable those switches in production.

## Start the local ingest

The repository includes a pinned MediaMTX harness. Test credentials, short-lived certificates, and the rendered config are written only below the gitignored `outputs/streaming` directory:

```bash
cd /path/to/opentalking
bash scripts/streaming/generate_test_pki.sh outputs/streaming/tls
.venv/bin/python scripts/streaming/prepare_mediamtx_harness.py
docker compose -f docker/docker-compose.streaming-test.yml up -d
set -a; . outputs/streaming/credentials.env; set +a
```

If you are reusing the current harness credentials, do not run `prepare_mediamtx_harness.py` again; it rotates the credentials. Run it only when you intentionally rotate them, then reload the generated `credentials.env`.

The local harness uses Linux `network_mode: host` and binds every enabled listener to `127.0.0.1`. This lets an ordinary Chromium browser reach the local ICE candidate directly; it is intended for a browser running on the same Linux host as MediaMTX. A remote browser cannot use the `127.0.0.1` endpoints below.

Local endpoints:

| Purpose | Endpoint |
| --- | --- |
| RTMPS publish | `rtmps://127.0.0.1:1936/live`, stream key `rtmps-test` |
| WHIP publish | `https://127.0.0.1:8889/whip-test/whip` |
| RTMPS playback | `rtsp://127.0.0.1:8554/live/rtmps-test` (reader credentials come from harness environment variables) |
| WHIP playback | `https://127.0.0.1:8889/whip-test/whep` |

For local WHEP, port `8889` carries signaling only; browser media also needs the harness-mapped `8189/udp` and `8190/tcp` ICE ports. The harness advertises only `127.0.0.1` to avoid Docker-internal candidates. Use `reader:<OPENTALKING_HARNESS_READ_PASSWORD>` as the receiver Bearer token, not the publishing `OPENTALKING_HARNESS_WHIP_TOKEN`.

MediaMTX 1.20 does not transcode AAC from an RTMPS input into WebRTC audio; use `/live/rtmps-test/whep` to verify video and the RTSP playback URL above for complete RTMPS A/V. The WHIP `/whip-test/whep` path verifies H.264 + Opus audio/video.

The local certificate is signed by the test CA. OpenTalking verifies it through `OPENTALKING_STREAMING_RTMPS_CA_FILE` and `OPENTALKING_STREAMING_WHIP_CA_FILE`; disabling TLS verification is not the normal test path.

## Create outputs

Create and start a Session first, and wait for `/start` to return ready:

```bash
BASE=http://127.0.0.1:8210
SID=$(curl -sS -X POST "$BASE/sessions" \
  -H 'Content-Type: application/json' \
  --data '{"avatar_id":"anchor","model":"mock","tts_provider":"mock","stt_provider":"funasr"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
curl -sS -X POST "$BASE/sessions/$SID/start"
```

Secrets must use structured fields and must not be embedded in endpoints:

```bash
curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/outputs" \
  -H "Authorization: Bearer ${OPENTALKING_STREAMING_CONTROL_TOKEN:-}" \
  -H "Idempotency-Key: local-rtmps-001" \
  -H 'Content-Type: application/json' \
  --data '{
    "type":"rtmps",
    "name":"local RTMPS",
    "auto_connect":true,
    "transport":{
      "endpoint":"rtmps://127.0.0.1:1936/live",
      "stream_key":"rtmps-test",
      "username":"publisher",
      "password":"'"$OPENTALKING_HARNESS_RTMPS_PASSWORD"'"
    }
  }'

curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/outputs" \
  -H "Authorization: Bearer ${OPENTALKING_STREAMING_CONTROL_TOKEN:-}" \
  -H "Idempotency-Key: local-whip-001" \
  -H 'Content-Type: application/json' \
  --data '{
    "type":"whip",
    "name":"local WHIP",
    "auto_connect":true,
    "transport":{
      "endpoint":"https://127.0.0.1:8889/whip-test/whip",
      "bearer_token":"'"$OPENTALKING_HARNESS_WHIP_TOKEN"'"
    }
  }'
```

Create returns `201`, connect/disconnect/reconnect return `202`, GET returns a secret-free snapshot, and delete returns `204`. Reusing the same idempotency key and payload does not create another output; changing the payload with the same key is rejected.

## Send and receive media

```bash
curl --fail-with-body -sS -X POST "$BASE/sessions/$SID/speak" \
  -H 'Content-Type: application/json' \
  --data '{"text":"Welcome to OpenTalking","mode":"replace","command_id":"demo-say-001","tts_provider":"mock"}'

.venv/bin/python scripts/streaming/receive_rtmps.py \
  --url "rtsp://127.0.0.1:8554/live/rtmps-test" \
  --output outputs/streaming/rtmps-capture.mp4 --seconds 30

.venv/bin/python scripts/streaming/receive_whep.py \
  --url https://127.0.0.1:8889/whip-test/whep \
  --ca-file outputs/streaming/tls/ca.crt \
  --output outputs/streaming/whip-capture.mkv \
  --stats outputs/streaming/whip-stats.json \
  --answer-sdp outputs/streaming/whip-answer.sdp --seconds 30
```

RTMPS capture should contain H.264 + AAC. WHEP stats should contain video and audio frames; use the answer SDP to check the H.264 + Opus wire codecs:

```bash
ffprobe -v error -show_streams -show_packets -show_frames -of json \
  outputs/streaming/rtmps-capture.mp4 > outputs/streaming/rtmps-capture.ffprobe.json
.venv/bin/python scripts/streaming/assert_media_timeline.py \
  --ffprobe-json outputs/streaming/rtmps-capture.ffprobe.json \
  --video-max-gap-ms 120 --audio-max-gap-ms 60 \
  --av-drift-p95-ms 100 --av-drift-max-ms 250
.venv/bin/python scripts/streaming/assert_whep_stats.py \
  --stats outputs/streaming/whip-stats.json \
  --sdp outputs/streaming/whip-answer.sdp
```

## Studio streaming page

After starting `scripts/start_unified.sh`, open the “流媒体” (Streaming) module in the WebUI. Start a real-time conversation, then create RTMPS/WHIP outputs, inspect health, connect/disconnect/reconnect/delete outputs, and use the browser WHEP player to receive the MediaMTX stream. Publish passwords and bearer tokens are used only for the request and are never shown in output status cards or browser localStorage; the receiver token may be left blank for a WHEP service that does not require authentication.

## Stop the harness

```bash
docker compose -f docker/docker-compose.streaming-test.yml down -v
```

The receiver scripts read temporary credentials from `OPENTALKING_HARNESS_READ_USERNAME`, `OPENTALKING_HARNESS_READ_PASSWORD`, and `OPENTALKING_HARNESS_WHEP_TOKEN`; do not embed credentials in URLs or command lines. Test credentials, private keys, captures, and `.env` files must not be committed.
