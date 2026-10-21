"""Policies separate inspection targets from executable synthetic fixtures."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gym.site_access_policy import (
    SitePolicyError, load_policy, normalize_host, require_site_mode,
)
from gym.functional_sites import FunctionalSite


class SiteAccessPolicyTests(unittest.TestCase):
    def test_google_is_registered_for_read_only_only(self):
        policy = load_policy()
        for url in (
            "https://google.com/",
            "https://www.google.com/search",
            "https://accounts.google.com/signin/",
        ):
            with self.subTest(url=url):
                for mode in ("capture", "static_replay", "source_inspection"):
                    item = require_site_mode(url, mode)
                    self.assertFalse(item["owner_permission_verified"])
                    self.assertEqual(item["source_kind"], "external_third_party")
                with self.assertRaisesRegex(SitePolicyError, "not permitted"):
                    require_site_mode(url, "native_js")

    def test_only_reviewed_synthetic_fixtures_can_run_native_js(self):
        for name, host in (("js-demo", "fixture.test"),
                           ("study-board", "studyboard.test")):
            with self.subTest(name=name):
                entry = require_site_mode(host, "native_js", fixture_id=name)
                self.assertTrue(entry["owner_permission_verified"])
                site = FunctionalSite(name)
                self.assertEqual(site.host, host)
                self.assertNotIn(b"sim.js", site.dispatch("GET", "/").body)
                self.assertEqual(site.dispatch("GET", "/app.js").status, 200)
        with self.assertRaises(SitePolicyError):
            require_site_mode("fixture.test", "native_js")
        with self.assertRaises(SitePolicyError):
            require_site_mode("fixture.test", "native_js", fixture_id="study-board")

    def test_policy_file_lying_about_google_cannot_unlock_native_js(self):
        with TemporaryDirectory() as folder:
            fake = Path(folder) / "policy.json"
            data = {"schema": "site-access-policy-v1", "sites": [{
                "host": "accounts.google.com",
                "label": "Fake claim",
                "source_kind": "reviewed_synthetic_fixture",
                "fixture_id": "js-demo",
                "owner_permission_verified": True,
                "allowed_modes": ["native_js"],
            }]}
            fake.write_text(json.dumps(data), encoding="utf-8")
            with patch("gym.site_access_policy.POLICY", fake):
                with self.assertRaisesRegex(SitePolicyError, "limited to reviewed"):
                    require_site_mode("accounts.google.com", "native_js",
                                      fixture_id="js-demo")

    def test_exact_host_prevents_suffix_or_path_tricks(self):
        for url in ("https://accounts.google.com.attacker.test/",
                    "https://attacker.test/accounts.google.com",
                    "https://accounts-google.com/", "https://foo.accounts.google.com"):
            with self.subTest(url=url):
                with self.assertRaises(SitePolicyError):
                    require_site_mode(url, "static_replay")
        for url in ("https://user:password@accounts.google.com/",
                    "https://accounts.google.com:9443/",
                    "file:///accounts.google.com",
                    "*.google.com", "google.com.evil.test"):
            with self.subTest(url=url):
                with self.assertRaises(SitePolicyError):
                    require_site_mode(url, "static_replay")
        self.assertEqual(normalize_host("https://accounts.google.com/path"),
                         "accounts.google.com")

    def test_malformed_policy_fails_closed(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            for entries in (
                [],
                [{"host": "fixture.test", "source_kind": "reviewed_synthetic_fixture",
                  "owner_permission_verified": True, "allowed_modes": ["native_js"]},
                 {"host": "fixture.test", "source_kind": "reviewed_synthetic_fixture",
                  "owner_permission_verified": True, "allowed_modes": ["native_js"]}],
                [{"host": "*.google.com", "source_kind": "external_third_party",
                  "owner_permission_verified": False, "allowed_modes": ["capture"]}],
                [{"host": "example.test", "source_kind": "external_third_party",
                  "owner_permission_verified": "yes", "allowed_modes": ["native_js"]}],
            ):
                # An empty list is technically valid, but denies all sites.
                path.write_text(json.dumps({"schema": "site-access-policy-v1",
                                            "sites": entries}), encoding="utf-8")
                with patch("gym.site_access_policy.POLICY", path):
                    if not entries:
                        self.assertEqual(load_policy(), {})
                        with self.assertRaises(SitePolicyError):
                            require_site_mode("google.com", "capture")
                    else:
                        with self.assertRaises(SitePolicyError):
                            load_policy()

    def test_registry_integration_refuses_fixture_removed_from_policy(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            path.write_text(json.dumps({"schema": "site-access-policy-v1",
                                        "sites": []}), encoding="utf-8")
            with patch("gym.site_access_policy.POLICY", path):
                with self.assertRaises(SitePolicyError):
                    FunctionalSite("js-demo")


if __name__ == "__main__":
    unittest.main()
