from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ImportJobStatus = Literal["needs_speaker_selection", "draft_ready", "committed", "error"]


@dataclass(frozen=True)
class MemoryImportCommitResult:
    job_id: str
    persona_id: str
    memory_imported: int
    persona_md_bytes: int
    profile_id: str
    character_id: str
    memory_library_id: str
