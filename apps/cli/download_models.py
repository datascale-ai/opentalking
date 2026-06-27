from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from collections.abc import Sequence


DOWNLOADS = {
    "flashtalk_hf": {
        "label": "SoulX-FlashTalk-14B (HuggingFace)",
        "cmd": [
            "huggingface-cli",
            "download",
            "SoulX/FlashTalk-14B",
            "--local-dir",
            "models/SoulX-FlashTalk-14B",
        ],
    },
    "flashtalk_ms": {
        "label": "SoulX-FlashTalk-14B (ModelScope)",
        "cmd": [
            "modelscope",
            "download",
            "--model",
            "SoulX/FlashTalk-14B",
            "--local_dir",
            "models/SoulX-FlashTalk-14B",
        ],
    },
    "wav2vec_hf": {
        "label": "chinese-wav2vec2-base",
        "cmd": [
            "huggingface-cli",
            "download",
            "TencentGameMate/chinese-wav2vec2-base",
            "--local-dir",
            "models/chinese-wav2vec2-base",
        ],
    },
}


def _run(cmd: Sequence[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive OpenTalking model downloader")
    parser.add_argument(
        "--choice",
        choices=["flashtalk_hf", "flashtalk_ms", "wav2vec_hf", "all"],
        help="Skip the prompt and download the selected model set.",
    )
    args = parser.parse_args()

    Path("models").mkdir(exist_ok=True)
    choice = args.choice
    if not choice:
        print("Select models to download:")
        print("1. SoulX-FlashTalk-14B (HuggingFace)")
        print("2. SoulX-FlashTalk-14B (ModelScope)")
        print("3. chinese-wav2vec2-base")
        print("4. all")
        selection = input("> ").strip()
        choice = {
            "1": "flashtalk_hf",
            "2": "flashtalk_ms",
            "3": "wav2vec_hf",
            "4": "all",
        }.get(selection, "")
    if choice == "all":
        for item in ("flashtalk_hf", "wav2vec_hf"):
            print(f"Downloading {DOWNLOADS[item]['label']}...")
            _run(DOWNLOADS[item]["cmd"])
        return
    if choice not in DOWNLOADS:
        raise SystemExit("No valid download choice selected.")
    print(f"Downloading {DOWNLOADS[choice]['label']}...")
    _run(DOWNLOADS[choice]["cmd"])


if __name__ == "__main__":
    main()
