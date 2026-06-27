from __future__ import annotations

import argparse

from apps.cli import persona


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenTalking command line tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    persona_parser = subparsers.add_parser("persona", help="Persona Package tools")
    persona_parser.add_argument("persona_args", nargs=argparse.REMAINDER)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "persona":
        return persona.main(args.persona_args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
