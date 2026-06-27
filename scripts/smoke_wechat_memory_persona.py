from __future__ import annotations

# ruff: noqa: E402 - smoke script adds the repo root before importing local packages.

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from opentalking.core.config import get_settings
from opentalking.persona.session import build_session_defaults
from opentalking.persona.store import PersonaStore
from opentalking.persona.wechat_import import WeChatImportJobRegistry
from opentalking.providers.memory.mem0_provider import InMemoryMemoryProvider
from opentalking.providers.memory.runtime import MemoryRuntime, normalize_memory_scope



def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    return value


def fake_weflow_chatlab_export() -> dict[str, Any]:
    return {
        "chatlab": {"version": "0.0.2", "generator": "WeFlow"},
        "meta": {
            "name": "Smoke project room",
            "platform": "wechat",
            "type": "group",
            "groupId": "room-smoke@chatroom",
        },
        "members": [
            {"platformId": "wxid_li", "accountName": "Li", "groupNickname": "Li"},
            {"platformId": "wxid_chen", "accountName": "Chen", "groupNickname": "Chen"},
            {"platformId": "self_wxid", "accountName": "me", "groupNickname": "me"},
        ],
        "messages": [
            {
                "sender": "wxid_li",
                "accountName": "Li",
                "groupNickname": "Li",
                "timestamp": 1738713600,
                "type": 0,
                "content": "morning, breathe first. keep it small today.",
                "platformMessageId": "10000000000000000001",
            },
            {
                "sender": "self_wxid",
                "accountName": "me",
                "groupNickname": "me",
                "timestamp": 1738713660,
                "type": 0,
                "content": "I am nervous about the demo.",
                "platformMessageId": "10000000000000000002",
                "isSelf": True,
            },
            {
                "sender": "wxid_chen",
                "accountName": "Chen",
                "groupNickname": "Chen",
                "timestamp": 1738713720,
                "type": 0,
                "content": "ship now, no need to wait.",
                "platformMessageId": "10000000000000000003",
            },
            {
                "sender": "wxid_li",
                "accountName": "Li",
                "groupNickname": "Li",
                "timestamp": 1738713780,
                "type": 0,
                "content": "then make one tiny checklist and ping me after lunch.",
                "platformMessageId": "10000000000000000004",
            },
            {
                "sender": "wxid_li",
                "accountName": "Li",
                "groupNickname": "Li",
                "timestamp": 1738713840,
                "type": 0,
                "content": "no need to be heroic, steady is enough.",
                "platformMessageId": "10000000000000000005",
            },
            {
                "sender": "wxid_li",
                "accountName": "Li",
                "groupNickname": "Li",
                "timestamp": 1738713900,
                "type": 0,
                "content": "demo secret code is 8848 and should never be copied raw.",
                "platformMessageId": "10000000000000000006",
            },
        ],
    }


async def run_smoke(report_dir: Path) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="opentalking-wechat-smoke-", dir=str(report_dir)))
    export_path = workspace / "fake-weflow-chatlab.json"
    export_path.write_text(json.dumps(fake_weflow_chatlab_export(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    persona_store = PersonaStore(workspace / "personas")
    memory_provider = InMemoryMemoryProvider()
    registry = WeChatImportJobRegistry(persona_store=persona_store, memory_provider=memory_provider)

    checks: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})

    job = registry.create_job(
        export_path,
        profile_id="smoke-profile",
        memory_library_id="wechat-smoke",
        avatar_id="smoke-avatar-li",
        avatar_model="mock",
    )
    check("job waits for speaker selection in group chat", job.status == "needs_speaker_selection", job.status)
    check("speakers parsed from uploaded WeFlow file", [s.id for s in job.speakers] == ["wxid_li", "wxid_chen"], [s.id for s in job.speakers])

    selected = await registry.select_speaker_async(job.id, "wxid_li")
    check("speaker selection builds draft", selected.status == "draft_ready" and selected.draft is not None, selected.status)
    persona_md_preview = selected.draft.persona_md if selected.draft else ""
    check("persona draft is summary, not raw secret", "8848" not in persona_md_preview and "demo secret code" not in persona_md_preview)

    commit = await registry.commit(job.id, persona_id="smoke-friend-li", persona_name="Smoke Friend Li")
    check("commit imports three layered memories", commit.memory_imported == 3, commit.memory_imported)

    record = persona_store.get_persona("smoke-friend-li")
    persona_md = (record.path / "persona.md").read_text(encoding="utf-8")
    check("persona is bound to avatar asset", record.manifest.avatar.id == "smoke-avatar-li", record.manifest.avatar.id)
    check("persona manifest points to persona.md", record.manifest.agent.persona_prompt == "persona.md", record.manifest.agent.persona_prompt)
    check("persona.md exists and is redacted", "8848" not in persona_md and "demo secret code" not in persona_md)

    defaults = build_session_defaults(record)
    check("session defaults load persona.md into system prompt", bool(defaults.llm_system_prompt and "# Persona" in defaults.llm_system_prompt), defaults.llm_system_prompt[:120] if defaults.llm_system_prompt else None)

    items = await memory_provider.list_items(
        library_id="wechat-smoke",
        profile_id="smoke-profile",
        character_id="smoke-avatar-li",
    )
    memory_layers = sorted({str(item.metadata.get("layer")) for item in items})
    check("memory items carry style/semantic/episodic layers", memory_layers == ["episodic", "semantic", "style"], memory_layers)
    check("memory items are structured imported records", all(item.metadata.get("source") == "wechat_import" for item in items))
    check("memory items are redacted", all("8848" not in item.text and "demo secret code" not in item.text for item in items))

    settings = get_settings()
    scope = normalize_memory_scope(
        settings=settings,
        memory_enabled=True,
        profile_id="smoke-profile",
        character_id="smoke-avatar-li",
        avatar_id="smoke-avatar-li",
        library_id="wechat-smoke",
    )
    runtime = MemoryRuntime(scope=scope, provider=memory_provider, settings=settings)
    recall_query = "\u6309 Li \u7684 calm practical guidance \u98ce\u683c\u56de\u7b54\u8fd9\u6761 demo \u5b89\u6392"
    recall_prompt = await runtime.retrieve_prompt(recall_query)
    check("conversation memory runtime recalls imported memories", bool(recall_prompt.strip()) and "Li tends to use concise replies" in recall_prompt, recall_prompt)

    result = {
        "generated_at": utc_now(),
        "workspace": str(workspace),
        "input": {
            "fake_weflow_export": str(export_path),
            "fake_only": "Only the WeFlow chat record is simulated; parser/import/persona/session/memory runtime use real project code.",
        },
        "job": selected.to_dict(),
        "commit": to_jsonable(commit),
        "persona": {
            "id": record.manifest.id,
            "name": record.manifest.name,
            "avatar": to_jsonable(record.manifest.avatar),
            "agent": to_jsonable(record.manifest.agent),
            "path": str(record.path),
            "persona_md": persona_md,
            "session_system_prompt": defaults.llm_system_prompt,
        },
        "memory": {
            "library_id": "wechat-smoke",
            "profile_id": "smoke-profile",
            "character_id": "smoke-avatar-li",
            "items": [to_jsonable(item) for item in items],
            "layers": memory_layers,
            "runtime_recall_query": recall_query,
            "runtime_recall_prompt": recall_prompt,
        },
        "checks": checks,
        "summary": {
            "passed": all(item["passed"] for item in checks),
            "passed_count": sum(1 for item in checks if item["passed"]),
            "failed_count": sum(1 for item in checks if not item["passed"]),
        },
    }
    return result


def write_markdown(result: dict[str, Any], out_path: Path) -> None:
    checks = result["checks"]
    failed = [item for item in checks if not item["passed"]]
    memory_items = result["memory"]["items"]
    lines = [
        "# WeChat Memory Persona Smoke Report",
        "",
        f"Generated at: `{result['generated_at']}`",
        "",
        "## Scope",
        "",
        "This smoke test simulates only the uploaded WeFlow WeChat export file. All processing after upload uses the real OpenTalking feature code: parser, import job registry, persona store, persona.md loading, memory provider writes, and memory runtime recall.",
        "",
        "## Result",
        "",
        f"- Overall: {'PASS' if result['summary']['passed'] else 'FAIL'}",
        f"- Passed checks: {result['summary']['passed_count']}",
        f"- Failed checks: {result['summary']['failed_count']}",
        f"- Temp workspace on 146: `{result['workspace']}`",
        "",
        "## Key Evidence",
        "",
        f"- Persona id: `{result['persona']['id']}`",
        f"- Bound avatar asset: `{result['persona']['avatar']['id']}` / model `{result['persona']['avatar']['model']}`",
        f"- persona.md path: `{result['persona']['path']}/persona.md`",
        f"- Memory layers: `{', '.join(result['memory']['layers'])}`",
        f"- Runtime recall query: `{result['memory']['runtime_recall_query']}`",
        f"- Runtime recall prompt non-empty: `{bool(result['memory']['runtime_recall_prompt'])}`",
        "",
        "## Checks",
        "",
    ]
    for item in checks:
        mark = "PASS" if item["passed"] else "FAIL"
        lines.append(f"- {mark}: {item['name']}")
        if item.get("detail") is not None and not item["passed"]:
            lines.append(f"  Detail: `{item['detail']}`")
    lines.extend([
        "",
        "## Generated persona.md",
        "",
        "```markdown",
        result["persona"]["persona_md"].strip(),
        "```",
        "",
        "## Imported Memory Items",
        "",
    ])
    for item in memory_items:
        metadata = item.get("metadata") or {}
        lines.append(f"- `{metadata.get('layer')}` / `{item.get('type')}`: {item.get('text')}")
    lines.extend([
        "",
        "## Runtime Recall Prompt",
        "",
        "```text",
        result["memory"]["runtime_recall_prompt"].strip(),
        "```",
        "",
        "## Analysis",
        "",
        "The end-to-end path is functioning if all checks pass: uploaded WeFlow data is parsed, group-speaker selection is required, the chosen speaker produces a redacted persona.md draft, commit persists a persona bound to the avatar asset, session defaults load persona.md into the system prompt, and the memory runtime can recall structured imported memories. Raw chat logs are not injected into prompts; only the generated persona summary and structured memory items are used at runtime.",
    ])
    if failed:
        lines.extend(["", "## Failures", ""])
        for item in failed:
            lines.append(f"- {item['name']}: `{item.get('detail')}`")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test WeFlow WeChat import -> persona.md -> memory runtime.")
    parser.add_argument("--report-dir", default="/tmp/opentalking-wechat-smoke", help="Directory for generated reports")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    result = asyncio.run(run_smoke(report_dir))
    json_path = report_dir / "wechat-memory-persona-smoke-report.json"
    md_path = report_dir / "wechat-memory-persona-smoke-report.md"
    json_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(result, md_path)
    print(json.dumps({"passed": result["summary"]["passed"], "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0 if result["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
