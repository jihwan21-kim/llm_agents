"""Recorded JavaScript can be inspected as text but is never executed.

All fixtures are local synthetic data and do not access the network.
"""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from capture_replay import (
    CaptureReplay, SCRIPT_INDEX, SCRIPT_INDEX_JSON, SCRIPT_SOURCE,
    is_javascript_response
)


class SourceInspectionTests(unittest.TestCase):
    def _recording(self, location):
        base = Path(location)
        (base / "bundle.json").write_text(json.dumps({
            "startUrl": "https://fixture.test/home",
            "steps": [{"url": "https://fixture.test/home", "html": "step-000.html"}],
            "transitions": []
        }), encoding="utf-8")
        (base / "step-000.html").write_text(
            '<html><body><main><p>Hello</p>'
            '<script>window.injected=true</script>'
            '<script src="/app.js"></script></main></body></html>',
            encoding="utf-8"
        )
        js = b"document.querySelector('#out').textContent = 'synthetic';"
        entries = [
            {"request": {"method": "GET", "url": "https://fixture.test/app.js?secret=never-export"},
             "response": {"content": {"mimeType": "application/javascript",
                                      "text": js.decode()}}},
            {"request": {"method": "GET", "url": "https://cdn.fixture.test/bundle.mjs"},
             "response": {"content": {"mimeType": "text/plain",
                                      "text": base64.b64encode(b"export const test=1").decode(),
                                      "encoding": "base64"}}},
            {"request": {"method": "GET", "url": "https://fixture.test/app.js?secret=never-export"},
             "response": {"content": {"mimeType": "application/javascript",
                                      "text": js.decode()}}},
            {"request": {"method": "POST", "url": "https://fixture.test/action.js"},
             "response": {"content": {"mimeType": "text/javascript",
                                      "text": "not exported"}}},
            {"request": {"method": "GET", "url": "https://fixture.test/bad.js"},
             "response": {"content": {"mimeType": "text/html",
                                      "text": "<script>alert(1)</script>"}}}
        ]
        (base / "trace.har").write_text(json.dumps({"log": {"entries": entries}}),
                                        encoding="utf-8")
        return js

    def test_sources_are_read_only_and_unavailable_in_original_page(self):
        with tempfile.TemporaryDirectory() as location:
            js = self._recording(location)
            replay = CaptureReplay(location)
            self.assertEqual(len(replay.script_index), 2)
            digest = hashlib.sha256(js).hexdigest()
            self.assertEqual(replay.script_index[0]["id"], digest)
            self.assertEqual(replay.script_index[0]["name"], "app.js")
            self.assertEqual(replay.script_index[0]["origin"], "recorded")
            self.assertEqual(replay.script_index[1]["origin"], "external")

            status, page, mime = replay.respond("GET", "/home")
            self.assertEqual(status, 200)
            self.assertNotIn(b"app.js", page)
            self.assertNotIn(b"window.injected", page)
            self.assertIn(b"/__mock_capture/sim.js", page)
            self.assertNotIn(b"/__mock_capture/scripts", page)

            status, manifest, mimetype = replay.respond("GET", SCRIPT_INDEX_JSON)
            self.assertEqual(status, 200)
            self.assertEqual(mimetype, "application/json; charset=utf-8")
            parsed = json.loads(manifest)
            self.assertFalse(parsed["execution"])
            self.assertEqual(len(parsed["scripts"]), 2)
            self.assertNotIn("never-export", manifest.decode())

            status, listing, mime = replay.respond("GET", SCRIPT_INDEX)
            self.assertEqual(status, 200)
            self.assertIn(b"read-only", listing)
            self.assertIn(digest.encode(), listing)
            self.assertNotIn(b"<script", listing)
            self.assertNotIn(b"never-export", listing)

            status, raw, mime = replay.respond("GET", SCRIPT_SOURCE + digest)
            self.assertEqual((status, raw), (200, js))
            self.assertEqual(mime, "text/plain; charset=utf-8")
            self.assertEqual(replay.respond("HEAD", SCRIPT_SOURCE + digest)[1], b"")
            self.assertEqual(replay.respond("GET", SCRIPT_SOURCE + "arbitrary")[0], 404)
            self.assertEqual(replay.respond("POST", SCRIPT_SOURCE + digest)[0], 405)

    def test_limits_and_content_type_gate(self):
        self.assertTrue(is_javascript_response("https://fixture.test/foo.js", "text/javascript"))
        self.assertTrue(is_javascript_response("https://fixture.test/foo.mjs", "text/plain"))
        self.assertFalse(is_javascript_response("https://fixture.test/foo.js", "text/html"))
        self.assertFalse(is_javascript_response("https://fixture.test/foo.js", "application/json"))
        with tempfile.TemporaryDirectory() as location:
            self._recording(location)
            p = Path(location) / "trace.har"
            har = json.loads(p.read_text())
            har["log"]["entries"].append({
                "request": {"method": "GET", "url": "https://fixture.test/huge.js"},
                "response": {"content": {"mimeType": "text/javascript",
                                         "text": "A" * (1024 * 1024 + 1)}}
            })
            p.write_text(json.dumps(har))
            replay = CaptureReplay(location)
            self.assertEqual(replay.script_sources_skipped, 1)
            self.assertEqual(len(replay.script_index), 2)


if __name__ == "__main__":
    unittest.main()
