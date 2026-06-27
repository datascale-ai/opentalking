from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("OPENTALKING_WORKER_HOST", "0.0.0.0")
    port = int(os.environ.get("OPENTALKING_WORKER_PORT", "9001"))
    uvicorn.run(
        "opentalking.runtime.server:create_app",
        host=host,
        port=port,
        factory=True,
    )


if __name__ == "__main__":
    main()
