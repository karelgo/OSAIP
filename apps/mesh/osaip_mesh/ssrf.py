"""SSRF guard for user-supplied provider base URLs (spec §8).

An LLM connection's `base_url` is attacker-influencable input that the mesh will fetch
server-side, so it is validated on save AND before every call (a hostname's DNS answer
can change between the two — the check must not be a one-time formality).

Blocked by default: non-HTTP(S) schemes, credentials in the URL, and any host that
resolves to loopback / link-local (incl. cloud metadata 169.254.169.254) / private /
reserved space. An operator may allowlist specific hosts for on-prem models
(OSAIP_MESH_URL_ALLOWLIST), which is how Ollama on the compose network is reached.
"""

import ipaddress
import os
import socket
from urllib.parse import urlsplit


class UrlNotAllowed(ValueError):
    """The URL is refused; the message is safe to show a user."""


def _allowlist() -> set[str]:
    raw = os.environ.get("OSAIP_MESH_URL_ALLOWLIST", "")
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"The host {host!r} could not be resolved.") from exc
    addresses = []
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:  # pragma: no cover — getaddrinfo always yields literals
            continue
    return addresses


def _is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_loopback
        or address.is_link_local  # includes 169.254.169.254 (cloud metadata)
        or address.is_private
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_base_url(url: str) -> str:
    """Return the URL if it is safe to fetch server-side, else raise UrlNotAllowed."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UrlNotAllowed("Only http and https URLs are allowed.")
    if parts.username or parts.password:
        raise UrlNotAllowed("Credentials in the URL are not allowed — use a secret.")
    host = (parts.hostname or "").lower()
    if not host:
        raise UrlNotAllowed("The URL has no host.")
    if host in _allowlist():
        return url  # operator-allowlisted (e.g. the ollama container on the compose net)
    for address in _resolve(host):
        if _is_blocked(address):
            raise UrlNotAllowed(
                f"{host!r} resolves to a private or link-local address, which the mesh "
                "refuses to call. Add it to OSAIP_MESH_URL_ALLOWLIST if this is an "
                "intentional on-prem endpoint."
            )
    return url
