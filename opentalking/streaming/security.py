from __future__ import annotations

import hmac
import ipaddress
import socket
from urllib.parse import urlparse


def constant_time_token_equal(expected: str, provided: str | None) -> bool:
    """Compare bearer tokens without leaking their common prefix."""

    if not expected or provided is None:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def validate_target_url(
    value: str,
    *,
    schemes: set[str],
    allow_local: bool = False,
    allowed_hosts: set[str] | None = None,
    allowed_cidrs: list[str] | None = None,
) -> str:
    """Validate a publisher endpoint before any network connection is made.

    This is intentionally conservative.  DNS resolution is performed by the
    caller immediately before connect as well; this helper only rejects
    malformed URLs, userinfo, localhost/private literals, and non-allowlisted
    hosts when local targets are disabled.
    """

    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {item.lower() for item in schemes}:
        raise ValueError(f"unsupported target scheme: {scheme or '<empty>'}")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("target must contain a hostname and no URL credentials")
    if "%" in parsed.netloc or "%" in parsed.path:
        raise ValueError("percent-encoded target components are not allowed")
    host = parsed.hostname.rstrip(".").lower()
    allowed = {item.rstrip(".").lower() for item in (allowed_hosts or set()) if item.strip()}
    if not allow_local and allowed and host not in allowed:
        raise ValueError("target host is not allowlisted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        networks = [ipaddress.ip_network(item, strict=False) for item in (allowed_cidrs or [])]
        is_local = address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
        if is_local and not allow_local and not any(address in net for net in networks):
            raise ValueError("private/local target is not allowed")
    return value.strip()


def validate_resolved_target(
    host: str,
    port: int,
    *,
    allow_local: bool = False,
    allowed_cidrs: list[str] | None = None,
) -> list[str]:
    """Resolve immediately before connect and reject private DNS answers."""

    addresses = resolve_public_ips(host, port)
    networks = [ipaddress.ip_network(item, strict=False) for item in (allowed_cidrs or [])]
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        is_local = address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
        if is_local and not allow_local and not any(address in net for net in networks):
            raise ValueError("target DNS answer is private/local and is not allowed")
    return addresses


def resolve_public_ips(host: str, port: int) -> list[str]:
    """Resolve a host for DNS pinning and reject empty/invalid answers."""

    results = {
        str(item[4][0])
        for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if item[4]
    }
    if not results:
        raise OSError(f"DNS returned no addresses for {host}")
    return sorted(results)
