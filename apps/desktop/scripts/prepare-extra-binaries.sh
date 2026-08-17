#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
work="${root}/.binary-work"
src="${work}/share-binary"
dst="${root}/resources/extra"

repo="${OPENTALKING_SHARE_BINARY_REPO:-https://github.com/modstart-lib/share-binary}"

mkdir -p "$work" "$dst"
if [[ ! -d "$src/.git" ]]; then
  git clone "$repo" "$src"
else
  git -C "$src" pull --ff-only
fi

copy_bin() {
  local from="$1"
  local to_dir="$2"
  local name="$3"
  mkdir -p "$dst/$to_dir"
  cp -a "$src/$from/$name" "$dst/$to_dir/$name"
}

copy_bin osx-arm64 mac-arm64 ffmpeg
copy_bin osx-arm64 mac-arm64 ffprobe
copy_bin osx-x86 mac-x64 ffmpeg
copy_bin osx-x86 mac-x64 ffprobe
copy_bin linux-x86 linux-x64 ffmpeg
copy_bin linux-x86 linux-x64 ffprobe
copy_bin linux-arm64 linux-arm64 ffmpeg
copy_bin linux-arm64 linux-arm64 ffprobe
copy_bin win-x86 win-x64 ffmpeg.exe
copy_bin win-x86 win-x64 ffprobe.exe

find "$dst" -maxdepth 2 -type f | sort
