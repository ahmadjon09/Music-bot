"""Forgiving proxy parser.

Proxy vendors hand out credentials in every format known to humanity
(and a few known only to chaos). This module normalises all of them into
a canonical ``scheme://user:pass@host:port`` URL that yt-dlp understands.

Accepted shapes::

    host:port
    host:port:username:password
    username:password:host:port
    username:password@host:port
    host:port@username:password
    scheme://host:port
    scheme://username:password@host:port
    [ipv6]:port  /  scheme://user:pass@[ipv6]:port

``scheme`` may be http, https, socks4, socks5 or socks5h (default: http).
Multiple proxies can be separated by newlines, commas or semicolons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

_ALLOWED_SCHEMES = {"http", "https", "socks4", "socks5", "socks5h", "socks"}
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


class ProxyParseError(ValueError):
    """Raised when a string refuses to be a proxy, no matter how nicely we ask."""


@dataclass(frozen=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        auth = ""
        if self.username:
            auth = quote(self.username, safe="")
            if self.password:
                auth += f":{quote(self.password, safe='')}"
            auth += "@"
        return f"{self.scheme}://{auth}{host}:{self.port}"

    @property
    def masked(self) -> str:
        """Human-safe rendering for the admin panel — password stays a secret."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        auth = f"{self.username}:•••@" if self.username else ""
        return f"{self.scheme}://{auth}{host}:{self.port}"


def _valid_host(host: str) -> bool:
    if not host:
        return False
    if ":" in host:  # IPv6 literal — the split helpers already kept it intact
        return True
    if all(part.isdigit() and 0 <= int(part) <= 255 for part in host.split(".")) and host.count(".") == 3:
        return True
    return bool(_HOSTNAME_RE.match(host))


def _valid_port(value: str) -> bool:
    return value.isdigit() and 1 <= int(value) <= 65535


def _split_hostport(value: str) -> tuple[str, int] | None:
    """Split ``host:port`` (IPv6-aware). Returns None when it doesn't fit."""
    value = value.strip()
    if value.startswith("["):  # [ipv6]:port
        end = value.find("]")
        if end == -1 or not value[end + 1 :].startswith(":"):
            return None
        host, port = value[1:end], value[end + 2 :]
    elif value.count(":") == 1:
        host, port = value.rsplit(":", 1)
    elif value.count(":") > 1:  # bare IPv6 without a port — not usable here
        return None
    else:
        return None
    host = host.strip().lower()
    if _valid_host(host) and _valid_port(port.strip()):
        return host, int(port)
    return None


def _from_url(raw: str) -> Proxy:
    parts = urlsplit(raw if "://" in raw else f"http://{raw}")
    scheme = (parts.scheme or "http").lower()
    if scheme == "socks":
        scheme = "socks5"
    if scheme not in _ALLOWED_SCHEMES:
        raise ProxyParseError(f"Unsupported proxy scheme: {scheme!r}")
    host = (parts.hostname or "").lower()
    if not _valid_host(host) or parts.port is None:
        raise ProxyParseError(f"Invalid proxy URL: {raw!r}")
    return Proxy(
        scheme=scheme,
        host=host,
        port=parts.port,
        username=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
    )


def parse_proxy(raw: str) -> Proxy:
    """Parse a single proxy in any of the supported vendor formats."""
    text = (raw or "").strip()
    if not text:
        raise ProxyParseError("Empty proxy string")

    scheme = "http"
    if "://" in text:
        scheme_part, _, text = text.partition("://")
        scheme = scheme_part.strip().lower()
        if scheme == "socks":
            scheme = "socks5"
        if scheme not in _ALLOWED_SCHEMES:
            raise ProxyParseError(f"Unsupported proxy scheme: {scheme!r}")
        return _from_url_with_scheme(text, scheme)

    # ── Shapes containing "@": either user:pass@host:port or host:port@user:pass
    if "@" in text:
        left, _, right = text.rpartition("@")
        if hp := _split_hostport(right):  # user:pass@host:port (the sane one)
            user, _, password = left.partition(":")
            return Proxy(scheme, hp[0], hp[1], unquote(user), unquote(password))
        if hp := _split_hostport(left):  # host:port@user:pass (the vendor special)
            user, _, password = right.partition(":")
            return Proxy(scheme, hp[0], hp[1], unquote(user), unquote(password))
        raise ProxyParseError(f"Cannot parse proxy: {raw!r}")

    # ── Colon-joined shapes
    parts = text.split(":")
    if len(parts) == 2 and (hp := _split_hostport(text)):
        return Proxy(scheme, hp[0], hp[1])
    if len(parts) >= 4:
        # host:port:user:pass — password may itself contain ":" → keep the tail.
        if _valid_host(parts[0].lower()) and _valid_port(parts[1]):
            return Proxy(scheme, parts[0].lower(), int(parts[1]), parts[2], ":".join(parts[3:]))
        # user:pass:host:port — password may contain ":" too, so anchor on the tail.
        if hp := _split_hostport(":".join(parts[-2:])):
            user, password = parts[0], ":".join(parts[1:-2])
            return Proxy(scheme, hp[0], hp[1], user, password)
    if hp := _split_hostport(text):  # last chance (e.g. [ipv6]:port)
        return Proxy(scheme, hp[0], hp[1])
    raise ProxyParseError(f"Cannot parse proxy: {raw!r}")


def _from_url_with_scheme(rest: str, scheme: str) -> Proxy:
    proxy = parse_proxy(rest) if "@" not in rest and rest.count(":") != 1 else _from_url(f"{scheme}://{rest}")
    return Proxy(scheme, proxy.host, proxy.port, proxy.username, proxy.password)


def parse_proxy_list(raw: str) -> list[Proxy]:
    """Parse many proxies separated by newlines, commas or semicolons."""
    chunks = re.split(r"[\n,;]+", raw or "")
    proxies: list[Proxy] = []
    errors: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            proxies.append(parse_proxy(chunk))
        except ProxyParseError:
            errors.append(chunk)
    if errors and not proxies:
        raise ProxyParseError(f"Could not parse: {', '.join(errors[:3])}")
    if errors:
        raise ProxyParseError(f"Skipped invalid entries: {', '.join(errors[:3])}")
    return proxies
