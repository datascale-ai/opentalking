"""音色目录（SQLite）与百炼声音复刻。"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from opentalking.voices import bailian_clone
from opentalking.voices.store import delete_entry, get_entry, init_voice_store, insert_clone, list_voices

log = logging.getLogger(__name__)

router = APIRouter(tags=["voices"])

_UPLOAD_DIR = Path("data/voice_uploads")


def _upload_dir() -> Path:
    d = _UPLOAD_DIR.resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _public_base(request: Request) -> str:
    try:
        from opentalking.core.config import get_settings

        raw = (get_settings().public_base_url or "").strip()
    except Exception:
        raw = ""
    if raw:
        return raw.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/voices", response_model=None)
async def get_voices(provider: str | None = None) -> JSONResponse:
    init_voice_store()
    p = provider.strip().lower() if provider else None
    rows = list_voices(provider=p)
    items = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "provider": r.provider,
            "voice_id": r.voice_id,
            "display_label": r.display_label,
            "target_model": r.target_model,
            "source": r.source,
        }
        for r in rows
    ]
    return JSONResponse({"items": items})


@router.get("/voice-uploads/{token}")
async def serve_voice_upload(token: str) -> FileResponse:
    """供百炼服务端拉取 CosyVoice 复刻用音频（须公网可达）。"""
    safe = re.sub(r"[^a-f0-9]", "", token.lower())
    if len(safe) != 32:
        raise HTTPException(status_code=404, detail="invalid token")
    path = _upload_dir() / f"{safe}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="sample not found")
    return FileResponse(path, media_type="audio/wav", filename=f"{safe}.wav")


@router.post("/voices/clone", response_model=None)
async def post_voice_clone(
    request: Request,
    background_tasks: BackgroundTasks,
    provider: str = Form(..., description="cosyvoice 或 dashscope（千问复刻）"),
    target_model: str = Form(...),
    display_label: str = Form(...),
    audio: UploadFile = File(...),
    prefix: str = Form(""),
    preferred_name: str = Form(""),
) -> JSONResponse:
    """
    上传一段朗读音频完成复刻。
    - CosyVoice：需要本服务地址对公网可达（或配置 OPENTALKING_PUBLIC_BASE_URL）。
    - 千问（dashscope）：使用 base64，无需公网 URL。
    """
    init_voice_store()
    prov = provider.strip().lower()
    if prov not in {"cosyvoice", "dashscope"}:
        raise HTTPException(status_code=400, detail="provider 须为 cosyvoice 或 dashscope")

    raw = await audio.read()
    if len(raw) < 256:
        raise HTTPException(status_code=400, detail="音频过短")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频文件过大（>12MB）")

    suffix = Path(audio.filename or "upload.bin").suffix.lower() or ".webm"
    try:
        wav = bailian_clone.convert_audio_to_wav_24k_mono(raw, suffix)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    label = (display_label or "").strip() or "我的复刻音色"
    tm = (target_model or "").strip()

    try:
        if prov == "cosyvoice":
            token = uuid.uuid4().hex
            up = _upload_dir() / f"{token}.wav"
            up.write_bytes(wav)
            base = _public_base(request)
            public_url = f"{base}/voice-uploads/{token}"
            pf = (prefix or "").strip().lower() or f"c{token[:6]}"
            try:
                vid = bailian_clone.clone_cosyvoice_voice(
                    target_model=tm,
                    prefix=pf,
                    public_audio_url=public_url,
                )
            except Exception as e:
                up.unlink(missing_ok=True)
                raise HTTPException(status_code=502, detail=f"CosyVoice 复刻失败: {e}") from e

            eid = insert_clone(
                provider="cosyvoice",
                voice_id=vid,
                display_label=label,
                target_model=tm,
            )

            async def _remove_upload_after_delay(p: Path, seconds: float = 300.0) -> None:
                await asyncio.sleep(seconds)
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

            background_tasks.add_task(_remove_upload_after_delay, up)
            return JSONResponse(
                {
                    "ok": True,
                    "entry_id": eid,
                    "voice_id": vid,
                    "provider": "cosyvoice",
                    "target_model": tm,
                    "message": "CosyVoice 复刻成功，请在合成时选择相同 CosyVoice 模型。",
                }
            )

        # 千问声音复刻（与实时 qwen3-tts-flash-realtime 不同系，请选文档中的 VC / 复刻专用模型）
        pref = (preferred_name or "").strip().lower() or f"u{uuid.uuid4().hex[:8]}"
        try:
            vid = bailian_clone.clone_qwen_voice(
                wav_bytes=wav,
                target_model=tm,
                preferred_name=pref,
                audio_mime="audio/wav",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        eid = insert_clone(
            provider="dashscope",
            voice_id=vid,
            display_label=label,
            target_model=tm,
        )
        return JSONResponse(
            {
                "ok": True,
                "entry_id": eid,
                "voice_id": vid,
                "provider": "dashscope",
                "target_model": tm,
                "message": "千问复刻成功：合成时请选用与复刻相同的 target_model。",
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.delete("/voices/{entry_id}", response_model=None)
async def delete_voice_entry(entry_id: int) -> JSONResponse:
    init_voice_store()
    row = get_entry(entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    if row.get("source") != "clone":
        raise HTTPException(status_code=400, detail="不能删除系统预设音色")
    if delete_entry(entry_id):
        return JSONResponse({"ok": True})
    raise HTTPException(status_code=404, detail="not found")
