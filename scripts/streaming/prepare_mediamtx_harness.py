#!/usr/bin/env python3
"""Create ephemeral MediaMTX credentials/config for the local harness.

The generated files live below ``outputs/`` (which is gitignored) and are
0600.  This script never prints the generated passwords.
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path


def _write_private(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="configs/streaming/mediamtx.yml")
    parser.add_argument("--output-dir", default="outputs/streaming")
    args = parser.parse_args()
    template = Path(args.template).read_text(encoding="utf-8")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    publish_password = secrets.token_urlsafe(24)
    read_password = secrets.token_urlsafe(24)
    auth = f'''authInternalUsers:
  - user: publisher
    pass: {publish_password}
    ips: []
    permissions:
      - action: publish
        path: live/rtmps-test
      - action: publish
        path: whip-test
  - user: reader
    pass: {read_password}
    ips: []
    permissions:
      - action: read
        path: live/rtmps-test
      - action: playback
        path: live/rtmps-test
      - action: read
        path: whip-test
'''
    rendered = template.replace("authInternalUsers: []", auth.rstrip())
    config_path = output_dir / "mediamtx.generated.yml"
    credentials_path = output_dir / "credentials.env"
    _write_private(config_path, rendered)
    _write_private(
        credentials_path,
        "\n".join(
            [
                "OPENTALKING_HARNESS_RTMPS_USERNAME=publisher",
                f"OPENTALKING_HARNESS_RTMPS_PASSWORD={publish_password}",
                "OPENTALKING_HARNESS_WHIP_TOKEN=publisher:" + publish_password,
                "OPENTALKING_HARNESS_READ_USERNAME=reader",
                f"OPENTALKING_HARNESS_READ_PASSWORD={read_password}",
                "",
            ]
        ),
    )
    print(f"Prepared ephemeral MediaMTX files in {output_dir.resolve()}")
    print(f"Source credentials only in: {credentials_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

