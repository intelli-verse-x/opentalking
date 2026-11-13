#!/usr/bin/env python3
"""Create ephemeral MediaMTX credentials/config for the local harness.

The generated files live below ``outputs/`` (which is gitignored) and are
0600.  This script never prints the generated passwords.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import secrets
import tempfile
from pathlib import Path


def _write_private(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The harness is POSIX-only. Do not imply chmod bits provide a Windows ACL.
    if os.name != "posix":
        raise RuntimeError("private harness credential files require a POSIX host")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        # mkstemp creates a private 0600 file before any credential bytes are
        # written. Replacing the path also avoids following an existing symlink.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="configs/streaming/mediamtx.yml")
    parser.add_argument("--output-dir", default="outputs/streaming")
    args = parser.parse_args()
    template = Path(args.template).read_text(encoding="utf-8")
    public_ip = os.environ.get("OPENTALKING_STREAMING_PUBLIC_IP", "").strip()
    if public_ip:
        try:
            ipaddress.ip_address(public_ip)
        except ValueError as exc:
            raise SystemExit(f"OPENTALKING_STREAMING_PUBLIC_IP is not an IP address: {public_ip}") from exc
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
    if public_ip:
        # The default harness is loopback-only. A remote browser needs the
        # server address for WebRTC signaling and ICE media candidates.
        rendered = rendered.replace("webrtcAddress: 127.0.0.1:8889", "webrtcAddress: 0.0.0.0:8889")
        rendered = rendered.replace("webrtcLocalUDPAddress: 127.0.0.1:8189", "webrtcLocalUDPAddress: 0.0.0.0:8189")
        rendered = rendered.replace("webrtcLocalTCPAddress: 127.0.0.1:8190", "webrtcLocalTCPAddress: 0.0.0.0:8190")
        rendered = rendered.replace(
            "webrtcAdditionalHosts:\n  - 127.0.0.1",
            f"webrtcAdditionalHosts:\n  - 127.0.0.1\n  - {public_ip}",
        )
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
                "OPENTALKING_HARNESS_WHEP_TOKEN=reader:" + read_password,
                "",
            ]
        ),
    )
    print(f"Prepared ephemeral MediaMTX files in {output_dir.resolve()}")
    print(f"Source credentials only in: {credentials_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
