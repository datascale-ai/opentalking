from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentalking.persona.memory_builder import (
    WeChatPersonaDraft,
    build_wechat_persona_draft,
    build_wechat_persona_draft_async,
)
from opentalking.persona.schema import (
    PERSONA_SCHEMA_VERSION,
    PersonaAgent,
    PersonaAvatar,
    PersonaManifest,
    PersonaRuntime,
    PersonaSafety,
    write_persona_manifest,
)
from opentalking.persona.store import PersonaRecord, PersonaStore
from opentalking.persona.weflow_parser import WeFlowExport, WeFlowSpeaker, parse_weflow_export
from opentalking.providers.memory.base import MemoryProvider
from opentalking.providers.memory.import_jobs import ImportJobStatus, MemoryImportCommitResult
from opentalking.providers.memory.schemas import utc_now_iso


@dataclass
class WeChatImportJob:
    id: str
    status: ImportJobStatus
    export: WeFlowExport
    speakers: list[WeFlowSpeaker]
    profile_id: str
    memory_library_id: str
    avatar_id: str
    avatar_model: str
    character_id: str
    selected_speaker_id: str | None = None
    draft: WeChatPersonaDraft | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "speakers": [speaker.__dict__ for speaker in self.speakers],
            "profile_id": self.profile_id,
            "memory_library_id": self.memory_library_id,
            "avatar_id": self.avatar_id,
            "avatar_model": self.avatar_model,
            "character_id": self.character_id,
            "selected_speaker_id": self.selected_speaker_id,
            "persona_md": self.draft.persona_md if self.draft else None,
            "source_metadata": self.source_metadata,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class WeChatImportJobRegistry:
    def __init__(self, *, persona_store: PersonaStore, memory_provider: MemoryProvider) -> None:
        self.persona_store = persona_store
        self.memory_provider = memory_provider
        self._jobs: dict[str, WeChatImportJob] = {}

    def create_job(
        self,
        file_path: str | Path,
        *,
        profile_id: str = "default",
        memory_library_id: str = "default",
        avatar_id: str,
        avatar_model: str,
        character_id: str | None = None,
        target_speaker_id: str | None = None,
        source_format: str = "auto",
        timezone: str = "Asia/Shanghai",
    ) -> WeChatImportJob:
        job = self._create_base_job(
            file_path,
            profile_id=profile_id,
            memory_library_id=memory_library_id,
            avatar_id=avatar_id,
            avatar_model=avatar_model,
            character_id=character_id,
            source_format=source_format,
            timezone=timezone,
        )
        if target_speaker_id or len(job.speakers) == 1:
            return self.select_speaker(job.id, target_speaker_id or job.speakers[0].id)
        return job

    async def create_job_async(
        self,
        file_path: str | Path,
        *,
        profile_id: str = "default",
        memory_library_id: str = "default",
        avatar_id: str,
        avatar_model: str,
        character_id: str | None = None,
        target_speaker_id: str | None = None,
        source_format: str = "auto",
        timezone: str = "Asia/Shanghai",
    ) -> WeChatImportJob:
        job = self._create_base_job(
            file_path,
            profile_id=profile_id,
            memory_library_id=memory_library_id,
            avatar_id=avatar_id,
            avatar_model=avatar_model,
            character_id=character_id,
            source_format=source_format,
            timezone=timezone,
        )
        if target_speaker_id or len(job.speakers) == 1:
            return await self.select_speaker_async(job.id, target_speaker_id or job.speakers[0].id)
        return job

    def _create_base_job(
        self,
        file_path: str | Path,
        *,
        profile_id: str,
        memory_library_id: str,
        avatar_id: str,
        avatar_model: str,
        character_id: str | None,
        source_format: str,
        timezone: str,
    ) -> WeChatImportJob:
        export = parse_weflow_export(file_path, source_format=source_format, timezone=timezone)
        speakers = [speaker for speaker in export.speakers if not speaker.is_self]
        if not speakers:
            speakers = list(export.speakers)
        job = WeChatImportJob(
            id=uuid.uuid4().hex,
            status="needs_speaker_selection",
            export=export,
            speakers=speakers,
            profile_id=(profile_id or "default").strip() or "default",
            memory_library_id=(memory_library_id or "default").strip() or "default",
            avatar_id=avatar_id,
            avatar_model=avatar_model,
            character_id=(character_id or avatar_id).strip() or avatar_id,
            source_metadata={**export.source_metadata, "source": "wechat_import"},
        )
        self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> WeChatImportJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("wechat import job not found") from exc

    def select_speaker(self, job_id: str, target_speaker_id: str) -> WeChatImportJob:
        job = self.get_job(job_id)
        draft = build_wechat_persona_draft(job.export, target_speaker_id=target_speaker_id)
        return self._set_draft(job, target_speaker_id=target_speaker_id, draft=draft)

    async def select_speaker_async(self, job_id: str, target_speaker_id: str) -> WeChatImportJob:
        job = self.get_job(job_id)
        draft = await build_wechat_persona_draft_async(job.export, target_speaker_id=target_speaker_id)
        return self._set_draft(job, target_speaker_id=target_speaker_id, draft=draft)

    def _set_draft(
        self,
        job: WeChatImportJob,
        *,
        target_speaker_id: str,
        draft: WeChatPersonaDraft,
    ) -> WeChatImportJob:
        job.selected_speaker_id = target_speaker_id
        job.draft = draft
        job.status = "draft_ready"
        job.updated_at = utc_now_iso()
        return job

    async def commit(
        self,
        job_id: str,
        *,
        persona_id: str,
        persona_name: str | None = None,
        description: str | None = None,
    ) -> MemoryImportCommitResult:
        job = self.get_job(job_id)
        if job.draft is None:
            raise ValueError("wechat import job has no persona draft")
        record = self._save_persona(job, persona_id=persona_id, persona_name=persona_name, description=description)
        imported = await self.memory_provider.add_items(
            library_id=job.memory_library_id,
            profile_id=job.profile_id,
            character_id=job.character_id,
            items=job.draft.memory_items,
        )
        job.status = "committed"
        job.updated_at = utc_now_iso()
        persona_md_path = record.path / "persona.md"
        return MemoryImportCommitResult(
            job_id=job.id,
            persona_id=record.manifest.id,
            memory_imported=imported,
            persona_md_bytes=persona_md_path.stat().st_size if persona_md_path.is_file() else 0,
            profile_id=job.profile_id,
            character_id=job.character_id,
            memory_library_id=job.memory_library_id,
        )

    def _save_persona(
        self,
        job: WeChatImportJob,
        *,
        persona_id: str,
        persona_name: str | None,
        description: str | None,
    ) -> PersonaRecord:
        if job.draft is None:
            raise ValueError("wechat import job has no persona draft")
        name = (persona_name or job.draft.persona_name or persona_id).strip() or persona_id
        manifest = PersonaManifest(
            schema_version=PERSONA_SCHEMA_VERSION,
            id=persona_id,
            name=name,
            description=(description or "Persona generated from an uploaded WeFlow WeChat export."),
            locale="zh-CN",
            avatar=PersonaAvatar(id=job.avatar_id, model=job.avatar_model),
            agent=PersonaAgent(
                persona_prompt="persona.md",
                memory_enabled=True,
                knowledge_enabled=False,
            ),
            runtime=PersonaRuntime(),
            safety=PersonaSafety(
                authorized_avatar=True,
                authorized_voice=False,
                content_label_required=True,
            ),
        )
        with tempfile.TemporaryDirectory(prefix="opentalking-wechat-persona-") as tmp:
            root = Path(tmp)
            (root / "persona.md").write_text(job.draft.persona_md.strip() + "\n", encoding="utf-8")
            (root / "import_metadata.json").write_text(
                json.dumps(job.draft.source_metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            write_persona_manifest(root / "persona.json", manifest)
            return self.persona_store.save_persona(
                manifest,
                source_dir=root,
                source="wechat_import",
                replace=True,
            )
