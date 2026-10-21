"""Multi-recording inbox config tests; all data and transport are synthetic."""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from mailbox_recordings import load_recording_directories
from browser_mail import BrowserMailbox


def make_recording(directory, host):
    directory.mkdir(parents=True, exist_ok=True)
    url = "https://" + host + "/entry"
    (directory / "bundle.json").write_text(json.dumps({
        "startUrl": url,
        "steps": [
            {"url": url, "html": "step-000.html"},
            {"url": "https://" + host + "/next", "html": "step-001.html"},
            {"url": "https://" + host + "/login", "html": "step-002.html"}
        ],
        "transitions": [
            {"from": 0, "to": 1, "selector": "#continue",
             "kind": "click", "outcome": "changed", "observed": True},
            {"from": 1, "to": 2, "selector": "#enter",
             "kind": "click", "outcome": "changed", "observed": True},
            {"from": 0, "to": 2, "selector": "#continue",
             "kind": "click", "outcome": "changed", "observed": True}
        ],
    }), encoding="utf-8")
    (directory / "step-000.html").write_text(
        "<!doctype html><html><body><h1>Offline test</h1>"
        "<button id='continue' onclick='steal()'>Continue</button>"
        "<script>window.alert('untrusted')</script></body></html>",
        encoding="utf-8")
    (directory / "step-001.html").write_text(
        "<!doctype html><html><body><h1>Next</h1>"
        "<button id='enter'>Continue</button></body></html>",
        encoding="utf-8")
    (directory / "step-002.html").write_text(
        "<!doctype html><html><body><h1>Sign in</h1>"
        "<form><input type='password'><button>Continue</button></form></body></html>",
        encoding="utf-8")
    (directory / "trace.har").write_text(
        json.dumps({"log": {"entries": []}}), encoding="utf-8")


class MailboxRecordingConfigTests(unittest.TestCase):
    def make_manifest(self, root, entries):
        manifest = root / "mailbox-recordings.json"
        manifest.write_text(json.dumps({"recordings": entries}), encoding="utf-8")
        return manifest

    def test_latest_child_folder_and_missing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "recordings" / "alpha"
            older = parent / "run-old"
            newer = parent / "run-new"
            make_recording(older, "older.example.test")
            make_recording(newer, "newer.example.test")
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))
            direct = root / "recordings" / "beta"
            make_recording(direct, "beta.example.test")
            config = self.make_manifest(root, [
                "recordings/alpha", "recordings/missing", "recordings/beta"
            ])
            with mock.patch("builtins.print"):
                selected = load_recording_directories(config, root=root)
            self.assertEqual(selected, [newer.resolve(), direct.resolve()])

    def test_rejects_path_traversal_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "recordings").mkdir()
            for entry in ("../secret", "recordings/../private",
                          "/etc/passwd", "C:\\Users\\user\\secret",
                          "recordings//bad", "somewhere/outside"):
                with self.subTest(entry=entry):
                    conf = self.make_manifest(root, [entry])
                    with self.assertRaises(ValueError):
                        load_recording_directories(conf, root=root)

    def test_rejects_symlink_that_leaves_recordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "recordings").mkdir()
            outside = root / "elsewhere"
            make_recording(outside, "outside.example.test")
            link = root / "recordings" / "shortcut"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks not available on this platform")
            conf = self.make_manifest(root, ["recordings/shortcut"])
            with self.assertRaises(ValueError):
                load_recording_directories(conf, root=root)

    def test_inbox_entries_retain_separate_saved_page_hosts(self):
        inbox = BrowserMailbox([
            {"host": "alpha.example.test", "entry": "/entry", "id": "recording-preview"},
            {"host": "beta.example.test", "entry": "/entry", "id": "recording-preview"},
        ])
        self.assertEqual(len(inbox.messages), 2)
        self.assertEqual(inbox.resolve("1"), "https://alpha.example.test/entry")
        self.assertEqual(inbox.resolve("2"), "https://beta.example.test/entry")
        self.assertIn("alpha.example.test", inbox.messages[0]["subject"])
        self.assertIn("beta.example.test", inbox.messages[1]["subject"])
        self.assertTrue(all("Offline snapshot" in m["subject"] for m in inbox.messages))

    def test_proxy_serves_both_hosts_with_safe_clicks_but_no_form_writes(self):
        from mailbox_recordings import ROOT
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            # Use repo-local folder for real loader, but keep fixtures in tmp:
            # patch only root argument resolution (no external host access).
            root = Path(tmp)
            a = root / "recordings" / "alpha"
            b = root / "recordings" / "beta"
            make_recording(a, "alpha.example.test")
            make_recording(b, "beta.example.test")
            config = self.make_manifest(root, ["recordings/alpha", "recordings/beta"])

            class FakeResponse:
                @staticmethod
                def make(status, body, headers):
                    return types.SimpleNamespace(status_code=status, content=body,
                                                 headers=dict(headers))

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
                "mitmproxy": mitmproxy,
                "mitmproxy.http": http,
                "mitmproxy.options": options,
                "mitmproxy.tools": tools,
                "mitmproxy.tools.dump": dump
            }):
                import run_capture_proxy
                with mock.patch.object(run_capture_proxy,
                                       "load_recording_directories",
                                       side_effect=lambda path: load_recording_directories(path, root=root)):
                    proxy = run_capture_proxy.ConfiguredMailboxProxy(config)
                self.assertEqual(set(proxy.captures), {
                    "alpha.example.test", "beta.example.test"
                })
                self.assertEqual(len(proxy.mailbox.messages), len(proxy_app_sites()) + 2)

                def fetch(host, path, method="GET", body=None):
                    headers = {}
                    if body is not None:
                        headers = {"Origin": "https://" + host,
                                   "Content-Type": "application/json"}
                    request = types.SimpleNamespace(
                        host=host, path=path, port=443, method=method,
                        headers=headers,
                        raw_content=json.dumps(body).encode() if body is not None else b""
                    )
                    flow = types.SimpleNamespace(request=request, response=None)
                    proxy.handle(flow)
                    return flow.response

                for host in proxy.captures:
                    with self.subTest(host=host):
                        response = fetch(host, "/entry")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(b"Offline test", response.content)
                        self.assertIn("script-src 'self'",
                                      response.headers["Content-Security-Policy"])
                        self.assertIn("form-action 'none'",
                                      response.headers["Content-Security-Policy"])
                        self.assertEqual(fetch(host, "/__mock_capture/sim.js").status_code, 200)
                        self.assertEqual(fetch(host, "/entry", "POST").status_code, 405)
                        click = {"kind": "button_click", "step": 0, "to": 1,
                                 "selector": "#continue", "filled_types": []}
                        event = fetch(host, "/__mock_capture/event", "POST", click)
                        self.assertEqual(event.status_code, 200)
                        self.assertEqual(json.loads(event.content)["to"], 1)
                        self.assertTrue(json.loads(event.content)["observed"])
                        self.assertIn(b"Next", fetch(host, "/next?_step=1").content)
                        # Authentication destination and form submissions
                        # remain non-replayable, regardless of saved edges.
                        click["to"] = 2
                        self.assertEqual(fetch(host, "/__mock_capture/event",
                                               "POST", click).status_code, 400)
                        click = {"kind": "button_click", "step": 1, "to": 2,
                                 "selector": "#enter", "filled_types": []}
                        self.assertEqual(fetch(host, "/__mock_capture/event",
                                               "POST", click).status_code, 400)
                        bad = {"kind": "form_submit", "step": 0, "to": 1,
                               "selector": "#continue", "filled_types": []}
                        self.assertEqual(fetch(host, "/__mock_capture/event",
                                               "POST", bad).status_code, 400)
                        self.assertIn("script-src 'none'",
                                      fetch(host, "/login?_step=2").headers["Content-Security-Policy"])
                        self.assertEqual(fetch(host, "/login", "POST").status_code, 405)
                entries = json.loads(fetch("inbox.cedarpostmail.net", "/api/messages").content)
                self.assertEqual(len(entries), len(proxy_app_sites()) + 2)
                for i, host in enumerate(proxy.captures, start=len(proxy_app_sites())+1):
                    redirect = fetch("inbox.cedarpostmail.net", "/open/" + str(i))
                    self.assertEqual(redirect.status_code, 302)
                    self.assertEqual(redirect.headers["Location"], "https://" + host + "/entry")


def proxy_app_sites():
    import proxy_app
    return proxy_app.SITES


if __name__ == "__main__":
    unittest.main()
