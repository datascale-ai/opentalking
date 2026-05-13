# Contributing

Contributions to OpenTalking are welcome. This page documents the conventions for
submitting changes. For development environment setup, see [Developing](developing.md).

## Principles

**Interface-first design.** New synthesis backends, text-to-speech providers, speech
recognition providers, or WebRTC implementations should target the protocols defined
in `opentalking/core/interfaces/`. Concrete classes from `apps/` must not be imported
directly; doing so introduces coupling that is difficult to remove.

**Scoped commits.** Adapter, route, worker, and frontend changes should be split into
separate commits where practical, to facilitate review.

**Documentation alongside code.** User-visible behavior changes require updates to
both `docs/en/` and `docs/zh/` in the same pull request. Configuration changes require
updates to `.env.example` and the [Configuration](../user-guide/configuration.md)
page.

## Submission workflow

1. For non-trivial changes, open an issue to align on the proposed direction prior to
   implementation.
2. Branch from `main` using one of the prefixes `feat/`, `fix/`, `docs/`, or
   `refactor/`.
3. Run the local checks before pushing:

   ```bash
   ruff check opentalking apps tests
   ruff format opentalking apps tests
   pytest tests -v
   ```

4. Open a draft pull request early to receive feedback on the approach.
5. Mark the pull request ready for review once continuous integration passes.
6. Squash on merge unless commit history must be preserved.

## Commit message conventions

The repository follows a conventional commit style. Example:

```text
feat(worker): cache HuBERT features across sessions

Reuses extracted features between consecutive sessions on the same avatar,
reducing cold-start latency by approximately 400 ms. Keyed by avatar_id and
sample_rate.

Closes #142
```

Recognized prefixes:

- `feat:` — new feature.
- `fix:` — bug fix.
- `refactor:` — change with no behavioral impact.
- `docs:` — documentation only.
- `chore:` — infrastructure, dependencies, or build.
- `test:` — test-only change.

## Testing requirements

- New code paths require corresponding tests.
- Bug fixes require regression tests.
- Tests that perform live calls to external services (DashScope, ElevenLabs, etc.) are gated by `OPENTALKING_TEST_LIVE=1`.
- Slow tests are marked `@pytest.mark.slow` and are skipped in the default continuous integration run.

## Documentation

Two documentation surfaces are maintained:

| Surface | Updated when |
|---------|-------------|
| `README.md` / `README.en.md` | High-level project changes, major feature additions or removals, installation procedure changes. |
| `docs/` | Configuration fields, API endpoints, architecture, deployment topology, all detailed reference material. |

Both English and Chinese versions are first-class. Changes to one require corresponding
updates to the other.

## Reviewing pull requests

When reviewing, evaluate the following:

- Does the change match the agreed-upon issue or proposal?
- Are the existing project patterns followed (interface-first design, scoped commits, tests)?
- Are documentation updates included in the same pull request?
- Are error paths handled (network failures, missing avatars, malformed configuration)?

Use GitHub's suggestion feature for small corrections; leave comments for substantive
feedback.

## Code of conduct

Community standards are documented in
[CODE_OF_CONDUCT.md](https://github.com/datascale-ai/opentalking/blob/main/CODE_OF_CONDUCT.md).

## Communication channels

- GitHub Issues for bug reports and feature requests.
- The QQ group `1103327938` for general discussion (see [Community](../about/community.md)).
