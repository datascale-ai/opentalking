# Repository Guidelines

## Project Structure & Module Organization
This repository is a Python-first monorepo for the OpenTalking runtime. Core application code lives in `opentalking/`, with entrypoints and service layers under `apps/` (`apps/api`, `apps/cli`, `apps/unified`). The web client is in `apps/web/`. Configuration and examples live in `configs/`, `examples/`, and `docs/`. Tests are under `tests/` and `apps/api/tests/`.

## Build, Test, and Development Commands
- `pytest tests -v` runs the main Python test suite.
- `ruff check opentalking/core opentalking/events opentalking/avatar apps tests` runs lint checks on the main code paths.
- `cd apps/web && npm run build` builds the Vite frontend.
- `python -m apps.api.main` or the installed script `opentalking-api` starts the API server.
- `python -m apps.unified.main` or `opentalking-unified` starts the unified runtime.

## Coding Style & Naming Conventions
Use Python 3.10+ conventions, 4-space indentation, and type hints where practical. Keep line length within the repo’s Ruff limit of 100 characters. Prefer `snake_case` for functions, modules, and variables; use `PascalCase` for classes. Run Ruff before sending changes. The frontend follows the existing Vite/React style in `apps/web/`.

## Testing Guidelines
Use `pytest` for Python tests. Place new tests in `tests/` or `apps/api/tests/` and name them `test_*.py`. Prefer focused unit tests for pipeline, runtime, and API changes. If a change affects the web build, verify `cd apps/web && npm run build` still succeeds.

## Commit & Pull Request Guidelines
Git history uses short, imperative commits with optional prefixes such as `feat:`, `fix:`, `docs:`, and `refactor:`. Keep commits narrow and descriptive. PRs should summarize the change, note any config or model-download impact, and include screenshots or logs for user-facing behavior when relevant.

## Agent-Specific Instructions
Before editing, inspect the relevant module boundaries and follow the existing patterns rather than introducing new abstractions. Avoid touching generated files, cached artifacts, or unrelated docs. When in doubt, prefer the smallest change that keeps the runtime, API, and web client consistent.
