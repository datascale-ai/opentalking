from __future__ import annotations


def append_memory_prompt(system_prompt: str, memory_prompt: str) -> str:
    memory_prompt = (memory_prompt or "").strip()
    if not memory_prompt:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{memory_prompt}"
