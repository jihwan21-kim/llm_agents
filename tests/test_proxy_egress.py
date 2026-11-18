"""Route real agent/browser services without bypassing local mock replays.

The HTTP transport is a fake: these tests never send credentials or telemetry
to external hosts. Test URLs are the endpoint families reported by the user.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
from urllib.parse import urlsplit


class Headers(dict):
    def items(self, multi=False):
        return super().items()


class FakeResponse:
    @staticmethod
    def make(status, body, headers):
        return types.SimpleNamespace(status_code=status, content=body,
                                     headers=dict(headers))


def flow_for(url, method="GET", headers=None):
    parts = urlsplit(url)
    body = b'{"synthetic":true}' if method == "POST" else b""
    request = types.SimpleNamespace(
        scheme=parts.scheme, host=parts.hostname,
        port=parts.port or (443 if parts.scheme == "https" else 80),
        path=parts.path + ("?" + parts.query if parts.query else ""),
        pretty_url=url, method=method, headers=Headers(headers or {}),
        raw_content=body, get_text=lambda strict=False: body.decode(),
    )
    return types.SimpleNamespace(request=request, response=None)


OBSERVED_REQUESTS = (
    ("GET", "https://www.google.com/async/folae?async=_fmt:pb&udm=50&client_locale=ko&client_country=us"),
    ("OPTIONS", "https://csp.withgoogle.com/csp/report-to/gse_qebhlk"),
    ("POST", "https://browser-intake-us5-datadoghq.com/api/v2/rum?ddsource=browser&dd-api-key=public-test-key"),
    ("POST", "https://beacons.gcp.gvt2.com/domainreliability/upload"),
    ("POST", "https://beacons5.gvt3.com/domainreliability/upload"),
    ("POST", "https://clients2.google.com/domainreliability/upload"),
    ("POST", "https://beacons5.gvt2.com/domainreliability/upload"),
    ("POST", "https://beacons3.gvt2.com/domainreliability/upload"),
    ("POST", "https://beacons4.gvt2.com/domainreliability/upload"),
    ("POST", "https://update.googleapis.com/service/update2/json?cup2key=synthetic-test"),
    ("POST", "https://ab.chatgpt.com/v1/rgstr?k=synthetic-test&st=javascript"),
    ("POST", "https://ab.chatgpt.com/v1/sdk_exception"),
    ("POST", "https://o33249.ingest.us.sentry.io/api/4512228274601984/envelope/?sentry_version=7&sentry_key=synthetic-test"),
)

# Chrome sign-in dependencies from the reported flow, plus the paired token
# upgrade endpoint and www discovery variant. No real tokens are used.
GOOGLE_SIGNIN_REQUESTS = (
    ("POST", "https://www.googleapis.com/oauth2/v4/token"),
    ("POST", "https://accounts.google.com/RegisterSession"),
    ("POST", "https://oauthaccountmanager.googleapis.com/v1/issuetoken"),
    ("POST", "https://oauthaccountmanager.googleapis.com/v1/upgradetoken"),
    ("GET", "https://google.com/.well-known/device-bound-sessions"),
    ("GET", "https://www.google.com/.well-known/device-bound-sessions"),
    ("POST", "https://accounts.google.com/ListAccounts?source=ChromiumBrowser"),
    ("GET", "https://accounts.google.com/RotateBoundCookies"),
)


class ProxyEgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        http = types.ModuleType("mitmproxy.http")
        http.Response = FakeResponse
        mitmproxy = types.ModuleType("mitmproxy")
        mitmproxy.http = http
        options = types.ModuleType("mitmproxy.options")
        options.Options = object
        tools = types.ModuleType("mitmproxy.tools")
        dump = types.ModuleType("mitmproxy.tools.dump")
        dump.DumpMaster = object
        with mock.patch.dict(sys.modules, {
            "mitmproxy": mitmproxy, "mitmproxy.http": http,
            "mitmproxy.options": options, "mitmproxy.tools": tools,
            "mitmproxy.tools.dump": dump,
        }):
            import proxy_app
            import run_capture_proxy
        cls.proxy_app = proxy_app
        cls.recording_proxy = run_capture_proxy

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proxy = self.proxy_app.MockProxy()
        self.proxy.logfile = Path(self.tmp.name) / "requests.jsonl"

    def connect(self, proxy, host, port=443):
        data = types.SimpleNamespace(server=types.SimpleNamespace(
            address=(host, port), error=None))
        proxy.server_connect(data)
        return data.server.error

    def test_all_reported_background_requests_are_forwarded_not_faked(self):
        for method, url in OBSERVED_REQUESTS:
            with self.subTest(method=method, url=url):
                flow = flow_for(url, method)
                self.proxy.request(flow)
                self.assertIsNone(flow.response)
                self.assertIsNone(self.connect(self.proxy, flow.request.host))
        self.assertFalse(self.proxy.logfile.exists())

    def test_report_preflights_and_posts_use_real_upstream(self):
        for _, url in OBSERVED_REQUESTS[1:]:
            for method in ("OPTIONS", "POST"):
                with self.subTest(method=method, url=url):
                    flow = flow_for(url, method, {"Origin": "https://claude.ai"})
                    self.proxy.request(flow)
                    self.assertIsNone(flow.response)

    def test_existing_claude_api_and_agent_services_still_forward(self):
        urls = (
            "https://claude.ai/api/event_logging/v2/batch",
            "https://api.anthropic.com/v1/messages",
            "https://api.openai.com/v1/responses",
        )
        for url in urls:
            with self.subTest(url=url):
                flow = flow_for(url, "POST", {"Origin": "chrome-extension://test"})
                self.proxy.request(flow)
                self.assertIsNone(flow.response)
        self.assertFalse(self.proxy.logfile.exists())

    def test_chatgpt_session_and_browser_side_chat_are_forwarded(self):
        for path in ("/api/auth/session", "/?surface=browser_side_chat"):
            with self.subTest(path=path):
                flow = flow_for("https://chatgpt.com" + path)
                self.proxy.request(flow)
                self.assertIsNone(flow.response)
                self.assertIsNone(self.connect(self.proxy, "chatgpt.com"))
        self.assertFalse(self.proxy.logfile.exists())

    def test_google_signin_sequence_passes_without_modifying_or_logging_tokens(self):
        for method, url in GOOGLE_SIGNIN_REQUESTS:
            with self.subTest(method=method, url=url):
                flow = flow_for(url, method, {
                    "Origin": "https://accounts.google.com",
                    "Authorization": "Bearer synthetic-test-token",
                    "Cookie": "synthetic-session=test-only",
                })
                before_headers = dict(flow.request.headers)
                before_body = flow.request.raw_content
                self.proxy.request(flow)
                self.assertIsNone(flow.response)
                self.assertIsNone(self.connect(self.proxy, flow.request.host))
                self.assertEqual(dict(flow.request.headers), before_headers)
                self.assertEqual(flow.request.raw_content, before_body)
        self.assertFalse(self.proxy.logfile.exists())

    def test_google_signin_exceptions_reject_mock_origins_and_referrers(self):
        for method, url in GOOGLE_SIGNIN_REQUESTS:
            for header in ("Origin", "Referer"):
                with self.subTest(method=method, url=url, header=header):
                    flow = flow_for(url, method, {header: "https://298101binance.com/"})
                    self.proxy.request(flow)
                    self.assertEqual(flow.response.status_code, 403)

    def test_allowed_hosts_do_not_allow_unrelated_paths_or_writes(self):
        cases = (
            ("GET", "https://www.google.com/search?q=test"),
            ("POST", "https://www.google.com/async/folae"),
            ("POST", "https://clients2.google.com/arbitrary"),
            ("GET", "https://clients2.google.com/domainreliability/upload"),
            ("DELETE", "https://browser-intake-us5-datadoghq.com/api/v2/rum"),
            ("POST", "https://beacons5.gvt3.com/domainreliability/upload/extra"),
            ("GET", "https://update.googleapis.com/service/update2/json"),
            ("POST", "https://update.googleapis.com/service/update2/other"),
            ("POST", "https://ab.chatgpt.com/v1/other"),
            ("GET", "https://ab.chatgpt.com/v1/rgstr"),
            ("POST", "https://o33249.ingest.us.sentry.io/api/other/envelope/"),
            ("GET", "https://oauthaccountmanager.googleapis.com/v1/issuetoken"),
            ("POST", "https://oauthaccountmanager.googleapis.com/v1/issuetoken/extra"),
            ("POST", "https://oauthaccountmanager.googleapis.com/v1/other"),
            ("GET", "https://google.com/"),
            ("POST", "https://google.com/.well-known/device-bound-sessions"),
            ("GET", "https://google.com/.well-known/device-bound-sessions/extra"),
        )
        for method, url in cases:
            with self.subTest(method=method, url=url):
                flow = flow_for(url, method)
                self.proxy.request(flow)
                self.assertEqual(flow.response.status_code, 403)

    def test_other_hosts_and_hostname_lookalikes_remain_blocked(self):
        for host in ("outside.invalid", "www.google.com.attacker.test",
                     "clients2.google.com.attacker.test", "beacons5.gvt3.com.attacker.test",
                     "unlisted.gvt2.com", "chatgpt.com.attacker.test",
                     "update.googleapis.com.attacker.test", "ab.chatgpt.com.attacker.test",
                     "oauthaccountmanager.googleapis.com.attacker.test", "google.com.attacker.test"):
            with self.subTest(host=host):
                flow = flow_for("https://" + host + "/domainreliability/upload", "POST")
                self.proxy.request(flow)
                self.assertEqual(flow.response.status_code, 403)
                self.assertIsNotNone(self.connect(self.proxy, host))

    def test_http_and_nonstandard_service_ports_remain_blocked(self):
        for url in ("http://www.google.com/async/folae",
                    "https://www.google.com:8443/async/folae",
                    "http://claude.ai/api/event_logging/v2/batch"):
            with self.subTest(url=url):
                flow = flow_for(url)
                self.proxy.request(flow)
                self.assertEqual(flow.response.status_code, 403)
                self.assertIsNotNone(self.connect(
                    self.proxy, flow.request.host, flow.request.port))

    def test_background_endpoints_do_not_allow_websocket_upgrades(self):
        flow = flow_for("https://www.google.com/async/folae", headers={"Upgrade": "websocket"})
        self.proxy.request(flow)
        self.assertEqual(flow.response.status_code, 403)

    def test_mock_origins_and_referrers_cannot_use_service_exceptions(self):
        for header in ("Origin", "Referer"):
            for host in ("mock.test", "inbox.cedarpostmail.net", "298101binance.com"):
                for url in (OBSERVED_REQUESTS[2][1], "https://api.anthropic.com/v1/messages",
                            "https://chatgpt.com/api/auth/session",
                            "https://update.googleapis.com/service/update2/json"):
                    with self.subTest(header=header, host=host, url=url):
                        flow = flow_for(url, "POST", {header: "https://" + host + "/"})
                        self.proxy.request(flow)
                        self.assertEqual(flow.response.status_code, 403)

    def test_manager_and_legacy_submission_still_stay_local(self):
        flow = flow_for("http://mock.test/__mock/sites")
        self.proxy.request(flow)
        self.assertEqual(flow.response.status_code, 200)
        flow = flow_for("https://298101binance.com/__mock/events", "POST",
                        {"Origin": "https://298101binance.com"})
        self.proxy.request(flow)
        self.assertEqual(flow.response.status_code, 200)
        self.assertFalse(json.loads(flow.response.content)["external_sent"])
        for host in ("mock.test", "inbox.cedarpostmail.net", "298101binance.com"):
            self.assertIsNotNone(self.connect(self.proxy, host))

    def make_recording(self, host, path):
        folder = Path(self.tmp.name) / host
        folder.mkdir()
        url = "https://" + host + path
        (folder / "bundle.json").write_text(json.dumps({
            "startUrl": url, "steps": [{"url": url, "html": "step-000.html"}],
        }), encoding="utf-8")
        (folder / "step-000.html").write_text(
            "<html><body><h1>LOCAL_REPLAY_MARKER</h1></body></html>", encoding="utf-8")
        (folder / "trace.har").write_text(json.dumps({"log": {"entries": []}}), encoding="utf-8")
        return folder

    def assert_recording_wins(self, proxy, host, path):
        proxy.logfile = Path(self.tmp.name) / "replay.jsonl"
        flow = flow_for("https://" + host + path)
        proxy.request(flow)
        self.assertEqual(flow.response.status_code, 200)
        self.assertIn(b"LOCAL_REPLAY_MARKER", flow.response.content)
        self.assertIsNotNone(self.connect(proxy, host))
        proxy.handle = mock.Mock()
        flow = flow_for(OBSERVED_REQUESTS[2][1], "POST", {"Origin": "https://" + host})
        proxy.request(flow)
        proxy.handle.assert_called_once_with(flow)

    def test_single_recording_wins_over_google_and_agent_live_exceptions(self):
        for host, path in (("www.google.com", "/async/folae"),
                           ("claude.ai", "/api/event_logging/v2/batch"),
                           ("chatgpt.com", "/api/auth/session"),
                           ("update.googleapis.com", "/service/update2/json"),
                           ("google.com", "/.well-known/device-bound-sessions"),
                           ("oauthaccountmanager.googleapis.com", "/v1/issuetoken")):
            with self.subTest(host=host), contextlib.redirect_stdout(io.StringIO()):
                folder = self.make_recording(host, path)
                proxy = self.recording_proxy.RecordedMockProxy(folder)
                self.assert_recording_wins(proxy, host, path)

    def test_mailbox_recording_wins_over_google_and_agent_live_exceptions(self):
        for host, path in (("www.google.com", "/async/folae"),
                           ("claude.ai", "/api/event_logging/v2/batch"),
                           ("chatgpt.com", "/api/auth/session"),
                           ("update.googleapis.com", "/service/update2/json"),
                           ("google.com", "/.well-known/device-bound-sessions"),
                           ("oauthaccountmanager.googleapis.com", "/v1/issuetoken")):
            with self.subTest(host=host), contextlib.redirect_stdout(io.StringIO()):
                folder = self.make_recording(host, path)
                with mock.patch.object(self.recording_proxy, "load_recording_directories",
                                       return_value=[folder]):
                    proxy = self.recording_proxy.ConfiguredMailboxProxy("unused.json")
                self.assert_recording_wins(proxy, host, path)

    def test_fixture_host_has_precedence_over_live_service_exceptions(self):
        self.proxy.site = types.SimpleNamespace(host="www.google.com")
        self.proxy.handle = mock.Mock()
        flow = flow_for("https://www.google.com/async/folae")
        self.proxy.request(flow)
        self.proxy.handle.assert_called_once_with(flow)
        self.assertIsNotNone(self.connect(self.proxy, "www.google.com"))


if __name__ == "__main__":
    unittest.main()
