"""opentalking-doctor — environment health check.

Run this when something is not working. It walks through the things OpenTalking
needs and prints a checklist with concrete fix hints, so users do not have to
guess between "missing dep", "wrong env", "service down", etc.

Usage:
    opentalking-doctor
    opentalking-doctor --json    # machine-readable output

Exit code: 0 if everything OK, 1 if any required check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib import request as urlrequest
from urllib.error import URLError

OK = "✅"
WARN = "⚠️ "
FAIL = "❌"


def _load_dotenv(path: Path = Path(".env")) -> int:
    """Minimal .env loader (no extra deps).

    Lines look like KEY=value or KEY="value with spaces". Comments start with
    '#'. Existing os.environ values win, so callers can still override via
    `KEY=foo opentalking-doctor`. Returns the number of vars loaded.
    """
    if not path.is_file():
        return 0
    loaded = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip optional surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Strip inline trailing comment after unquoted value
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


@dataclass
class CheckResult:
    name: str
    status: str  # ok | warn | fail
    detail: str
    hint: str | None = None


def _check_python() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        return CheckResult(
            "python",
            "fail",
            f"Python {major}.{minor} (need ≥ 3.10)",
            "Install Python 3.10+ or activate the right venv (`source .venv/bin/activate`).",
        )
    return CheckResult("python", "ok", f"Python {major}.{minor}")


def _check_ffmpeg() -> CheckResult:
    binary = os.environ.get("OPENTALKING_FFMPEG_BIN", "ffmpeg")
    path = shutil.which(binary)
    if path:
        return CheckResult("ffmpeg", "ok", path)
    return CheckResult(
        "ffmpeg",
        "fail",
        f"`{binary}` not found in PATH",
        "Install ffmpeg (macOS: `brew install ffmpeg`, Ubuntu: `apt install ffmpeg`).",
    )


def _check_imports() -> CheckResult:
    try:
        import opentalking  # noqa: F401
    except ImportError as exc:
        return CheckResult(
            "opentalking package",
            "fail",
            str(exc),
            "Run `pip install -e .` (or `uv sync --extra dev`) inside the repo.",
        )
    return CheckResult("opentalking package", "ok", "importable")


def _check_env_file() -> CheckResult:
    if os.path.isfile(".env"):
        return CheckResult(".env file", "ok", "./.env present")
    return CheckResult(
        ".env file",
        "warn",
        "./.env missing",
        "Run `cp .env.example .env` and fill in OPENTALKING_LLM_API_KEY at minimum.",
    )


def _check_llm_key() -> CheckResult:
    key = os.environ.get("OPENTALKING_LLM_API_KEY")
    if not key:
        return CheckResult(
            "LLM API key",
            "warn",
            "OPENTALKING_LLM_API_KEY is not set",
            "Set OPENTALKING_LLM_API_KEY in .env for the configured OpenAI-compatible endpoint.",
        )
    masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
    return CheckResult("LLM API key", "ok", f"set ({masked})")


def _check_omnirt() -> CheckResult:
    endpoint = os.environ.get("OMNIRT_ENDPOINT", "").strip()
    legacy_ws = os.environ.get("OPENTALKING_FLASHTALK_WS_URL", "").strip()
    if not endpoint and not legacy_ws:
        return CheckResult(
            "synthesis backend",
            "ok",
            "no OMNIRT_ENDPOINT / FlashTalk WS configured "
            "(only model=mock will work; pick a real backend for flashtalk/musetalk/wav2lip)",
        )
    if legacy_ws and not endpoint:
        return CheckResult(
            "synthesis backend",
            "ok",
            f"FlashTalk WS direct: {legacy_ws}",
        )
    try:
        with urlrequest.urlopen(f"{endpoint.rstrip('/')}/health", timeout=3) as resp:
            if 200 <= resp.status < 300:
                return CheckResult("omnirt", "ok", f"{endpoint} healthy")
            return CheckResult(
                "omnirt",
                "fail",
                f"{endpoint}/health returned HTTP {resp.status}",
                "Check omnirt logs (`docker logs opentalking-omnirt` if you used run_omnirt.sh).",
            )
    except URLError as exc:
        return CheckResult(
            "omnirt",
            "fail",
            f"{endpoint} unreachable: {exc.reason}",
            "Start omnirt locally (`bash scripts/run_omnirt.sh`) "
            "or fix OMNIRT_ENDPOINT in .env.",
        )


def _check_redis() -> CheckResult:
    mode = os.environ.get("OPENTALKING_REDIS_MODE", "redis").lower()
    if mode == "memory":
        return CheckResult("redis", "ok", "OPENTALKING_REDIS_MODE=memory (single-process)")
    url = os.environ.get("OPENTALKING_REDIS_URL", "redis://localhost:6379/0")
    host, port = _parse_redis_url(url)
    try:
        with socket.create_connection((host, port), timeout=2):
            return CheckResult("redis", "ok", f"{host}:{port} reachable")
    except OSError as exc:
        return CheckResult(
            "redis",
            "fail",
            f"{host}:{port} unreachable: {exc}",
            "Start redis (`docker run -d -p 6379:6379 redis:7-alpine`) "
            "or use OPENTALKING_REDIS_MODE=memory for single-process dev.",
        )


def _parse_redis_url(url: str) -> tuple[str, int]:
    # Minimal parser, no auth / db handling
    rest = url.split("://", 1)[-1]
    host_port = rest.split("/", 1)[0]
    if ":" in host_port:
        host, port = host_port.split(":", 1)
        return host, int(port)
    return host_port, 6379


def _check_ports() -> CheckResult:
    api_port = int(os.environ.get("OPENTALKING_API_PORT", "8000"))
    web_port = int(os.environ.get("OPENTALKING_WEB_PORT", "5173"))
    busy = []
    for label, port in [("API", api_port), ("web", web_port)]:
        if _port_in_use(port):
            busy.append(f"{label}:{port}")
    if busy:
        return CheckResult(
            "ports",
            "warn",
            "in use: " + ", ".join(busy),
            "Stop existing services or change OPENTALKING_API_PORT / OPENTALKING_WEB_PORT.",
        )
    return CheckResult("ports", "ok", f"API:{api_port} / web:{web_port} free")


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


CHECKS: list[Callable[[], CheckResult]] = [
    _check_python,
    _check_imports,
    _check_ffmpeg,
    _check_env_file,
    _check_llm_key,
    _check_omnirt,
    _check_redis,
    _check_ports,
]


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenTalking environment doctor")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to a .env file to read (default: ./.env). Pass empty string to skip.",
    )
    args = parser.parse_args()

    if args.env_file:
        _load_dotenv(Path(args.env_file))

    results = [check() for check in CHECKS]

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        _print_text(results)

    has_fail = any(r.status == "fail" for r in results)
    return 1 if has_fail else 0


def _print_text(results: list[CheckResult]) -> None:
    print()
    print("OpenTalking environment doctor")
    print("=" * 32)
    for r in results:
        icon = {"ok": OK, "warn": WARN, "fail": FAIL}[r.status]
        print(f"{icon}  {r.name:24} {r.detail}")
        if r.hint and r.status != "ok":
            print(f"        → {r.hint}")
    print()
    n_fail = sum(1 for r in results if r.status == "fail")
    n_warn = sum(1 for r in results if r.status == "warn")
    if n_fail:
        print(f"{FAIL} {n_fail} blocking issue(s) — fix the items above before starting OpenTalking.")
    elif n_warn:
        print(f"{WARN} {n_warn} warning(s) — OpenTalking should still start, but features may be limited.")
    else:
        print(f"{OK} All checks passed. You can start OpenTalking now.")
    print()


if __name__ == "__main__":
    sys.exit(main())
