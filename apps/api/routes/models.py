from __future__ import annotations

from fastapi import APIRouter, Request

from opentalking.providers.synthesis import SYNTHESIS_PROVIDERS
from opentalking.providers.synthesis.availability import resolve_model_statuses

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
async def list_registered_models(
    request: Request,
) -> dict[str, list[dict[str, str | bool]] | list[str] | str | None]:
    statuses = await resolve_model_statuses(request.app.state.settings)
    default_model = (getattr(request.app.state.settings, "default_model", "") or "").strip().lower()
    if default_model not in SYNTHESIS_PROVIDERS:
        default_model = None
    return {
        "models": [status.id for status in statuses],
        "statuses": [status.to_dict() for status in statuses],
        "default_model": default_model,
    }
