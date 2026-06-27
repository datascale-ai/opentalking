from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

sys.path.insert(0, str(ROOT))

from apps.api.main import create_app


def openapi_routes() -> set[tuple[str, str]]:
    spec = create_app().openapi()
    routes: set[tuple[str, str]] = set()
    for path, methods in spec["paths"].items():
        for method in methods:
            upper = method.upper()
            if upper in HTTP_METHODS:
                routes.add((upper, path))
    return routes


def documented_routes(path: Path) -> set[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    routes: set[tuple[str, str]] = set()
    for match in re.finditer(r"\|\s*`(?P<method>[A-Z]+)`\s*\|\s*`(?P<path>/[^`]+)`\s*\|", text):
        method = match.group("method")
        if method in HTTP_METHODS:
            routes.add((method, match.group("path")))
    return routes


def main() -> int:
    expected = openapi_routes()
    failures: list[str] = []
    for rel in ("docs/zh/docs/api/index.md", "docs/en/docs/api/index.md"):
        doc = ROOT / rel
        found = documented_routes(doc)
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        if missing or extra:
            failures.append(f"{rel}:")
            if missing:
                failures.append("  Missing from docs:")
                failures.extend(f"    {method} {path}" for method, path in missing)
            if extra:
                failures.append("  Extra in docs:")
                failures.extend(f"    {method} {path}" for method, path in extra)

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("API docs match FastAPI OpenAPI routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
