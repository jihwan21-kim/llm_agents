"""Offline fidelity preflight regressions using only synthetic data."""
import json
from pathlib import Path
import tempfile
import unittest

from fidelity_audit import audit_recording


class FidelityPreflightTests(unittest.TestCase):
    def fixture(self, root):
        path = Path(root)
        (path / "bundle.json").write_text(json.dumps({
            "startUrl": "https://demo.example.test/home",
            "steps": [
                {"url": "https://demo.example.test/home", "html": "step-000.html"},
                {"url": "https://demo.example.test/cart", "html": "step-001.html"},
            ],
            "transitions": [
                {"from": 0, "to": 1, "kind": "click",
                 "observed": True, "blocked_write": True},
                {"from": 1, "to": 1, "kind": "dom_settle",
                 "observed": False, "temporal_observation": True},
            ],
        }), encoding="utf-8")
        (path / "step-000.html").write_text(
            '<html><head><script src="/app.js?private=DO_NOT_EXPOSE"></script>'
            '<script>window.untrusted=1</script></head><body>'
            '<iframe src="https://nowhere.test/"></iframe>'
            '<form><input type="text" onfocus="inert()"></form>'
            '</body></html>', encoding="utf-8")
        (path / "step-001.html").write_text(
            "<html><body><h1>Cart</h1></body></html>", encoding="utf-8")
        (path / "trace.har").write_text(json.dumps({"log": {"entries": [
            {"request": {"method": "GET", "url": "https://demo.example.test/app.js?private=DO_NOT_EXPOSE"},
             "response": {"content": {"mimeType": "text/javascript", "text": "alert('untrusted');"}}},
            {"request": {"method": "GET", "url": "https://cdn.example.test/no-body.js"},
             "response": {"content": {"mimeType": "application/javascript"}}},
            {"request": {"method": "POST", "url": "https://demo.example.test/submit"},
             "response": {"content": {"mimeType": "application/json", "text": "secret=DO_NOT_EXPOSE"}}},
        ]}}), encoding="utf-8")

    def test_report_discloses_limitations_without_source_or_payload(self):
        with tempfile.TemporaryDirectory() as d:
            self.fixture(d)
            report = audit_recording(d)
            observed = report["observations"]
            self.assertFalse(report["claimed_full_original_equivalence"])
            self.assertEqual(report["mode"], "sanitized_static_snapshot_replay")
            self.assertEqual(observed["snapshots"], 2)
            self.assertEqual(observed["unique_paths"], 2)
            self.assertEqual(observed["observed_action_edges"], 1)
            self.assertEqual(observed["unverified_dom_edges"], 1)
            self.assertEqual(observed["blocked_write_edges"], 1)
            self.assertEqual(observed["inline_script_elements"], 1)
            self.assertEqual(observed["inline_event_handler_attributes"], 1)
            self.assertEqual(observed["frame_elements"], 1)
            self.assertEqual(observed["distinct_external_script_urls_in_snapshots"], 1)
            self.assertEqual(observed["script_urls_with_har_response_body"], 1)
            self.assertEqual(observed["script_urls_without_har_response_body"], 0)
            self.assertEqual(observed["javascript_har_entries"], 2)
            self.assertEqual(observed["javascript_har_entries_with_body"], 1)
            self.assertEqual(observed["cross_origin_javascript_urls_in_har"], 1)
            behavior = report["replay_behavior"]
            self.assertFalse(behavior["original_external_javascript_executes"])
            self.assertFalse(behavior["original_inline_javascript_executes"])
            self.assertFalse(behavior["original_backend_available"])
            self.assertFalse(behavior["upstream_network_allowed"])
            text = json.dumps(report)
            self.assertNotIn("DO_NOT_EXPOSE", text)
            self.assertNotIn("untrusted", text)

    def test_uncaptured_declared_script_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            self.fixture(d)
            (Path(d) / "trace.har").write_text(json.dumps({"log": {"entries": []}}))
            report = audit_recording(d)
            self.assertEqual(
                report["observations"]["script_urls_without_har_response_body"], 1)

    def test_blocks_snapshot_path_escape(self):
        with tempfile.TemporaryDirectory() as d:
            self.fixture(d)
            p = Path(d) / "bundle.json"
            bundle = json.loads(p.read_text())
            bundle["steps"][0]["html"] = "../not-in-directory.html"
            p.write_text(json.dumps(bundle))
            with self.assertRaises((ValueError, FileNotFoundError)):
                audit_recording(d)


if __name__ == "__main__":
    unittest.main()
