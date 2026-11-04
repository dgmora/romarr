"""Scoped Archive.org session cookies for ROMarr's ROM Hub HTTP bridge.

The plugin subprocess receives no secrets. ROM Hub's host fetcher and
downloader both support an HTTPX transport argument; use it to attach an
Archive.org session only to the intended HTTPS hosts.
"""
from configparser import ConfigParser
from pathlib import Path
import re

import httpx

_STORAGE_HOST = re.compile(r"ia[0-9]+\.(?:us|ca)\.archive\.org\Z")
_COOKIE_NAMES = ("logged-in-user", "logged-in-sig")


class ArchiveAuthError(ValueError):
    """Invalid or incomplete credentials; never include secret values."""


def _cookie_header(config_path: str | Path) -> str:
    config = ConfigParser(interpolation=None)
    path = Path(config_path)
    try:
        with path.open(encoding="utf-8") as handle:
            config.read_file(handle)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ArchiveAuthError("cannot read Archive.org authentication config") from exc
    if not config.has_section("cookies"):
        raise ArchiveAuthError("Archive.org config has no [cookies] section")
    parts = []
    for name in _COOKIE_NAMES:
        raw = config.get("cookies", name, fallback="").strip()
        # internetarchive's ia.ini saves a Set-Cookie string; the first
        # portion is the cookie value, followed by domain/expiry attributes.
        token = raw.partition(";")[0].strip()
        if token.startswith(name + "="):
            token = token[len(name) + 1:]
        if not token or any(ch in token for ch in "\r\n; "):
            raise ArchiveAuthError(f"missing or invalid {name} cookie")
        parts.append(f"{name}={token}")
    return "; ".join(parts)


class ArchiveOrgCookieTransport(httpx.BaseTransport):
    """Attach IA cookies to explicitly permitted Archive.org HTTPS hosts.

    This is not a global HTTPX cookie jar: ROM Hub's search dispatcher
    shares its fetcher across plugins. Only call this transport for the
    archive-org plugin, with anonymous transport for all other plugins.
    """

    def __init__(self, config_path: str | Path,
                 transport: httpx.BaseTransport | None = None):
        self._cookie = _cookie_header(config_path)
        self._delegate = transport if transport is not None else httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = (request.url.host or "").lower().rstrip(".")
        if (request.url.scheme == "https" and
                (host == "archive.org" or _STORAGE_HOST.fullmatch(host))):
            request.headers["cookie"] = self._cookie
        return self._delegate.handle_request(request)

    def close(self) -> None:
        self._delegate.close()


def archive_transport(plugin_slug: str):
    """Opt-in credentials only for the Archive.org plugin."""
    import os
    path = os.environ.get("ROMARR_IA_CONFIG_FILE", "")
    return ArchiveOrgCookieTransport(path) if path and plugin_slug == "archive-org" else None
