#!/usr/bin/env bash
set -euo pipefail

package_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

echo "QuickTalk package: $package_root"
test -f "$package_root/models/quicktalk/checkpoints/quicktalk.pth" && echo "quicktalk.pth: ok" || echo "quicktalk.pth: missing"
test -f "$package_root/models/quicktalk/checkpoints/repair.npy" && echo "repair.npy: ok" || echo "repair.npy: missing"
test -d "$package_root/models/quicktalk/checkpoints/chinese-hubert-large" && echo "HuBERT: ok" || echo "HuBERT: missing"
test -d "$package_root/models/quicktalk/checkpoints/auxiliary/models/buffalo_l" && echo "InsightFace buffalo_l: ok" || echo "InsightFace buffalo_l: missing"
