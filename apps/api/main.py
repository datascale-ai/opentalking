from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.core.config import get_settings
from apps.api.routes import agent, avatars, events, exports, health, hls_proxy, memory, models, outputs, personas, rtmps_jobs, runtime_config, scene_assets, sessions, tts_preview, video_clone, video_creation, voices
from opentalking.voice.store import init_voice_store
from opentalking.video_creation_jobs import VideoCreationJobManager
from opentalking.streaming.rtmps_jobs import ChunkedRTMPSJobManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_voice_store()
    settings = get_settings()
    if (
        settings.streaming_enabled
        and not settings.streaming_test_auth_bypass
        and not settings.streaming_internal_control_token.strip()
    ):
        raise RuntimeError(
            "OPENTALKING_STREAMING_INTERNAL_CONTROL_TOKEN is required for split API/worker mode"
        )
    app.state.settings = settings
    app.state.video_creation_jobs = VideoCreationJobManager(settings)
    app.state.rtmps_video_jobs = ChunkedRTMPSJobManager(settings, app.state.video_creation_jobs)
    app.state.worker_boot_id = uuid.uuid4().hex
    r = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.redis = r
    yield
    await app.state.rtmps_video_jobs.close()
    await app.state.video_creation_jobs.close()
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
    app.include_router(memory.router)
    app.include_router(sessions.router)
    app.include_router(outputs.router)
    app.include_router(agent.router)
    app.include_router(agent.router, prefix="/api")
    app.include_router(personas.router)
    app.include_router(events.router)
    app.include_router(exports.router)
    app.include_router(scene_assets.router)
    app.include_router(runtime_config.router)
    app.include_router(tts_preview.router)
    app.include_router(video_clone.router)
    app.include_router(video_creation.router)
    app.include_router(rtmps_jobs.router)
    app.include_router(hls_proxy.router)
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
