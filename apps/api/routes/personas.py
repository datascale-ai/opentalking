from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from opentalking.agent.context_builder import default_knowledge_store
from opentalking.persona.package import export_persona_package, import_persona_package, validate_persona_package
from opentalking.persona.persona_md import read_persona_md, write_persona_md
from opentalking.persona.session import default_persona_store

router = APIRouter(prefix="/personas", tags=["personas"])


class PersonaAvatarResponse(BaseModel):
    id: str
    model: str
    path: str | None = None


class PersonaVoiceResponse(BaseModel):
    provider: str | None = None
    voice_id: str | None = None
    model: str | None = None


class PersonaAgentResponse(BaseModel):
    persona_prompt: str | None = None
    system_prompt: str | None = None
    style_prompt: str | None = None
    memory_enabled: bool = False
    knowledge_enabled: bool = True
    knowledge_base_ids: list[str] = []


class PersonaRuntimeResponse(BaseModel):
    stt_provider: str | None = None
    tts_provider: str | None = None
    preferred_backend: str | None = None


class PersonaSafetyResponse(BaseModel):
    authorized_avatar: bool = False
    authorized_voice: bool = False
    content_label_required: bool = True


class PersonaResponse(BaseModel):
    schema_version: str
    id: str
    name: str
    description: str
    locale: str
    avatar: PersonaAvatarResponse
    voice: PersonaVoiceResponse
    agent: PersonaAgentResponse
    runtime: PersonaRuntimeResponse
    safety: PersonaSafetyResponse
    created_at: str
    updated_at: str
    source: str = "local"


class PersonasResponse(BaseModel):
    personas: list[PersonaResponse]




class PersonaMdRequest(BaseModel):
    content: str


class PersonaMdResponse(BaseModel):
    persona_id: str
    content: str

class DeletePersonaResponse(BaseModel):
    deleted: bool


def _persona_response(record) -> PersonaResponse:
    payload = record.to_dict()
    return PersonaResponse(**payload)


@router.get("", response_model=PersonasResponse)
async def list_personas() -> PersonasResponse:
    records = default_persona_store().list_personas()
    return PersonasResponse(personas=[_persona_response(record) for record in records])


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: str) -> PersonaResponse:
    try:
        return _persona_response(default_persona_store().get_persona(persona_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="persona not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{persona_id}/persona-md", response_model=PersonaMdResponse)
async def get_persona_md(persona_id: str) -> PersonaMdResponse:
    try:
        record = default_persona_store().get_persona(persona_id)
        return PersonaMdResponse(persona_id=persona_id, content=read_persona_md(record))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="persona not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{persona_id}/persona-md", response_model=PersonaMdResponse)
async def update_persona_md(persona_id: str, body: PersonaMdRequest) -> PersonaMdResponse:
    try:
        record = default_persona_store().get_persona(persona_id)
        content = write_persona_md(record, body.content)
        return PersonaMdResponse(persona_id=persona_id, content=content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="persona not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import", response_model=PersonaResponse)
async def import_persona(file: UploadFile = File(...)) -> PersonaResponse:
    filename = file.filename or "persona.otpersona"
    suffix = Path(filename).suffix.lower()
    if suffix != ".otpersona" and suffix != ".zip":
        raise HTTPException(status_code=400, detail="persona package must be .otpersona or .zip")
    with tempfile.NamedTemporaryFile(prefix="opentalking-persona-", suffix=suffix, delete=True) as tmp:
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 200 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="persona package is larger than 200MB")
            tmp.write(chunk)
        tmp.flush()
        try:
            record = await import_persona_package(
                tmp.name,
                store=default_persona_store(),
                knowledge_store=default_knowledge_store(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _persona_response(record)


@router.post("/validate", response_model=PersonaResponse)
async def validate_persona(file: UploadFile = File(...)) -> PersonaResponse:
    with tempfile.NamedTemporaryFile(prefix="opentalking-persona-validate-", suffix=".otpersona", delete=True) as tmp:
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
        tmp.flush()
        try:
            manifest = validate_persona_package(tmp.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PersonaResponse(
        **{
            **asdict(manifest),
            "created_at": "",
            "updated_at": "",
            "source": "validated",
        }
    )


@router.get("/{persona_id}/export")
async def export_persona(persona_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"opentalking-{persona_id}-",
            suffix=".otpersona",
            delete=False,
        ) as tmp:
            out_path = Path(tmp.name)
        export_persona_package(persona_id, store=default_persona_store(), out_path=out_path)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="persona not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(out_path.unlink, missing_ok=True)
    return FileResponse(
        str(out_path),
        media_type="application/zip",
        filename=f"{persona_id}.otpersona",
    )


@router.delete("/{persona_id}", response_model=DeletePersonaResponse)
async def delete_persona(persona_id: str) -> DeletePersonaResponse:
    try:
        deleted = default_persona_store().delete_persona(persona_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="persona not found")
    return DeletePersonaResponse(deleted=True)
