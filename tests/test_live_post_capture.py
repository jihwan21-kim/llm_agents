"""Unit checks for opt-in browser capture POST policy without live traffic."""
import ast
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def isolated_function(path, function_name, scope=None):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches = [item for item in tree.body
               if isinstance(item, ast.FunctionDef) and item.name == function_name]
    if len(matches) != 1:
        raise AssertionError("Function not found: " + function_name)
    module = ast.Module(body=matches, type_ignores=[])
    context = {} if scope is None else dict(scope)
    exec(compile(module, str(path), "exec"), context)
    return context[function_name]


class LivePostCaptureTests(unittest.TestCase):
    def test_live_post_requires_explicit_opt_in(self):
        accept = isolated_function(
            ROOT / "automatic_capture.py", "capture_method_allowed"
        )
        for method in ("GET", "HEAD", "OPTIONS"):
            self.assertTrue(accept(method))
            self.assertTrue(accept(method, True))
        self.assertFalse(accept("POST"))
        self.assertTrue(accept("POST", True))
        self.assertTrue(accept("post", True))
        for method in ("PUT", "PATCH", "DELETE", "CONNECT"):
            self.assertFalse(accept(method))
            self.assertFalse(accept(method, True))

    def test_flag_is_passed_to_interceptor_and_recorded_in_metadata(self):
        source = (ROOT / "automatic_capture.py").read_text(encoding="utf-8")
        self.assertIn('"--allow-live-post"', source)
        self.assertIn("capture_method_allowed(method, args.allow_live_post)", source)
        self.assertIn('"livePostAllowed": args.allow_live_post', source)
        self.assertIn('route.continue_()', source)
        self.assertIn('route.abort()', source)
        # Network interception does not disable the rest of the recorder.
        self.assertIn('record_har_path=str(raw_har)', source)

    def test_live_posts_are_not_retained_in_har(self):
        # HAR sanitizer must still discard POST and authentication metadata
        # even if the capture browser has been allowed to send POST.
        sanitize = isolated_function(
            ROOT / "record_site.py", "sanitize_har", {"json": json}
        )
        with tempfile.TemporaryDirectory() as tmp:
            raw, clean = Path(tmp) / "raw.har", Path(tmp) / "trace.har"
            raw.write_text(json.dumps({"log": {"entries": [
                {"request": {
                    "method": "POST", "url": "https://example.test/submit",
                    "headers": [{"name": "Authorization", "value": "secret"}],
                    "postData": {"text": "secret"},
                }, "response": {"content": {"text": "private"}}},
                {"request": {
                    "method": "GET", "url": "https://example.test/style.css",
                    "headers": [{"name": "Cookie", "value": "secret"}],
                    "cookies": [{"name": "session", "value": "secret"}],
                    "queryString": [],
                }, "response": {
                    "headers": [{"name": "Set-Cookie", "value": "secret"}],
                    "cookies": [], "content": {
                        "mimeType": "text/css", "text": "body {margin:0}"
                    }
                }}
            ], "pages": [{"id": "potential-personal-title"}]}}),
                encoding="utf-8")
            self.assertEqual(sanitize(raw, clean), 1)
            result = json.loads(clean.read_text(encoding="utf-8"))
            self.assertEqual(len(result["log"]["entries"]), 1)
            self.assertEqual(result["log"]["pages"], [])
            item = result["log"]["entries"][0]
            self.assertEqual(item["request"]["method"], "GET")
            self.assertEqual(item["request"]["headers"], [])
            self.assertEqual(item["request"]["cookies"], [])
            self.assertEqual(item["response"]["headers"], [])
            self.assertNotIn("postData", item["request"])
            self.assertNotIn("secret", clean.read_text())


if __name__ == "__main__":
    unittest.main()
