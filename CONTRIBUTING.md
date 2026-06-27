# Contributing

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e ".[dev]"
cd apps/web && npm ci
```

Install engine extras if you are working on FlashTalk:

```bash
pip install -e ".[engine,demo]"
```

## Workflow

1. Create a focused branch.
2. Keep changes scoped to one problem or migration step.
3. Run the relevant checks before opening a PR.
4. Include setup notes for anything hardware-specific.

## Checks

```bash
ruff check src/opentalking/core src/opentalking/server src/opentalking/worker src/opentalking/llm src/opentalking/tts src/opentalking/avatars src/opentalking/events src/opentalking/rtc apps/api apps/unified apps/cli tests
mypy src/opentalking/core src/opentalking/server src/opentalking/worker src/opentalking/llm src/opentalking/tts src/opentalking/avatars src/opentalking/events src/opentalking/rtc apps/api apps/unified apps/cli --ignore-missing-imports
pytest apps/api/tests apps/worker/tests tests
cd apps/web && npm run build
```

## Project Conventions

- Canonical Python packages live under `src/opentalking/`.
- `apps/web/` is the frontend. Do not mix backend code into it.
- Prefer `opentalking.*` imports over legacy package namespaces.
- Keep environment-specific paths configurable through env vars.
- Do not commit secrets, credentials, or machine-specific paths.

## Large Changes

For architecture work, include:

- the migration scope
- compatibility impact
- operational changes
- test coverage or validation performed

## Reporting Issues

Use the GitHub issue templates for bugs and feature requests.
