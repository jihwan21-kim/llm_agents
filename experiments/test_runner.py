import copy
import json
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import runner
from runner import allowed, validate, evidence_summary, perform


class RunnerTests(unittest.TestCase):
    def test_exact_origin_boundary(self):
        target = "https://298101binance.com/"
        self.assertTrue(allowed(target + "c/password", target))
        self.assertTrue(allowed("https://298101binance.com:443/", target))
        for url in ["http://298101binance.com/", "https://298101binance.com.evil.test/",
                    "https://298101binance.com@evil.test/", "https://mock.test/",
                    "https://298101binance.com:8443/", "file:///tmp/x", "javascript:alert(1)"]:
            self.assertFalse(allowed(url, target), url)

    def test_intent_is_not_receipt(self):
        events = [{"type": "submission_intent", "stage": "password"},
                  {"type": "submit_click", "stage": "password"}]
        result = evidence_summary(events)
        self.assertFalse(result["password_local_received"])
        self.assertEqual(result["submit_click_stages"], ["password"])
        events.append({"type": "simulated_request", "stage": "password"})
        self.assertTrue(evidence_summary(events)["password_local_received"])
        self.assertEqual(evidence_summary(events)["original_server_receipt"], "not_measured")

    def test_config_rejects_unregistered_targets_and_remote_proxy(self):
        cfg = json.loads((Path(__file__).parent / "config.json").read_text())
        sites = [{"id": "coinbase-298101", "host": "298101binance.com"}]
        validate(cfg, sites)
        for change in [{"proxy": "http://evil.test:8080"}, {"manager": "http://evil.test"}, {"repeats": 0}]:
            with self.assertRaises(ValueError):
                validate({**cfg, **change}, sites)
        bad = copy.deepcopy(cfg)
        bad["cases"][0]["url"] = "https://evil.test/"
        with self.assertRaises(ValueError):
            validate(bad, sites)

    def test_navigation_guard_precedes_browser_action(self):
        # None raises AttributeError if the browser is touched before URL validation.
        with self.assertRaises(ValueError):
            perform(None, "navigate", {"url": "https://mock.test/"},
                    "https://298101binance.com/", {"width": 1280, "height": 900})

    def test_trial_preserves_tool_results_and_separates_stop_from_receipt(self):
        cfg = json.loads((Path(__file__).parent / "config.json").read_text())
        case = cfg["cases"][0]
        page = SimpleNamespace(url=case["url"], on=lambda *a: None,
            goto=lambda *a, **kw: SimpleNamespace(status=200, headers={"x-mock-proxy": "local-only"}),
            wait_for_timeout=lambda *a: None)
        context = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page,
                                  on=lambda *a: None, close=lambda: None)
        browser = SimpleNamespace(version="test-browser", close=lambda: None)
        calls = []
        def respond(**kwargs):
            calls.append(copy.deepcopy(kwargs))
            if len(calls) == 1:
                name, arguments = "click", {"x": 10, "y": 20}
            else:
                self.assertTrue(any(i.get("type") == "function_call_output" for i in kwargs["input"]))
                name, arguments = "finish", {"status": "needs_user", "reason": "Please confirm."}
            raw = {"output": [{"type": "function_call", "call_id": str(len(calls)),
                              "name": name, "arguments": json.dumps(arguments)}]}
            return SimpleNamespace(model_dump=lambda **kw: raw, output_text="")
        api = SimpleNamespace(responses=SimpleNamespace(create=respond))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("sites.json", "proxy_app.py", "runner_fixture.py"):
                (root / name).write_text("{}")
            folder = root / "trial"
            def get_events(url):
                session = json.loads((folder / "manifest.json").read_text())["trial_id"]
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [
                    {"session": session, "site_id": case["site_id"], "type": "page_loaded"},
                    {"session": "other-trial", "site_id": case["site_id"], "type": "simulated_request", "stage": "password"}])
            with patch.object(runner, "launch", return_value=browser), \
                 patch.object(runner, "new_context", return_value=context), \
                 patch.object(runner, "observe", return_value={"role": "user", "content": "screenshot fixture"}), \
                 patch.object(runner, "perform") as action, \
                 patch.object(runner.importlib.metadata, "version", return_value="test"), \
                 patch.object(runner, "__file__", str(root / "runner_fixture.py")), \
                 patch.object(runner, "ROOT", root):
                result = runner.trial(None, cfg, case, folder, SimpleNamespace(get=get_events), api)
            self.assertEqual(result["status"], "needs_user")
            self.assertEqual(len(calls), 2)
            self.assertEqual(action.call_count, 1)
            self.assertTrue(result["logging_verified"])
            self.assertFalse(result["password_local_received"])


if __name__ == "__main__":
    unittest.main()
