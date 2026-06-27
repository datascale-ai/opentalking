# Community

OpenTalking is developed as an open-source project. Contributions are welcome through
GitHub, the QQ group, and documentation feedback.

## Channels

| Channel | Purpose |
|---------|---------|
| [GitHub repository](https://github.com/datascale-ai/opentalking) | Code, docs, issues, and pull requests. |
| [GitHub Issues](https://github.com/datascale-ai/opentalking/issues) | Bug reports, feature requests, and reproducible deployment problems. |
| [GitHub Discussions](https://github.com/datascale-ai/opentalking/discussions) | Design discussion, Q&A, and model integration proposals. |
| [GitHub Releases](https://github.com/datascale-ai/opentalking/releases) | Version history and changelog. |
| QQ group `1103327938` | Chinese real-time discussion for OpenTalking, FlashTalk, OmniRT, and deployment. |

![AI digital-human QQ group QR code](../../assets/images/qq_group_qrcode.png){ width=280 }

## Ways to Participate

- **Report issues**: use the bug report template and include system, hardware, commands, logs, and `/models` output.
- **Request features**: use the feature request template and describe the scenario, API expectation, and acceptable deployment dependencies.
- **Improve docs**: typo fixes, command corrections, and new cases are all welcome.
- **Contribute model integration**: read [Model Adapter](../docs/model-adapter.md) first to align backend boundaries and validation.
- **Discuss architecture**: open a Discussion or Draft PR before large API, deployment, or model-strategy changes.

## Good First Tasks

- Add screenshots, common errors, and environment notes to tutorials.
- Add mirror links and checksum notes to `deployment` pages.
- Add reproducible records to the Benchmark section.
- Improve request and response examples in API docs.
- Add avatar asset validation examples.

## PR Checklist

Before submitting, confirm:

- Documentation links pass `python -m mkdocs build --strict --clean`.
- Code changes include tests, or explain why tests are unnecessary.
- New config options are reflected in tutorials, model deployment docs, or API docs.
- The PR does not include local private paths, internal hostnames, secrets, or non-public logs.
- Behavior changes explain migration impact in the PR description.

## Feedback Template

For deployment or runtime problems, include:

```text
OpenTalking commit:
Run mode: mock / local / direct_ws / omnirt
Hardware: CPU / GPU / NPU model
Operating system:
Python / Node.js versions:
Startup command:
Relevant .env settings (without secrets):
/health output:
/models output:
Error logs:
```

## Roadmap

Project planning lives in GitHub issues, discussions, releases, and roadmap documents. The
community page only keeps participation paths and does not replace version planning.
