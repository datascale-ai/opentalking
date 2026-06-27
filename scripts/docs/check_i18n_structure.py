from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECK_DIRS = ("tutorials", "model-deployment", "docs", "benchmark", "community")


def files(locale: str) -> set[str]:
    base = ROOT / "docs" / locale
    found: set[str] = set()
    for directory in CHECK_DIRS:
        for path in (base / directory).rglob("*.md"):
            found.add(str(path.relative_to(base)))
    return found


def main() -> int:
    zh = files("zh")
    en = files("en")
    missing_en = sorted(zh - en)
    missing_zh = sorted(en - zh)

    if missing_en or missing_zh:
        if missing_en:
            print("Missing English pages:", file=sys.stderr)
            for path in missing_en:
                print(f"  {path}", file=sys.stderr)
        if missing_zh:
            print("Missing Chinese pages:", file=sys.stderr)
            for path in missing_zh:
                print(f"  {path}", file=sys.stderr)
        return 1

    print("Chinese and English doc structures match for active sections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
