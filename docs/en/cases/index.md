# Use Cases

Use cases answer a practical question: how OpenTalking can be used today. This section
does not repeat model deployment details. Instead, each page ties together the business
goal, recommended pipeline, configuration points, validation steps, and integration path.

If you are new to the project, finish the [Quickstart](../tutorials/quickstart.md) first.
If a case uses a real talking-head model, make sure the corresponding backend and weights
are ready in [Model Deployment](../model-deployment/index.md).

## Pick a Case

<div class="grid cards" markdown>

-   :material-headset: **AI Customer Support**

    ---

    Start with the `mock` path for support conversations, TTS, captions, and WebRTC,
    then replace it with a real avatar backend.

    [Open case →](customer-support.md)

-   :material-storefront: **Product Demo and Live Sales**

    ---

    For e-commerce, showrooms, and guided demos: persona, product facts, long-form
    speaking, and operator interruption.

    [Open case →](product-demo-live-sales.md)

-   :material-domain: **Private Deployment**

    ---

    Use OpenTalking as the orchestration layer for private LLMs, TTS, avatar backends,
    Redis, and an enterprise gateway.

    [Open case →](private-deployment.md)

</div>

## Cases vs. Low-Level Guides

| Goal | Read |
|------|------|
| Understand what business scenarios are possible | This Use Cases section |
| Run the project for the first time | [Quickstart](../tutorials/quickstart.md) |
| Deploy Wav2Lip, QuickTalk, or FlashTalk | [Model Deployment](../model-deployment/index.md) |
| Call an API endpoint | [API Interfaces](../docs/api/index.md) |
| Add a new model backend | [Model Adapter](../docs/model-adapter.md) |

## Template for New Cases

Use the same structure for future cases:

1. Suitable scenarios.
2. Expected result.
3. Recommended pipeline.
4. Prerequisites.
5. Configuration and startup.
6. WebUI or API operation.
7. Validation.
8. Troubleshooting.
9. Next extensions.

