"""Local-only regression tests for opt-in agent source inspection.

Never activates captured JavaScript; all sample contents are harmless.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from capture_replay import CaptureReplay, SCRIPT_INDEX, SCRIPT_INDEX_JSON, SCRIPT_SOURCE


class AgentJsSourceInspectionTests(unittest.TestCase):
    def recording(self, root):
        root = Path(root)
        harmless_js = b"const number = 42;\nconsole.info(number);\n"
        (root / "step-000.html").write_text(
            '<!doctype html><html><body><h1>Sample</h1>'
            '<script src="/assets/site.js"></script></body></html>',
            encoding="utf-8")
        (root / "bundle.json").write_text(json.dumps({
            "startUrl": "https://synthetic.test/",
            "steps": [{"url": "https://synthetic.test/", "html": "step-000.html"}],
            "transitions": []
        }), encoding="utf-8")
        (root / "trace.har").write_text(json.dumps({"log": {"entries": [
            {"request": {"method": "GET",
                          "url": "https://synthetic.test/assets/site.js?private_query=hidden"},
             "response": {"content": {"mimeType": "text/javascript",
                                      "text": harmless_js.decode("utf-8")}}},
        ]}}), encoding="utf-8")
        return harmless_js

    def test_opt_in_link_exposes_real_har_js_for_reading(self):
        with tempfile.TemporaryDirectory() as temp:
            original = self.recording(temp)
            replay = CaptureReplay(temp, agent_js_inspection=True)
            page = replay.respond("GET", "/")[1].decode("utf-8")
            self.assertIn("Inspect recorded JavaScript (read-only)", page)
            self.assertIn(SCRIPT_INDEX, page)
            self.assertIn("/__mock_capture/sim.js", page)
            self.assertNotIn("private_query", page)
            self.assertNotIn("const number = 42", page)
            index = replay.respond("GET", SCRIPT_INDEX)
            self.assertEqual(index[0], 200)
            self.assertIn(b"/assets/site.js", index[1])
            self.assertNotIn(b"private_query", index[1])
            data = json.loads(replay.respond("GET", SCRIPT_INDEX_JSON)[1])
            self.assertFalse(data["execution"])
            self.assertEqual(len(data["scripts"]), 1)
            script = data["scripts"][0]
            digest = hashlib.sha256(original).hexdigest()
            self.assertEqual(script["id"], digest)
            self.assertEqual(script["path"], "/assets/site.js")
            self.assertEqual(script["source_url"], SCRIPT_SOURCE + digest)
            self.assertNotIn("private_query", json.dumps(data))
            status, body, mime = replay.respond("GET", script["source_url"])
            self.assertEqual((status, body, mime),
                             (200, original, "text/plain; charset=utf-8"))
            self.assertEqual(replay.respond("HEAD", script["source_url"])[1], b"")

    def test_default_baseline_has_no_source_access_link(self):
        with tempfile.TemporaryDirectory() as temp:
            self.recording(temp)
            replay = CaptureReplay(temp)
            page = replay.respond("GET", "/")[1].decode("utf-8")
            self.assertNotIn("mock-research-source-link", page)
            self.assertNotIn(SCRIPT_INDEX, page)
            self.assertNotIn("<script src=\"/assets/site.js\"", page)
            self.assertEqual(len(replay.script_index), 1)
            self.assertEqual(replay.respond("GET", SCRIPT_INDEX)[0], 200)

    def test_read_only_sources_never_allow_write_or_unknown_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            self.recording(temp)
            replay = CaptureReplay(temp, agent_js_inspection=True)
            digest = replay.script_index[0]["id"]
            self.assertEqual(replay.respond("POST", SCRIPT_SOURCE + digest)[0], 405)
            self.assertEqual(replay.respond("GET", SCRIPT_SOURCE + "wronghash")[0], 404)


if __name__ == "__main__":
    unittest.main()
