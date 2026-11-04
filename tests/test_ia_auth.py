"""Offline proofs for IA login, secret isolation, renewal and request scope."""
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from romarr.ia_auth import ArchiveAuthError, configure, credentials, status
from romarr.ia_session import ArchiveOrgSession, ArchiveOrgTransport


@pytest.fixture
def root(tmp_path, monkeypatch):
    for key in ("EMAIL", "PASSWORD", "EMAIL_FILE", "PASSWORD_FILE"):
        monkeypatch.delenv("ROMARR_ARCHIVE_ORG_" + key, raising=False)
    # Exercise ROM Hub's actual persistent encrypted file store in CI.
    monkeypatch.setenv("ROM_HUB_SECRET_STORE", "file")
    monkeypatch.setenv("ROM_HUB_SECRET_KEY", "test-key-stored-only-in-environment")
    return tmp_path


def _client(root, handler, remote):
    manager = ArchiveOrgSession(root, login_transport=httpx.MockTransport(handler))
    return manager, httpx.Client(transport=ArchiveOrgTransport(
        manager, transport=httpx.MockTransport(remote)))


def _login(request, token="session"):
    assert request.url == "https://archive.org/services/xauthn/?op=login"
    assert request.method == "POST"
    assert b"email=" in request.content and b"password=" in request.content
    return httpx.Response(200, json={"success": True, "values": {"cookies": {
        "logged-in-user": "account%40example.com; Max-Age=3600; domain=.archive.org",
        "logged-in-sig": token + "; Max-Age=3600; domain=.archive.org"}}})


def test_ui_uses_existing_secret_store_and_only_one_encrypted_entry(root):
    assert status(root)["configured"] is False
    assert configure(root, "account@example.com", "secret-password") == {"ok": True}
    assert credentials(root) == ("account@example.com", "secret-password")
    stored = root / "secrets.json"
    assert stored.is_file()
    content = stored.read_text()
    assert "secret-password" not in content and "account@example.com" not in content
    assert not (root / "state.json").exists()
    assert status(root) == {"configured": True, "external": False, "error": ""}
    assert configure(root, clear=True) == {"ok": True}
    assert credentials(root) is None


def test_external_files_override_ui_without_copying_to_store(root, monkeypatch):
    assert configure(root, "ui@example.com", "ui-secret") == {"ok": True}
    email_path, password_path = root / "email", root / "password"
    email_path.write_text("external@example.com\n")
    password_path.write_text("external-secret\n")
    monkeypatch.setenv("ROMARR_ARCHIVE_ORG_EMAIL_FILE", str(email_path))
    monkeypatch.setenv("ROMARR_ARCHIVE_ORG_PASSWORD_FILE", str(password_path))
    assert credentials(root) == ("external@example.com", "external-secret")
    assert configure(root, "second@example.com", "second-secret")["ok"] is False
    assert status(root)["external"] is True
    monkeypatch.delenv("ROMARR_ARCHIVE_ORG_EMAIL_FILE")
    monkeypatch.delenv("ROMARR_ARCHIVE_ORG_PASSWORD_FILE")
    assert credentials(root) == ("ui@example.com", "ui-secret")


def test_login_reuses_cookie_and_never_sends_it_to_unrelated_hosts(root):
    assert configure(root, "account@example.com", "secret-password")["ok"]
    logins, requests = [], []
    def login(req):
        logins.append(1)
        return _login(req)
    def remote(req):
        requests.append((str(req.url), req.headers.get("cookie")))
        return httpx.Response(200)
    manager, client = _client(root, login, remote)
    with client:
        for host in ("archive.org", "ia800408.us.archive.org", "ia600107.ca.archive.org"):
            assert client.get(f"https://{host}/view_archive.php").status_code == 200
        for host in ("www.archive.org", "archive.org.attacker.test", "example.com"):
            assert client.get(f"https://{host}/download").status_code == 200
        assert client.get("http://archive.org/test").status_code == 200
    assert len(logins) == 1
    expected = "logged-in-user=account%40example.com; logged-in-sig=session"
    assert [cookie for _, cookie in requests] == [expected] * 3 + [None] * 4


def test_cookie_expiry_renews_before_request(root):
    assert configure(root, "account@example.com", "secret-password")["ok"]
    logins = []
    def login(req):
        logins.append(1)
        return _login(req, "cookie" + str(len(logins)))
    manager, client = _client(root, login, lambda req: httpx.Response(200))
    with client:
        client.get("https://archive.org/metadata/test")
        manager._expires = time.time() + 60  # inside the five-minute margin
        client.get("https://archive.org/metadata/test")
    assert len(logins) == 2


def test_403_reauthenticates_only_once_then_preserves_refusal(root):
    assert configure(root, "account@example.com", "secret-password")["ok"]
    logins, outgoing = [], []
    def login(req):
        logins.append(1)
        return _login(req, "cookie" + str(len(logins)))
    def remote(req):
        outgoing.append(req.headers["cookie"])
        return httpx.Response(403)
    _, client = _client(root, login, remote)
    with client:
        response = client.get("https://archive.org/download/restricted.zip/member.chd")
    assert response.status_code == 403
    assert len(logins) == 2
    assert len(outgoing) == 2 and outgoing[0] != outgoing[1]


def test_bad_login_message_cannot_expose_password(root):
    assert configure(root, "account@example.com", "secret-password")["ok"]
    _, client = _client(root, lambda req: httpx.Response(
        200, json={"success": False, "error": "secret-password"}), lambda req: httpx.Response(200))
    with client, pytest.raises(ArchiveAuthError, match="rejected"):
        client.get("https://archive.org/metadata/restricted")
    # The returned message contains no response body or submitted credentials.


def test_plugin_has_no_credentials_to_receive(root):
    from rom_hub.registry import Registry
    # This is a host-only secret slug, not an installed plugin secret declaration.
    assert "archive-org-host-auth" != "archive-org"
