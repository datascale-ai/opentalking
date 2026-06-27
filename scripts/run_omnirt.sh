#!/usr/bin/env bash
# Start a standalone omnirt container, independent of the OpenTalking compose
# stack. Useful when you want OpenTalking running natively (Python venv) but
# still need a local inference backend.
#
# Usage:
#   bash scripts/run_omnirt.sh                  # CUDA, port 9000
#   OMNIRT_PORT=9100 bash scripts/run_omnirt.sh
#   OMNIRT_BACKEND=ascend bash scripts/run_omnirt.sh
#
# To stop: docker stop opentalking-omnirt
set -euo pipefail

backend=${OMNIRT_BACKEND:-cuda}
port=${OMNIRT_PORT:-9000}
name=${OMNIRT_CONTAINER_NAME:-opentalking-omnirt}
image=${OMNIRT_IMAGE:-ghcr.io/datascale-ai/omnirt:${backend}-latest}

echo "Starting omnirt"
echo "  backend: $backend"
echo "  image:   $image"
echo "  port:    $port"
echo "  name:    $name"

docker rm -f "$name" >/dev/null 2>&1 || true

gpu_flag=""
case "$backend" in
  cuda)   gpu_flag="--gpus all" ;;
  ascend) gpu_flag="--device /dev/davinci0 --device /dev/davinci_manager --device /dev/hisi_hdc" ;;
  cpu)    gpu_flag="" ;;
  *)      echo "unknown backend: $backend"; exit 2 ;;
esac

docker run -d --name "$name" $gpu_flag \
  -p "$port:9000" \
  "$image"

echo ""
echo "Waiting for omnirt /health (up to 60s) ..."
for _ in {1..30}; do
  if curl -fsS "http://localhost:$port/health" >/dev/null 2>&1; then
    echo "✅ omnirt is up at http://localhost:$port"
    echo ""
    echo "Point OpenTalking at it:"
    echo "  echo 'OMNIRT_ENDPOINT=http://localhost:$port' >> .env"
    exit 0
  fi
  sleep 2
done
echo "❌ omnirt did not become healthy in 60s. Inspect:"
echo "  docker logs $name"
exit 1
