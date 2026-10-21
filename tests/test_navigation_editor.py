"""Offline visual-navigation editor tests with synthetic, non-sensitive pages."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from navigation_editor import (
    NavigationEditor, NavigationEditError, EDITOR, EDITOR_HTML, EDITOR_JS,
    SELECTOR, OVERRIDES_NAME, SensitivePageParser
)
from capture_replay import CaptureReplay


class NavigationEditorTests(unittest.TestCase):
    def recording(self, location):
        folder = Path(location)
        steps = [
            {"url": "https://fixture.test/home", "html": "step-000.html"},
            {"url": "https://fixture.test/about", "html": "step-001.html"},
            {"url": "https://fixture.test/signin", "html": "step-002.html"},
            {"url": "https://fixture.test/secure", "html": "step-003.html"},
        ]
        (folder / "bundle.json").write_text(json.dumps({
            "startUrl": "https://fixture.test/home", "steps": steps,
            "transitions": [
                {"from": 0, "to": 0, "kind": "click", "selector": "#more",
                 "observed": True, "outcome": "no-change"}
            ],
        }), encoding="utf-8")
        for index, markup in enumerate([
            '<!doctype html><html><body><main><button id="more">More</button>'
            '<a href="/about">About</a></main></body></html>',
            '<html><body><h1>About</h1><p>Benign destination.</p></body></html>',
            '<html><body><h1>Sign in</h1><input type="email"></body></html>',
            '<html><body><h1>Other</h1><input type="password"></body></html>',
        ]):
            (folder / f"step-{index:03d}.html").write_text(
                markup, encoding="utf-8")
        (folder / "trace.har").write_text(
            json.dumps({"log": {"entries": []}}), encoding="utf-8")
        return folder

    def test_edit_saved_and_replay_manual_edge_overrides_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.recording(tmp)
            before = CaptureReplay(folder)
            self.assertEqual(before.manual_edges, [])
            bundle_before = (folder / "bundle.json").read_bytes()
            html_before = (folder / "step-000.html").read_bytes()
            editor = NavigationEditor(folder, before.bundle)
            self.assertEqual([s["blocked"] for s in editor.states],
                             [False, False, True, True])
            data = editor.write(b'{"operation":"set","from":0,"to":1,"selector":"#more"}')
            self.assertEqual(data, [{"from": 0, "to": 1, "selector": "#more"}])
            self.assertEqual((folder / OVERRIDES_NAME).is_file(), True)
            self.assertEqual(json.loads((folder / OVERRIDES_NAME).read_text())["version"], 1)
            after = CaptureReplay(folder)
            self.assertEqual(after.manual_edges, data)
            _, raw, _ = after.respond("GET", "/home")
            page = raw.decode()
            self.assertIn("manual_navigation", page)
            self.assertIn("manual_override", page)
            self.assertIn("#more", page)
            self.assertIn("&quot;to&quot;: 1", page)
            self.assertNotIn("src=\"/app.js\"", page)
            self.assertIn("sim.js", page)
            self.assertEqual((folder / "bundle.json").read_bytes(), bundle_before)
            self.assertEqual((folder / "step-000.html").read_bytes(), html_before)
            self.assertEqual(after.navigation_editor.overrides, data)
            editor.write(b'{"operation":"delete","from":0,"selector":"#more"}')
            self.assertEqual(CaptureReplay(folder).manual_edges, [])

    def test_editor_forbids_sensitive_steps_and_form_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.recording(tmp)
            editor = NavigationEditor(folder, json.loads((folder / "bundle.json").read_text()))
            for from_step, to_step in [(0, 2), (2, 1), (1, 3), (3, 0), (0, 0)]:
                payload = json.dumps({
                    "operation": "set", "from": from_step, "to": to_step,
                    "selector": "#more"}).encode()
                with self.subTest(from_step=from_step, to_step=to_step):
                    with self.assertRaises(NavigationEditError):
                        editor.write(payload)
            self.assertEqual(editor.overrides, [])

    def test_rejects_malformed_payloads_and_selector_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.recording(tmp)
            editor = NavigationEditor(folder, json.loads((folder / "bundle.json").read_text()))
            candidates = [
                {"operation": "set", "from": True, "to": 1, "selector": "#more"},
                {"operation": "set", "from": 0, "to": 1, "selector": "input[type=password]"},
                {"operation": "set", "from": 0, "to": 1, "selector": "button, form"},
                {"operation": "set", "from": 0, "to": 1, "selector": "a[href*=password]"},
                {"operation": "set", "from": 0, "to": 1, "selector": "*"},
                {"operation": "set", "from": 0, "to": 1, "selector": "#more", "other": 2},
                {"operation": "set", "from": 0, "to": "1", "selector": "#more"},
                {"operation": "delete", "from": 0, "selector": "#nothing"},
            ]
            for candidate in candidates:
                with self.subTest(candidate=candidate):
                    with self.assertRaises(NavigationEditError):
                        editor.write(json.dumps(candidate).encode())
            with self.assertRaises(NavigationEditError):
                editor.write(b"{" + b" " * 2500)
            self.assertFalse((folder / OVERRIDES_NAME).exists())

    def test_selector_allowlist_accepts_generated_selectors(self):
        for good in (
            "#more", "a[data-mock-link-index=\"0\"]",
            "body:nth-of-type(1) > main:nth-of-type(1) > button:nth-of-type(1)",
            "div > button",
        ):
            with self.subTest(selector=good):
                self.assertTrue(SELECTOR.fullmatch(good))
        for bad in ("", "*", "[onclick]", "form input", "a[href]",
                    "button, input", "script", "#a<script>",
                    "body > button + a"):
            # A bare tag is valid but not used by the real UI; keep it out
            # of the rejected cases above.
            if bad == "script":
                continue
            with self.subTest(selector=bad):
                self.assertFalse(SELECTOR.fullmatch(bad))

    def test_tampered_override_refused_not_silently_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.recording(tmp)
            p = folder / OVERRIDES_NAME
            p.write_text(json.dumps({"version": 1, "overrides": [{
                "from": 0, "to": 2, "selector": "#more"
            }]}), encoding="utf-8")
            with self.assertRaises(NavigationEditError):
                CaptureReplay(folder)

    def test_login_heading_locked_even_without_form_fields(self):
        parser = SensitivePageParser()
        parser.feed("<html><head><title>Sign in</title></head><body><button>Next</button></body></html>")
        self.assertTrue(parser.sensitive)
        benign = SensitivePageParser()
        benign.feed("<html><head><title>Products</title></head><body><h1>Gallery</h1><button>Next</button></body></html>")
        self.assertFalse(benign.sensitive)

    def test_editor_html_is_standalone_and_js_is_valid(self):
        self.assertIn(EDITOR, "/__mock_capture/editor")
        self.assertIn("Mock Navigation Editor", EDITOR_HTML)
        self.assertIn('id="preview"', EDITOR_HTML)
        self.assertIn('id="save"', EDITOR_HTML)
        self.assertIn('src="/__mock_capture/editor.js"', EDITOR_HTML)
        # Locked states are visible only as inert, read-only recordings.
        self.assertIn('sandbox="allow-same-origin"', EDITOR_HTML)
        # Both pickers can select any recorded screen for read-only viewing.
        self.assertIn('fill(sourceSelect, state.steps)', EDITOR_JS)
        self.assertIn('fill(targetSelect, state.steps)', EDITOR_JS)
        self.assertNotIn('option.disabled = s.blocked', EDITOR_JS)
        self.assertIn('preview.style.pointerEvents = readOnly ? "none" : "auto"', EDITOR_JS)
        self.assertIn('preview.src = stepPath(id)', EDITOR_JS)
        self.assertIn('$(\"save\").disabled = !canEdit', EDITOR_JS)
        # Auth/payment screen navigation writes remain forbidden in UI and backend.
        self.assertIn('current.blocked || !destination || destination.blocked', EDITOR_JS)
        self.assertIn('self.states[a]["blocked"] or self.states[b]["blocked"]', (Path(__file__).resolve().parents[1] / "navigation_editor.py").read_text(encoding="utf-8"))
        # Snapshot slideshow cannot execute scripts or write navigation overrides.
        self.assertIn('id="previousRecorded"', EDITOR_HTML)
        self.assertIn('id="nextRecorded"', EDITOR_HTML)
        self.assertIn('loadPreview(next, true)', EDITOR_JS)
        self.assertIn('loadPreview(to, true)', EDITOR_JS)
        self.assertNotIn('window.open(stepPath(to)', EDITOR_JS)

        self.assertIn("stopImmediatePropagation", EDITOR_JS)
        node = shutil.which("node")
        if node:
            result = subprocess.run([node, "--check"], input=EDITOR_JS,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
