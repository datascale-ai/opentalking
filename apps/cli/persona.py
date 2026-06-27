from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from opentalking.agent.context_builder import default_knowledge_store
from opentalking.persona.package import (
    create_persona_package_from_dir,
    export_persona_package,
    import_persona_package,
    persona_record_json,
    validate_persona_package,
)
from opentalking.persona.session import default_persona_store


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def _import(path: Path) -> int:
    record = await import_persona_package(
        path,
        store=default_persona_store(),
        knowledge_store=default_knowledge_store(),
    )
    print(persona_record_json(record))
    return 0


def _validate(path: Path) -> int:
    manifest = validate_persona_package(path)
    _print_json({"valid": True, "persona": manifest.to_dict()})
    return 0


def _export(persona_id: str, out_path: Path) -> int:
    export_persona_package(persona_id, store=default_persona_store(), out_path=out_path)
    _print_json({"exported": True, "persona_id": persona_id, "path": str(out_path)})
    return 0


def _pack(source_dir: Path, out_path: Path) -> int:
    create_persona_package_from_dir(source_dir, out_path)
    _print_json({"packed": True, "path": str(out_path)})
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenTalking Persona Package tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a .otpersona package")
    validate.add_argument("path", type=Path)

    import_cmd = subparsers.add_parser("import", help="Import a .otpersona package")
    import_cmd.add_argument("path", type=Path)

    export = subparsers.add_parser("export", help="Export an installed persona")
    export.add_argument("persona_id")
    export.add_argument("--out", required=True, type=Path)

    pack = subparsers.add_parser("pack", help="Pack a persona source directory into .otpersona")
    pack.add_argument("source_dir", type=Path)
    pack.add_argument("--out", required=True, type=Path)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args.path)
        if args.command == "import":
            return asyncio.run(_import(args.path))
        if args.command == "export":
            return _export(args.persona_id, args.out)
        if args.command == "pack":
            return _pack(args.source_dir, args.out)
    except Exception as exc:  # noqa: BLE001
        print(f"persona command failed: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
