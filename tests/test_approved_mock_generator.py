"""Regression tests for approved per-site JS mock generation and validation."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from gym.build_approved_mock import (
    GENERATED, MANIFEST, build_approved_mock, load_approved_mock, output_path,
)
from gym.functional_sites import FunctionalSite, SITES


class GeneratedApprovedMockTests(TestCase):
    def test_build_both_sites_with_original_script_hash_and_no_sim(self):
        with TemporaryDirectory() as temp:
            with patch("gym.build_approved_mock.GENERATED", Path(temp)):
                for name in sorted(SITES):
                    with self.subTest(name=name):
                        generated = build_approved_mock(name)
                        site = load_approved_mock(name)
                        reference = FunctionalSite(name)
                        self.assertEqual(site.url, reference.url)
                        self.assertEqual(site.hashes, reference.hashes)
                        self.assertEqual(site.root, generated)
                        manifest = json.loads((generated / MANIFEST).read_text())
                        self.assertEqual(manifest["sha256"], reference.hashes)
                        self.assertEqual(manifest["original_js_executed"], True)
                        self.assertEqual(manifest["external_upstream_allowed"], False)
                        self.assertEqual(site.dispatch("GET", "/app.js").body,
                                         reference.dispatch("GET", "/app.js").body)
                        self.assertNotIn(b"sim.js", site.dispatch("GET", "/").body)
                        self.assertEqual(site.dispatch("GET", "/trace.har").status, 404)
                        self.assertEqual(site.dispatch("GET", "/api/login").status, 404)
                        self.assertEqual(site.dispatch("GET", "/other.js").status, 404)
                        self.assertEqual(site.dispatch("GET", "/style.css").status, 200)

    def test_mutated_generated_js_refused_instead_of_executed(self):
        with TemporaryDirectory() as temp:
            with patch("gym.build_approved_mock.GENERATED", Path(temp)):
                output = build_approved_mock("study-board")
                app = output / "app.js"
                app.write_bytes(app.read_bytes() + b"\nconsole.log('unapproved');\n")
                with self.assertRaisesRegex(ValueError, "differs"):
                    load_approved_mock("study-board")

                # Rebuild restores exact reviewed bytes.
                build_approved_mock("study-board")
                self.assertEqual(load_approved_mock("study-board").url,
                                 "https://studyboard.test/")

    def test_tampered_manifest_refused(self):
        with TemporaryDirectory() as temp:
            with patch("gym.build_approved_mock.GENERATED", Path(temp)):
                output = build_approved_mock("js-demo")
                mf = output / MANIFEST
                data = json.loads(mf.read_text())
                data["static_routes"]["/steal.js"] = "app.js"
                mf.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "manifest"):
                    load_approved_mock("js-demo")

    def test_no_arbitrary_site_or_directory_import(self):
        with TemporaryDirectory() as temp:
            with patch("gym.build_approved_mock.GENERATED", Path(temp)):
                with self.assertRaises(ValueError):
                    build_approved_mock("unreviewed-url")
                with self.assertRaises(ValueError):
                    output_path("study-board", Path(temp))
                with self.assertRaises(ValueError):
                    output_path("study-board", Path(temp) / "js-demo")
                with self.assertRaises(ValueError):
                    output_path("study-board", Path(temp) / "study-board" / "other")
                with self.assertRaises(FileNotFoundError):
                    load_approved_mock("js-demo")

    def test_symlinked_script_is_refused(self):
        with TemporaryDirectory() as temp:
            with patch("gym.build_approved_mock.GENERATED", Path(temp)):
                output = build_approved_mock("study-board")
                app = output / "app.js"
                if app.is_symlink():
                    self.skipTest("fixture contains unexpected symlink")
                app.unlink()
                try:
                    app.symlink_to(FunctionalSite("study-board").root / "app.js")
                except (OSError, NotImplementedError):
                    self.skipTest("symlink unavailable")
                with self.assertRaises(ValueError):
                    load_approved_mock("study-board")
