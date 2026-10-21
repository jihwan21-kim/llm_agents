"""Regression tests for action-to-settled-state capture, with an inert UI fixture.

This suite never contacts a live website or receives input values.
"""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 100.0

    def forward(self, seconds):
        self.now += seconds


def recorder_class(clock):
    source = (ROOT / "automatic_capture.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "Recorder")
    ns = {
        "hashlib": hashlib, "json": json,
        "time": SimpleNamespace(monotonic=lambda: clock.now),
        "MARKER": "__MOCK_AUTO_EVENT__",
        "SNAPSHOT_JS": "",
        "SETTLE_QUIET_SECONDS": 1.75,
        "NO_CHANGE_WAIT_SECONDS": 3.5,
        "MAX_SETTLE_SECONDS": 10.0,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 "automatic_capture.py", "exec"), ns)
    return ns["Recorder"]


class MockPage:
    def __init__(self):
        self.url = "https://example.test/catalog"
        self.dom = "<html><body><button id='item-a'>Product A</button></body></html>"
        self.main_frame = object()

    def on(self, name, fn):
        pass

    def evaluate(self, script):
        return self.dom

    def screenshot(self, path, **kwargs):
        Path(path).write_bytes(b"FAKE_PNG")


class ConsoleMessage:
    def __init__(self, event):
        self.text = "__MOCK_AUTO_EVENT__" + json.dumps(event)


def send(recorder, kind, **fields):
    recorder.on_console(ConsoleMessage({"kind": kind, **fields}))


class ActionSettlingTests(unittest.TestCase):
    def test_delayed_dom_updates_join_one_action_to_final_state(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 12)
            r.snapshot("initial")
            send(r, "click", selector="#item-a", tag="button", action_id=1)
            clock.forward(0.4)
            page.dom = "<html><body>Loading...</body></html>"
            send(r, "mutation")
            clock.forward(0.8)
            r.poll()
            self.assertEqual(len(r.steps), 1)
            clock.forward(1.0)
            page.dom = "<html><body>Product details initializing...</body></html>"
            send(r, "mutation")
            clock.forward(1.0)
            r.poll()
            self.assertEqual(len(r.steps), 1)
            clock.forward(1.0)
            page.dom = "<html><body>Product A details ready</body></html>"
            send(r, "mutation")
            clock.forward(1.8)
            r.poll()
            self.assertEqual(len(r.steps), 2)
            self.assertEqual(len(r.transitions), 1)
            edge = r.transitions[0]
            self.assertEqual((edge["from"], edge["to"]), (0, 1))
            self.assertEqual(edge["selector"], "#item-a")
            self.assertEqual(edge["outcome"], "changed")
            self.assertTrue(edge["observed"])
            self.assertEqual(r.action_events[0]["outcome"], "changed")
            self.assertEqual(r.action_events[0]["to"], 1)
            self.assertEqual(len(r.completed_actions), 1)

    def test_programmatic_second_click_keeps_first_user_action(self):
        # A real checkout click can cause app JS to call .click() on a
        # login control, which used to overwrite the initiating action.
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 12)
            page.url = "https://example.test/cart"
            page.dom = "<html><body><div id='checkout'>Continue shopping</div></body></html>"
            r.snapshot("initial")
            send(r, "click", selector="#checkout", tag="div",
                 action_id=1, trusted=True)
            r.on_blocked_write("POST")
            clock.forward(0.05)
            send(r, "click", selector="#loginEntrar", tag="button",
                 action_id=2, trusted=False)
            self.assertEqual(len(r.action_events), 1)
            self.assertEqual(len(r.derived_events), 1)
            self.assertEqual(r.derived_events[0]["parent_action_id"], 1)
            self.assertIsNotNone(r.pending)
            self.assertEqual(r.pending["selector"], "#checkout")
            page.url = "https://example.test/login"
            page.dom = "<html><body>Test login page, fake values only</body></html>"
            send(r, "mutation")
            clock.forward(2)
            r.poll()
            self.assertEqual(len(r.steps), 2)
            self.assertEqual(len(r.transitions), 1)
            edge = r.transitions[0]
            self.assertEqual((edge["from"], edge["to"]), (0, 1))
            self.assertEqual(edge["selector"], "#checkout")
            self.assertEqual(edge["outcome"], "changed")
            self.assertTrue(edge["observed"])
            self.assertTrue(edge["blocked_write"])
            self.assertEqual(r.action_events[0]["outcome"], "changed")

    def test_default_submit_does_not_interrupt_button_click(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#next", tag="button",
                 action_id=1, trusted=True)
            clock.forward(0.1)
            send(r, "submit", selector="#form", tag="form",
                 action_id=2, trusted=True)
            self.assertEqual(len(r.action_events), 1)
            self.assertEqual(r.derived_events[0]["reason"], "immediate_followup_event")
            page.dom = "<html><body>Next step</body></html>"
            send(r, "mutation")
            clock.forward(2)
            r.poll()
            self.assertEqual(r.transitions[0]["selector"], "#next")
            self.assertTrue(r.transitions[0]["observed"])

    def test_untrusted_click_without_parent_cannot_prove_user_action(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#script", tag="button",
                 action_id=1, trusted=False)
            self.assertEqual(r.action_events, [])
            self.assertIsNone(r.pending)
            self.assertIsNone(r.derived_events[0]["parent_action_id"])

    def test_no_change_waits_and_is_not_invented_navigation(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#buy", tag="button", action_id=1)
            clock.forward(2)
            r.poll()
            self.assertEqual(len(r.transitions), 0)
            self.assertIsNotNone(r.pending)
            clock.forward(1.6)
            r.poll()
            self.assertEqual(len(r.transitions), 1)
            self.assertEqual(r.transitions[0]["outcome"], "no-change")
            self.assertEqual(r.transitions[0]["to"], 0)
            self.assertEqual(len(r.steps), 1)

    def test_blocked_write_is_reported_without_fake_success(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#buy", tag="button", action_id=1)
            r.on_blocked_write("POST")
            clock.forward(3.6)
            r.poll()
            self.assertEqual(r.transitions[0]["outcome"], "blocked-write")
            self.assertFalse(r.transitions[0]["observed"])
            self.assertTrue(r.action_events[0]["blocked_write"])
            self.assertEqual(r.blocked_writes,
                             [{"method": "POST", "pending_action_id": 1}])
            self.assertNotIn("body", json.dumps(r.blocked_writes))

    def test_second_action_interrupts_first_without_false_edge(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#item-a", tag="button", action_id=1)
            clock.forward(0.3)
            send(r, "click", selector="#item-b", tag="button", action_id=2)
            self.assertEqual(r.transitions[0]["outcome"], "interrupted")
            self.assertFalse(r.transitions[0]["observed"])
            page.dom = "<html><body>Product B details ready</body></html>"
            send(r, "mutation")
            clock.forward(2)
            r.poll()
            self.assertEqual(r.action_events[0]["outcome"], "interrupted")
            self.assertEqual(r.action_events[1]["outcome"], "changed")
            self.assertEqual([e["selector"] for e in r.transitions],
                             ["#item-a", "#item-b"])
            self.assertEqual([e["action_id"] for e in r.transitions], [1, 2])

    def test_back_navigation_reuses_first_node(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#item-a", tag="button", action_id=1)
            page.url = "https://example.test/product/a"
            page.dom = "<html><body>Product A</body></html>"
            send(r, "mutation")
            clock.forward(2)
            r.poll()
            self.assertEqual(r.current_index, 1)
            send(r, "history", operation="popstate")
            page.url = "https://example.test/catalog"
            page.dom = "<html><body><button id='item-a'>Product A</button></body></html>"
            clock.forward(2)
            r.poll()
            self.assertEqual(r.current_index, 0)
            self.assertEqual(len(r.steps), 2)
            self.assertEqual(r.transitions[-1]["kind"], "browser_navigation")
            self.assertEqual((r.transitions[-1]["from"], r.transitions[-1]["to"]), (1, 0))

    def test_click_listener_does_not_treat_focusable_main_as_button(self):
        source = (ROOT / "automatic_capture.py").read_text(encoding="utf-8")
        interactive = next(line for line in source.splitlines()
                           if line.strip().startswith("const interactive = "))
        self.assertNotIn("[tabindex]", interactive)
        self.assertIn("[role=button]", interactive)
        self.assertIn("target_selector:selector(el)", source)
        self.assertIn("action_id: ++nextActionId", source)
        self.assertIn("trusted:e.isTrusted === true", source)

    def test_finish_keeps_unresolved_action_unverified(self):
        clock, page = Clock(), MockPage()
        with tempfile.TemporaryDirectory() as tmp:
            r = recorder_class(clock)(page, Path(tmp), 10)
            r.snapshot("initial")
            send(r, "click", selector="#buy", tag="button", action_id=1)
            r.finish()
            self.assertEqual(r.action_events[0]["outcome"], "unfinished")
            self.assertFalse(r.transitions[0]["observed"])


if __name__ == "__main__":
    unittest.main()
