#!/usr/bin/env bash
set -euo pipefail

OUT="${1:-outputs/streaming/tls}"
mkdir -p "$OUT"
chmod 700 "$OUT"
umask 077
PUBLIC_IP="${OPENTALKING_STREAMING_PUBLIC_IP:-}"
SAN="DNS:localhost,IP:127.0.0.1"
if [[ -n "$PUBLIC_IP" ]]; then
  SAN="$SAN,IP:$PUBLIC_IP"
fi

openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -keyout "$OUT/ca.key" -out "$OUT/ca.crt" \
  -subj "/CN=OpenTalking streaming test CA" >/dev/null 2>&1
cat >"$OUT/server.ext" <<EOF
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$SAN
EOF
openssl req -newkey rsa:2048 -nodes \
  -keyout "$OUT/server.key" -out "$OUT/server.csr" \
  -subj "/CN=localhost" >/dev/null 2>&1
openssl x509 -req -days 2 -in "$OUT/server.csr" \
  -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial \
  -out "$OUT/server.crt" -extfile "$OUT/server.ext" >/dev/null 2>&1
rm -f "$OUT/server.csr" "$OUT/server.ext" "$OUT/ca.srl"
chmod 600 "$OUT"/*.key
chmod 644 "$OUT"/*.crt
echo "Generated short-lived test PKI in $OUT (private keys are local only)."
