from __future__ import annotations

from opentalking.providers.memory.runtime import MemoryScope
from opentalking.pipeline.session.runner import _agent_memory_enabled_for_runtime as session_agent_memory_enabled
from opentalking.pipeline.speak.synthesis_runner import (
    _agent_memory_enabled_for_runtime as speak_agent_memory_enabled,
)


def test_new_memory_runtime_disables_legacy_agent_memory_in_runners() -> None:
    enabled_scope = MemoryScope(
        enabled=True,
        profile_id="default",
        character_id="avatar-a",
        library_id="default",
    )

    assert session_agent_memory_enabled(memory_enabled=True, memory_scope=enabled_scope) is False
    assert speak_agent_memory_enabled(memory_enabled=True, memory_scope=enabled_scope) is False


def test_disabled_or_missing_memory_runtime_keeps_legacy_agent_memory_flag() -> None:
    disabled_scope = MemoryScope(
        enabled=False,
        profile_id="default",
        character_id="avatar-a",
        library_id="default",
    )
    empty_character_scope = MemoryScope(
        enabled=True,
        profile_id="default",
        character_id="",
        library_id="default",
    )

    assert session_agent_memory_enabled(memory_enabled=True, memory_scope=None) is True
    assert session_agent_memory_enabled(memory_enabled=True, memory_scope=disabled_scope) is True
    assert session_agent_memory_enabled(memory_enabled=True, memory_scope=empty_character_scope) is True
    assert session_agent_memory_enabled(memory_enabled=False, memory_scope=disabled_scope) is False
    assert speak_agent_memory_enabled(memory_enabled=True, memory_scope=None) is True
    assert speak_agent_memory_enabled(memory_enabled=True, memory_scope=disabled_scope) is True
    assert speak_agent_memory_enabled(memory_enabled=True, memory_scope=empty_character_scope) is True
    assert speak_agent_memory_enabled(memory_enabled=False, memory_scope=disabled_scope) is False
