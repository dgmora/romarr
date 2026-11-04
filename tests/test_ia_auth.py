"""Offline tests for Archive.org auth: cookies are never shared with other plugins."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from romarr.ia_auth import ArchiveAuthError, ArchiveOrgCookieTransport, archive_transport


class ArchiveAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "archive-org-cookies.json"
        self.config.write_text(
            '{"logged-in-user":"test%40example.com","logged-in-sig":"ABC%3D123"}'
        )

    def request(self, url):
        seen = []

        def mock(request):
            seen.append((str(request.url), request.headers.get("cookie")))
            return httpx.Response(200, text="ok")

        with httpx.Client(transport=ArchiveOrgCookieTransport(
                self.config, transport=httpx.MockTransport(mock))) as client:
            client.get(url)
        return seen[0]

    def test_cookie_exact_hosts_only(self):
        expected = "logged-in-user=test%40example.com; logged-in-sig=ABC%3D123"
        for host in ("archive.org", "ia800408.us.archive.org", "ia600107.ca.archive.org"):
            self.assertEqual(self.request(f"https://{host}/view_archive.php")[1], expected)
        for host in ("www.archive.org", "web.archive.org", "ia900.notarchive.org",
                     "archive.org.evil.example", "example.com"):
            self.assertIsNone(self.request(f"https://{host}/view_archive.php")[1])
        self.assertIsNone(self.request("http://archive.org/test")[1])

    def test_missing_login_is_no_transport(self):
        with patch.dict(os.environ, {"ROMARR_ARCHIVE_ORG_COOKIES_FILE": ""}):
            self.assertIsNone(archive_transport("archive-org"))
        with patch.dict(os.environ, {"ROMARR_ARCHIVE_ORG_COOKIES_FILE": str(self.config)}):
            self.assertIsNone(archive_transport("different-source"))
            transport = archive_transport("archive-org")
            self.assertIsInstance(transport, ArchiveOrgCookieTransport)
            transport.close()

    def test_missing_or_invalid_cookies_fail_closed_without_values(self):
        self.config.write_text('{"logged-in-user":"secret"}')
        with self.assertRaisesRegex(ArchiveAuthError, "exactly"):
            ArchiveOrgCookieTransport(self.config)
        self.config.write_text(
            '{"logged-in-user":"secret","logged-in-sig":"bad token"}'
        )
        with self.assertRaises(ArchiveAuthError) as raised:
            ArchiveOrgCookieTransport(self.config)
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("bad token", str(raised.exception))

    def test_rejects_non_json_and_extra_fields(self):
        self.config.write_text("[cookies]\\nlogged-in-user=secret\\n")
        with self.assertRaises(ArchiveAuthError):
            ArchiveOrgCookieTransport(self.config)
        self.config.write_text(
            '{"logged-in-user":"u","logged-in-sig":"s","s3-secret":"unsafe"}'
        )
        with self.assertRaisesRegex(ArchiveAuthError, "exactly"):
            ArchiveOrgCookieTransport(self.config)


if __name__ == "__main__":
    unittest.main()
