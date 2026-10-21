"""Browser inbox tests with fake HTTP transport; no live email/network."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from browser_mail import BrowserMailbox, MAIL_HOST, MAIL_URL, MAIL_PATH


ROOT = Path(__file__).resolve().parents[1]


class BrowserMailTests(unittest.TestCase):
    def site_rows(self):
        return json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))["sites"]

    def test_only_explicit_registered_local_destinations_are_listed(self):
        sites = self.site_rows()
        mailbox = BrowserMailbox(sites)
        self.assertEqual(len(mailbox.messages), len(sites))
        self.assertEqual(set(mailbox.targets.values()),
                         {"https://" + s["host"] + s["entry"] for s in sites})
        self.assertEqual(set(mailbox.messages[0]), {
            "id", "sender", "senderAddress", "subject", "preview", "body", "time", "linkLabel"
        })
        for item in mailbox.public_messages():
            self.assertNotIn("target", item)
            self.assertNotIn("password", json.dumps(item).lower())
            self.assertNotIn("phishing", json.dumps(item).lower())
            self.assertNotIn("mock", json.dumps(item).lower())
            self.assertNotIn(".test", json.dumps(item).lower())
            self.assertEqual(mailbox.resolve(item["id"]), mailbox.targets[item["id"]])
        self.assertIsNone(mailbox.resolve("not-a-message"))

    def test_untrusted_paths_and_hostnames_are_never_published(self):
        mailbox = BrowserMailbox([
            {"host": "fixture.test", "entry": "/home", "id": "owned"},
            {"host": "fixture.test", "entry": "//evil.test", "id": "invalid"},
            {"host": "fixture.test", "entry": "/?token=secret", "id": "invalid"},
            {"host": "fixture.test:443", "entry": "/", "id": "invalid"},
            {"host": "fixture.test@evil.test", "entry": "/", "id": "invalid"},
            {"host": "", "entry": "/", "id": "invalid"},
        ])
        self.assertEqual(len(mailbox.public_messages()), 1)
        self.assertEqual(mailbox.resolve("1"), "https://fixture.test/home")

    def test_mail_frontend_is_browser_only(self):
        html = (MAIL_PATH / "index.html").read_text(encoding="utf-8")
        js = (MAIL_PATH / "app.js").read_text(encoding="utf-8")
        self.assertTrue(MAIL_URL.startswith("https://"))
        self.assertTrue(MAIL_HOST.startswith("inbox."))
        self.assertIn('id="search"', html)
        self.assertIn('id="list"', html)
        self.assertIn('id="reader"', html)
        self.assertIn('src="/app.js"', html)
        self.assertNotIn("https://fonts.", html)
        self.assertIn("fetch(\"/api/messages\"", js)
        self.assertIn('"/read/"', js)
        self.assertIn('"/open/"', js)
        self.assertNotIn("phishing", html.lower())
        self.assertNotIn("phishing", js.lower())
        self.assertNotIn("mock.test", html)
        self.assertNotIn("mock.test", js)
        compile((ROOT / "proxy_app.py").read_text(encoding="utf-8"), "proxy_app.py", "exec")

    def test_proxy_routes_mail_and_manager_separately_without_credentials(self):
        class FakeResponse:
            @staticmethod
            def make(status, body, headers):
                return types.SimpleNamespace(status_code=status, content=body, headers=headers)

        fake_http = types.ModuleType("mitmproxy")
        fake_http.http = types.SimpleNamespace(Response=FakeResponse)

        with mock.patch.dict(sys.modules, {"mitmproxy": fake_http}):
            import proxy_app
            portal = proxy_app.MockProxy()
            with tempfile.TemporaryDirectory() as tmp:
                portal.logfile = Path(tmp) / "events.jsonl"

                def fetch(host, path, method="GET"):
                    request = types.SimpleNamespace(
                        host=host, path=path, port=443, method=method,
                        headers={}, raw_content=b"",
                    )
                    flow = types.SimpleNamespace(request=request, response=None)
                    portal.handle(flow)
                    return flow.response

                page = fetch(MAIL_HOST, "/")
                self.assertEqual(page.status_code, 200)
                self.assertIn(b"Cedar Mail", page.content)
                self.assertEqual(fetch(MAIL_HOST, "/app.js").status_code, 200)
                messages = json.loads(fetch(MAIL_HOST, "/api/messages").content)
                self.assertEqual(len(messages), len(self.site_rows()))
                self.assertEqual(fetch(MAIL_HOST, "/read/1").status_code, 200)
                redirect = fetch(MAIL_HOST, "/open/1")
                self.assertEqual(redirect.status_code, 302)
                self.assertEqual(redirect.headers["Location"], portal.mailbox.resolve("1"))
                self.assertEqual(fetch(MAIL_HOST, "/open/999").status_code, 404)
                self.assertEqual(fetch(MAIL_HOST, "/open/1", "POST").status_code, 405)
                telemetry = json.loads(fetch("mock.test", "/__mock/mail-events").content)
                self.assertEqual([r["kind"] for r in telemetry],
                                 ["message_open", "link_click"])
                self.assertEqual(telemetry[0]["message_id"], "1")
                self.assertTrue(all("body" not in row and "headers" not in row
                                    and "password" not in row and "cookie" not in row
                                    for row in telemetry))
                rows = [json.loads(l) for l in portal.logfile.read_text().splitlines()]
                self.assertEqual(rows, telemetry)
                self.assertEqual(fetch("mock.test", "/__mock/mail-events", "DELETE").status_code, 200)
                self.assertEqual(json.loads(fetch("mock.test", "/__mock/mail-events").content), [])


if __name__ == "__main__":
    unittest.main()
