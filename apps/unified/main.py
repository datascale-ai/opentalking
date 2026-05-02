"""
Single-process entry: FastAPI serves REST + SSE; worker task queue runs in-process.

Similar UX to LiveTalking's ``python app.py`` (one HTTP port, no external Redis).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import opentalking.models  # noqa: F401
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.core.config import get_settings
from apps.api.routes import avatars, events, health, models, sessions, voices
from opentalking.voices.store import init_voice_store
from opentalking.core.in_memory_redis import InMemoryRedis
from opentalking.worker.session_runner import SessionRunner
from opentalking.worker.task_consumer import consume_task_queue

log = logging.getLogger(__name__)


def _verify_offline_bundle_route_registered(app: FastAPI) -> None:
    """若缺失则 404 为 Starlette 默认 ``Not Found``（非 session not found），多为装了旧版包。"""
    log.info("apps.api.routes.sessions loaded from: %s", sessions.__file__)
    hits: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None) or ""
        if "flashtalk-offline-bundle" not in path:
            continue
        methods = sorted(getattr(route, "methods", None) or [])
        hits.append(f"{'|'.join(methods)} {path}")
    if hits:
        log.info("flashtalk-offline-bundle routes: %s", " ; ".join(hits))
    else:
        log.error(
            "未注册 flashtalk-offline-bundle：POST 会得到 404 {\"detail\":\"Not Found\"}。"
            "请在仓库根对当前环境执行: pip install -e . "
            "并确认启动前 cd 到含新代码的目录；勿使用未含该路由的旧 site-packages。"
        )


def _unified_uvicorn_workers() -> int:
    """Unified 的会话、任务队列、SessionRunner 均在单进程内存；多 worker 会导致随机 404 等故障。"""
    raw = os.environ.get("OPENTALKING_UNIFIED_UVICORN_WORKERS", "1").strip()
    try:
        n = int(raw)
    except ValueError:
        log.warning("Invalid OPENTALKING_UNIFIED_UVICORN_WORKERS=%r, using 1", raw)
        return 1
    if n != 1:
        log.error(
            "OPENTALKING_UNIFIED_UVICORN_WORKERS=%s is unsupported: session + worker share one process. "
            "Forcing 1. If you used `uvicorn ... --workers N`, remove it or use split API+worker with Redis.",
            n,
        )
        return 1
    return 1


@asynccontextmanager
async def unified_lifespan(app: FastAPI):
    init_voice_store()
    settings = get_settings()
    app.state.settings = settings
    log.info(
        "Unified: single HTTP worker required (in-memory session + task queue + runners). "
        "Do not use gunicorn/uvicorn --workers>1; do not load-balance multiple unified instances without sticky routing."
    )
    mem = InMemoryRedis()
    app.state.redis = mem
    runners: dict[str, SessionRunner] = {}
    app.state.session_runners = runners
    avatars_root = Path(
        os.environ.get("OPENTALKING_AVATARS_DIR", "./examples/avatars")
    ).resolve()
    device = os.environ.get("OPENTALKING_TORCH_DEVICE", "cpu")
    consumer = asyncio.create_task(
        consume_task_queue(mem, avatars_root, device, runners)
    )
    log.info(
        "OpenTalking unified mode: in-memory broker, avatars=%s device=%s",
        avatars_root,
        device,
    )
    yield
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    for s in list(runners.values()):
        await s.close()
    runners.clear()
    await mem.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="OpenTalking Unified",
        description="API + worker in one process (no Redis)",
        lifespan=unified_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(avatars.router)
    app.include_router(sessions.router)
    app.include_router(events.router)
    app.include_router(voices.router)
    _verify_offline_bundle_route_registered(app)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="OpenTalking single-process server")
    parser.add_argument("--host", default=os.environ.get("OPENTALKING_UNIFIED_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OPENTALKING_UNIFIED_PORT", "8000")),
    )
    args = parser.parse_args()
    workers = _unified_uvicorn_workers()
    uvicorn.run(
        "apps.unified.main:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        workers=workers,
    )


if __name__ == "__main__":
    main()
