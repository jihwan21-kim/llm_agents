"""Proof that exported DevTools sources are unchanged, inert and path-safe."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from export_recorded_js_for_devtools import (
    OUTPUT_FOLDER, README, MANIFEST, clean_filename, export_for_devtools,
)


class DevtoolsExportTests(unittest.TestCase):
    def create_capture(self, root):
        root = Path(root)
        script_a = b"const a=23;\n"
        script_b = b"export const b=44;\n"
        (root / "bundle.json").write_text(json.dumps({
            "startUrl": "https://example.test/",
            "steps": [{"url": "https://example.test/", "html": "step-000.html"}],
            "transitions": [],
        }), encoding="utf-8")
        markup = ('<!doctype html><html><body><h1>Sample</h1>'
                  '<script src="https://example.test/a/main.js"></script>'
                  '</body></html>')
        (root / "step-000.html").write_text(markup, encoding="utf-8")
        entries = [
            {"request": {"method": "GET", "url": "https://example.test/a/main.js?token=should-not-appear"},
             "response": {"content": {"mimeType": "text/javascript",
                                      "text": script_a.decode()}}},
            {"request": {"method": "GET", "url": "https://cdn.example.test/b/main.mjs"},
             "response": {"content": {"mimeType": "application/javascript",
                                      "text": base64.b64encode(script_b).decode(),
                                      "encoding": "base64"}}},
        ]
        (root / "trace.har").write_text(
            json.dumps({"log": {"entries": entries}}), encoding="utf-8")
        return markup, [script_a, script_b]

    def test_saved_sources_are_original_bytes_and_not_page_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            original_markup, scripts = self.create_capture(temp)
            dest, manifest = export_for_devtools(temp)
            self.assertEqual(dest, Path(temp) / OUTPUT_FOLDER)
            self.assertEqual(manifest["saved_count"], 2)
            self.assertEqual(manifest["skipped_due_to_limits"], 0)
            self.assertFalse(manifest["captured_js_executed_by_replay"])
            self.assertEqual(len({a["file"] for a in manifest["scripts"]}), 2)
            for entry, raw in zip(manifest["scripts"], scripts):
                self.assertEqual((dest / entry["file"]).read_bytes(), raw)
                self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertFalse(entry["executed"])
                self.assertTrue(entry["file"].startswith("archived_main_"))
            self.assertTrue(manifest["scripts"][1]["file"].endswith(".mjs"))
            text = (dest / MANIFEST).read_text()
            self.assertNotIn("token=should-not-appear", text)
            self.assertEqual(Path(temp, "step-000.html").read_text(), original_markup)
            self.assertNotIn("sim.js", "".join(a["file"] for a in manifest["scripts"]))
            self.assertIn("Sources > Page", (dest / README).read_text())

            # Idempotent: re-export neither alters sources nor adds duplicates.
            _, repeated = export_for_devtools(temp)
            self.assertEqual(repeated, manifest)

    def test_traversal_and_strange_filenames_are_not_preserved(self):
        digest = "a" * 64
        for malicious in (
            "../../outside.js", "C:\\\\Windows\\\\bad.js",
            "..\\\\foo.js", "\u0000.js", "<script>.js",
        ):
            filename = clean_filename(malicious, digest)
            self.assertNotIn("/", filename)
            self.assertNotIn("\\\\", filename)
            self.assertNotIn("<", filename)
            self.assertTrue(filename.startswith("archived_"))
            self.assertTrue(filename.endswith(".js"))

    def test_empty_archive_reports_no_sources_and_does_not_run_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            self.create_capture(temp)
            (Path(temp) / "trace.har").write_text(
                json.dumps({"log": {"entries": []}}), encoding="utf-8")
            dest, manifest = export_for_devtools(temp)
            self.assertEqual(manifest["saved_count"], 0)
            self.assertEqual(list(dest.glob("archived_*.js")), [])
            self.assertTrue((dest / MANIFEST).is_file())

    def test_refuses_symlink_export(self):
        with tempfile.TemporaryDirectory() as temp:
            self.create_capture(temp)
            elsewhere = Path(temp) / "other"
            elsewhere.mkdir()
            export = Path(temp) / OUTPUT_FOLDER
            try:
                export.symlink_to(elsewhere, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable")
            with self.assertRaisesRegex(ValueError, "symlinked"):
                export_for_devtools(temp)


if __name__ == "__main__":
    unittest.main()
