"""Create a protected server secret from the reviewed template; never overwrite."""

import argparse
import ipaddress
import os
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать серверный env без вывода секретов")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--bind-ip", required=True)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.bind_ip)
    if (
        address.version != 4
        or not address.is_private
        or address.is_unspecified
        or address.is_loopback
    ):
        parser.error("bind-ip must be a concrete private IPv4 address")
    template = Path(__file__).resolve().parents[1] / "deploy/ai/.env.example"
    content = (
        template.read_text()
        .replace("ARENA_BIND_IP=172.16.34.7", f"ARENA_BIND_IP={address}")
        .replace("GENERATE_ON_SERVER", secrets.token_hex(32))
    )
    # Existing credentials must never be rotated by a repeated deployment.
    descriptor = os.open(args.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
    print("Created protected server environment (token not displayed)")


if __name__ == "__main__":
    main()
