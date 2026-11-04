"""ROMarr-owned Archive.org session authentication for ROM Hub.

A dedicated JSON credential file contains only Archive.org's two session cookie
values. ROMarr reads it host-side; ROM Hub plugins and their config never see it.
The authenticated fetcher is never shared with other plugins.
"""
import json
from pathlib import Path
import re

import httpx

_STORAGE_HOST = re.compile(r"ia[0-9]+\.(?:us|ca)\.archive\.org\Z")
_COOKIE_NAMES = ("logged-in-user", "logged-in-sig")


class ArchiveAuthError(ValueError):
    """Invalid or incomplete credentials; never include secret values."""


def _cookie_header(path: str | Path) -> str:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ArchiveAuthError("cannot read Archive.org cookie JSON secret") from exc

    if not isinstance(data, dict) or set(data) != set(_COOKIE_NAMES):
        raise ArchiveAuthError("Archive.org cookie secret must contain exactly "
                               "logged-in-user and logged-in-sig")
    parts = []
    for name in _COOKIE_NAMES:
        value = data[name]
        if (not isinstance(value, str) or not value or
                any(c in value for c in "\r\n; \t")):
            raise ArchiveAuthError(f"missing or invalid {name} cookie")
        parts.append(f"{name}={value}")
    return "; ".join(parts)


class ArchiveOrgCookieTransport(httpx.BaseTransport):
    """Attach Archive.org cookies only to approved HTTPS hostnames."""

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
    """Opt-in only for the archive-org plugin, not the shared ROM Hub fanout."""
    import os
    path = os.environ.get("ROMARR_ARCHIVE_ORG_COOKIES_FILE", "")
    return ArchiveOrgCookieTransport(path) if path and plugin_slug == "archive-org" else None
