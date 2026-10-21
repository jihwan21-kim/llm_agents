"""Offline tests for two independently reviewed functional JavaScript sites."""
import hashlib
import json
from pathlib import Path
import unittest

from gym.functional_sites import FunctionalSite, SITES, json_payload


class FunctionalSiteTests(unittest.TestCase):
    def test_two_distinct_sites_and_original_js_bytes(self):
        first = FunctionalSite("js-demo")
        second = FunctionalSite("study-board")
        self.assertNotEqual(first.host, second.host)
        self.assertTrue(first.url.startswith("https://"))
        self.assertNotEqual(first.hashes["/app.js"], second.hashes["/app.js"])
        for site in [first, second]:
            homepage = site.dispatch("GET", "/")
            self.assertEqual(homepage.status, 200)
            self.assertIn(b'<script defer src="./app.js"></script>', homepage.body)
            self.assertNotIn(b"sim.js", homepage.body)
            js = site.dispatch("GET", "/app.js")
            self.assertEqual(js.status, 200)
            self.assertEqual(js.mime, "text/javascript; charset=utf-8")
            self.assertNotIn(b"__mock_capture/sim.js", js.body)
            source = (site.root / "app.js").read_bytes()
            self.assertEqual(js.body, source)
            self.assertEqual(site.hashes["/app.js"],
                             hashlib.sha256(source).hexdigest())
            self.assertEqual(site.dispatch("HEAD", "/app.js").body, b"")
            self.assertEqual(site.dispatch("GET", "/style.css").status, 200)
            self.assertEqual(site.dispatch("POST", "/app.js").status, 405)

    def test_unknown_files_cannot_load_from_disk_or_har(self):
        site = FunctionalSite("study-board")
        for path in ("/admin", "/etc/passwd", "/../app.js", "/trace.har",
                     "/__mock_capture/scripts", "/checkout", "/api/payment",
                     "/__mock_capture/sim.js", "/favicon.ico"):
            self.assertEqual(site.dispatch("GET", path).status, 404, path)
        with self.assertRaises(ValueError):
            FunctionalSite("random-captured-site")
        self.assertEqual(set(SITES), {"js-demo", "study-board"})

    def test_basket_fixture_only_accepts_preapproved_metadata(self):
        site = FunctionalSite("js-demo")
        good = site.dispatch(
            "POST", "/__mock_capture/fixture-receipt",
            b'{"event":"basket_add","sequence":2}',
            "application/json")
        self.assertEqual(good.status, 200)
        self.assertEqual(json.loads(good.body)["upstream_sent"], False)
        self.assertEqual(len(site.safe_events()), 1)
        self.assertEqual(site.safe_events()[0],
                         {"kind": "basket_add", "sequence": 2,
                          "local_receipt": True, "upstream_sent": False})
        for data in (
            b'{"event":"basket_add","sequence":true}',
            b'{"event":"basket_add","sequence":0}',
            b'{"event":"basket_add","sequence":2,"other":"no"}',
            b'{"event":"login","sequence":2}',
            b'{"event":"basket_add","sequence":2,"email":"example"}',
            b'{"event":"basket_add","sequence":2}' + b" " * 200,
        ):
            self.assertEqual(
                site.dispatch("POST", "/__mock_capture/fixture-receipt",
                              data, "application/json").status, 400)
        self.assertEqual(len(site.safe_events()), 1)
        self.assertEqual(site.dispatch(
            "POST", "/__mock_capture/fixture-receipt",
            b'{"event":"basket_add","sequence":3}', "text/plain").status, 415)

    def test_study_state_changes_only_in_local_memory(self):
        site = FunctionalSite("study-board")
        initial = json.loads(site.dispatch("GET", "/api/slots").body)
        self.assertEqual(len(initial["slots"]), 3)
        for n in range(1, 5):
            result = site.dispatch("POST", "/api/join",
                                   b'{"slot":"study"}', "application/json")
            self.assertEqual(result.status, 200)
            self.assertEqual(json.loads(result.body)["count"], n)
        full = site.dispatch("POST", "/api/join",
                             b'{"slot":"study"}', "application/json")
        self.assertEqual(full.status, 409)
        after = json.loads(site.dispatch("GET", "/api/slots").body)
        self.assertEqual(after["slots"][0]["joined"], 4)
        self.assertEqual(len(site.safe_events()), 4)
        self.assertTrue(all(event["upstream_sent"] is False
                            for event in site.safe_events()))
        reset = FunctionalSite("study-board")
        self.assertEqual(json.loads(reset.dispatch("GET", "/api/slots").body),
                         initial)
        self.assertEqual(reset.safe_events(), [])

    def test_strict_json_prevents_arbitrary_inputs(self):
        site = FunctionalSite("study-board")
        for payload in (
            b'{"slot":""}', b'{"slot":"unknown"}',
            b'{"slot":"study","note":"sensitive"}',
            b'{"slot":123}', b'[]', b'garbage', b'\xff',
            b'{"slot":"study"}' + b" " * 200,
        ):
            reply = site.dispatch("POST", "/api/join",
                                  payload, "application/json")
            self.assertEqual(reply.status, 400)
        self.assertEqual(site.safe_events(), [])
        self.assertEqual(site.dispatch("GET", "/api/join").status, 405)
        self.assertEqual(site.dispatch("POST", "/api/slots").status, 405)
        self.assertEqual(site.dispatch("POST", "/api/join",
                                       b'{"slot":"study"}', "").status, 415)


if __name__ == "__main__":
    unittest.main()
