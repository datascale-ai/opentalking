from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/queue/status")
async def queue_status() -> dict:
    try:
        from opentalking.worker.task_consumer import slot_is_occupied, slot_queue_size
        return {
            "slot_occupied": slot_is_occupied(),
            "queue_size": slot_queue_size(),
        }
    except Exception:
        return {"slot_occupied": False, "queue_size": 0}
