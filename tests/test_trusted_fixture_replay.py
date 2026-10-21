"""Tests for the verified, bundled, network-free JavaScript fixture."""
import json
from pathlib import Path
import tempfile
import unittest

from capture_replay import CaptureReplay, TRUSTED_JS_ASSETS
from gym.build_js_fixture_recording import build_fixture_recording


class PackagedFixtureTests(unittest.TestCase):
    def test_trusted_fixture_preserves_reviewed_external_js(self):
        with tempfile.TemporaryDirectory() as temp:
            root = build_fixture_recording(Path(temp) / "recording")
            static = CaptureReplay(root)
            static_html = static.respond("GET", "/")[1].decode()
            self.assertNotIn(TRUSTED_JS_ASSETS, static_html)
            self.assertIn("/__mock_capture/sim.js", static_html)

            replay = CaptureReplay(root, trusted_fixture_js=True)
            html = replay.respond("GET", "/")[1].decode()
            self.assertIn(TRUSTED_JS_ASSETS, html)
            self.assertNotIn("/__mock_capture/sim.js", html)
            self.assertIn("/__mock_capture/assets/", html)
            self.assertEqual(len(replay.trusted_js_sources), 1)
            digest = next(iter(replay.trusted_js_sources))
            status, script, mime = replay.respond("GET", TRUSTED_JS_ASSETS + digest)
            self.assertEqual(status, 200)
            self.assertEqual(mime, "text/javascript; charset=utf-8")
            approved = (Path(__file__).resolve().parents[1] /
                        "gym/fixtures/js-demo/app.js").read_bytes()
            self.assertEqual(script, approved)
            self.assertEqual(replay.respond("HEAD", TRUSTED_JS_ASSETS + digest)[1], b"")
            self.assertEqual(replay.respond("GET", TRUSTED_JS_ASSETS + "missing")[0], 404)
            self.assertEqual(replay.respond("POST", TRUSTED_JS_ASSETS + digest)[0], 405)

    def test_trusted_mode_is_fixed_to_approved_fixture_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = build_fixture_recording(temp)
            bundle_file = root / "bundle.json"
            bundle = json.loads(bundle_file.read_text())
            bundle["startUrl"] = "https://another.example.test/"
            bundle_file.write_text(json.dumps(bundle))
            with self.assertRaises(ValueError):
                CaptureReplay(root, trusted_fixture_js=True)


if __name__ == "__main__":
    unittest.main()
