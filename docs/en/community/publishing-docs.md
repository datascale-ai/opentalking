# Docs Publishing

OpenTalking builds its documentation with MkDocs and Material for MkDocs, and uses `mike` to maintain versioned documentation directories.

## Local Validation

Install the documentation dependencies:

```bash
python -m pip install -r docs/requirements.txt
```

Build with the same strict mode used by CI:

```bash
python -m mkdocs build --strict --clean
```

## Versioned Publishing

A push to `main` publishes one entry by default:

- `/latest/`: the current main-branch documentation and the default site entry

For a formal release, start `.github/workflows/docs-pages.yml` manually from the matching release branch or tag and set `version` to the release number, for example `v0.1.0`. Formal releases are kept under frozen paths such as `/v0.1.0/` and are not overwritten by later main-branch docs. To make a version the default landing point, set `default_version` to that version or `latest`.

The workflow first writes the versioned site content to the `gh-pages` branch. If GitHub Pages is not enabled yet, it still maintains `gh-pages`, but skips the Pages artifact and deploy steps. When enabling Pages, choose GitHub Actions as the source.
