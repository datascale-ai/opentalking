from __future__ import annotations

import httpx


async def forward_webrtc_offer(
    worker_base: str,
    session_id: str,
    sdp: str,
    type_: str,
) -> dict[str, str]:
    url = f"{worker_base.rstrip('/')}/webrtc/{session_id}/offer"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json={"sdp": sdp, "type": type_})
        r.raise_for_status()
        return r.json()


async def forward_worker_post_empty(worker_base: str, path: str) -> dict:
    url = f"{worker_base.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url)
        r.raise_for_status()
        return r.json()


async def forward_worker_json(
    worker_base: str,
    path: str,
    payload: dict,
    *,
    internal_token: str = "",
    method: str = "POST",
    idempotency_key: str | None = None,
) -> dict:
    url = f"{worker_base.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {internal_token}"} if internal_token else {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        response = await client.request(method, url, json=payload, headers=headers)
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()
