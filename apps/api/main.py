from __future__ import annotations

import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import get_settings
from apps.api.routes import avatars, events, health, models, sessions, voices
from opentalking.voices.store import init_voice_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_voice_store()
    settings = get_settings()
    app.state.settings = settings
    r = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = r
    yield
    await r.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="OpenTalking API", lifespan=lifespan)
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
    settings = get_settings()
    host = os.environ.get("OPENTALKING_API_HOST", settings.api_host)
    port = int(os.environ.get("OPENTALKING_API_PORT", str(settings.api_port)))
    uvicorn.run(
        "apps.api.main:create_app",
        host=host,
        port=port,
        factory=True,
    )


if __name__ == "__main__":
    main()
