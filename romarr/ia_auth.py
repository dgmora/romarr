"""Persistent IA credentials for ROMarr's host-side HTTP transport.

UI credentials live in ROM Hub's existing secret store under a *host-only*
slug, never under an installed plugin slug. External files/env take precedence
and are never copied into the store. No cookies are persisted.
"""
import json
import os
from pathlib import Path

STORE_SLUG = "archive-org-host-auth"


class ArchiveAuthError(RuntimeError):
    """Errors must never contain a password or response body."""


def _external() -> bool:
    return any(os.environ.get("ROMARR_ARCHIVE_ORG_" + suffix) for suffix in (
        "EMAIL_FILE", "PASSWORD_FILE", "EMAIL", "PASSWORD"))


def _read_external(name: str) -> str:
    path = os.environ.get("ROMARR_ARCHIVE_ORG_" + name + "_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ArchiveAuthError("Could not read Archive.org " + name.lower() + " file") from None
    return os.environ.get("ROMARR_ARCHIVE_ORG_" + name, "")


def _store(root: Path):
    from rom_hub.secrets import open_store
    return open_store(root)


def credentials(root: Path) -> tuple[str, str] | None:
    if _external():
        email, password = _read_external("EMAIL"), _read_external("PASSWORD")
    else:
        try:
            value = _store(root).get(STORE_SLUG, "credentials")
            if not value:
                return None
            data = json.loads(value)
            email, password = data["email"], data["password"]
        except Exception:
            raise ArchiveAuthError("Could not read Archive.org credentials") from None
    if not email and not password:
        return None
    if (not isinstance(email, str) or not isinstance(password, str)
            or not email or not password or len(email) > 320
            or len(password) > 4096 or "\r" in email or "\n" in email):
        raise ArchiveAuthError("Archive.org email and password must both be configured")
    return email, password


def status(root: Path) -> dict:
    try:
        configured = credentials(root) is not None
        error = ""
    except ArchiveAuthError as exc:
        configured, error = False, str(exc)
    return {"configured": configured, "external": _external(), "error": error}


def configure(root: Path, email="", password="", clear=False) -> dict:
    if _external():
        return {"ok": False, "error": "External credentials override UI settings"}
    if not isinstance(clear, bool):
        return {"ok": False, "error": "Invalid clear flag"}
    if not clear and (not isinstance(email, str) or not isinstance(password, str)
                      or not email or "@" not in email or len(email) > 320
                      or "\r" in email or "\n" in email
                      or not password or len(password) > 4096):
        return {"ok": False, "error": "Valid email and password are required"}
    try:
        store = _store(root)
        if clear:
            store.delete(STORE_SLUG, "credentials")
        else:
            # One atomic secret-store write, unlike two independent fields.
            store.set(STORE_SLUG, "credentials",
                      json.dumps({"email": email, "password": password}))
        from .ia_session import invalidate
        invalidate(root)
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "Could not update Archive.org credentials"}
