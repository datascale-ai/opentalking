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


@asynccontextmanager
async def unified_lifespan(app: FastAPI):
    init_voice_store()
    settings = get_settings()
    app.state.settings = settings
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
    uvicorn.run(
        "apps.unified.main:create_app",
        host=args.host,
        port=args.port,
        factory=True,
    )


if __name__ == "__main__":
    main()
