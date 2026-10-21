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
                 "MARKER": "__MOCK_AUTO_EVENT__", "SNAPSHOT_JS": ""}
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
            # A clickable DIV, rather than a semantic button, must still
            # create an edge that can be matched by the replay.
            recorder.on_console(Msg({
                "kind": "click", "selector": "#custom-card", "tag": "div"
            }))
            page.url = "https://example.test/card"
            page.content = "<html><body><div id='custom-card'>Done</div></body></html>"
            recorder.snapshot("click")
            self.assertEqual(recorder.transitions[-1]["selector"], "#custom-card")
            self.assertEqual(recorder.transitions[-1]["from"], 2)
            self.assertEqual(recorder.transitions[-1]["to"], 3)
            self.assertEqual(len(recorder.action_events), 4)

    def test_capture_event_instrumentation_covers_non_buttons(self):
        source = (Path(__file__).resolve().parents[1] / "automatic_capture.py").read_text()
        replay = (Path(__file__).resolve().parents[1] / "capture_replay.py").read_text()
        self.assertIn('const el = elementFor(e);', source)
        self.assertIn('el.closest(interactive) || el', source)
        self.assertIn('const chain = event.composedPath?.() || [];', replay)
        self.assertIn('const edge = bestEdge(target, "click");', replay)

    def test_replay_prefers_specific_click_over_broad_no_change(self):
        # Exercise the actual replay JS, not a Python duplicate of its
        # matching algorithm. CI runners with Node execute this regression.
        import ast
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed")
        source = (Path(__file__).resolve().parents[1] / "capture_replay.py").read_text()
        tree = ast.parse(source)
        sim = next(n.value.value for n in tree.body
                   if isinstance(n, ast.Assign) and any(
                       isinstance(t, ast.Name) and t.id == "SIM_JS" for t in n.targets
                   ))
        harness = r"""
const vm = require("vm");
const sim = SIMULATOR;
class Element {}
const main = new Element();
const card = new Element();
const inner = new Element();
main.parentElement = null;
card.parentElement = main;
inner.parentElement = card;
inner.closest = selector => {
  if (selector === "body > main") return main;
  if (selector === "body > main > div:nth-of-type(12)") return card;
  return null;
};
let clickedUrl = null;
let posted = null;
const listeners = {};
const document = {
  currentScript: {dataset: {step: "1", transitions: JSON.stringify([
    {kind:"click", selector:"body > main", to:1, outcome:"no-change", observed:true},
    {kind:"click", selector:"body > main > div:nth-of-type(12)", to:2,
     to_path:"/a/b", outcome:"changed", observed:true}
  ])}},
  addEventListener: (name, fn) => {listeners[name] = fn;},
  querySelectorAll: () => []
};
vm.runInNewContext(sim, {
  document, Element, console, URL,
  location: {origin:"https://example.test", assign: url => {clickedUrl = url;}},
  fetch: async (url, options) => {
    posted = JSON.parse(options.body);
    return {ok:true, json:async()=>({
      to:posted.to, observed:posted.observed_transition,
      static_navigation:false
    })};
  }
});
listeners.click({
  composedPath: () => [inner],
  target:inner,
  preventDefault: () => {}
});
setTimeout(() => {
  if (clickedUrl !== "/a/b?__mock_step=2" || posted?.to !== 2) {
    console.error("Wrong chosen transition:", clickedUrl, posted);
    process.exit(1);
  }
  // A *different* click in main must not be counted as the broad
  // 1 -> 1 no-change edge. It should be an unmatched attempt.
  inner.closest = selector => selector === "body > main" ? main : null;
  listeners.click({
    composedPath: () => [inner], target:inner, preventDefault: () => {}
  });
  setTimeout(() => {
    if (posted?.to !== 1 || posted?.selector !== "") {
      console.error("Broad no-op matched unrelated button:", posted);
      process.exit(1);
    }
  }, 30);
}, 30);
""".replace("SIMULATOR", json.dumps(sim))
        completed = subprocess.run([node, "-e", harness], capture_output=True,
                                   text=True, timeout=10, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_extract_html_and_javascript_navigation_without_execution(self):
        from navigation_analysis import (
            extract_html_navigation, extract_js_route_literals, analyze_recording
        )
        url = "https://example.test/a/b"
        markup = ('<html><body><a href="/checkout?token=private">Checkout</a>'
                  '<a href="https://external.test/steal">Outside</a>'
                  '<form action="/submit" method="POST"></form></body></html>')
        routes = extract_html_navigation(markup, url)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[0]["target_path"], "/checkout")
        self.assertEqual(routes[0]["selector"], 'a[data-mock-link-index="0"]')
        self.assertEqual(routes[1]["kind"], "form")
        self.assertEqual(routes[1]["method"], "POST")
        js = ('navigate("/login"); window.location.assign("/reset");'
              'router.push("/cart"); const hidden="/ignored";')
        self.assertEqual(extract_js_route_literals(js, url),
                         ["/login", "/reset", "/cart"])
        with tempfile.TemporaryDirectory() as tmp:
            self.make_recording(tmp)
            folder = Path(tmp)
            (folder / "step-000.html").write_text(markup)
            har = json.loads((folder / "trace.har").read_text())
            har["log"]["entries"].append({
                "request": {"method":"GET", "url":"https://example.test/main.js"},
                "response": {"content":{"mimeType":"text/javascript",
                                       "text":js}}
            })
            (folder / "trace.har").write_text(json.dumps(har))
            report = analyze_recording(folder)
            self.assertEqual(report["html_route_count"], 2)
            self.assertEqual(report["js_route_hint_count"], 3)
            self.assertNotIn("token=private", json.dumps(report))
            self.assertNotIn("external.test/steal", json.dumps(report))

    def test_report_explains_zero_literal_routes_and_counts_saved_graph(self):
        from navigation_analysis import analyze_recording
        with tempfile.TemporaryDirectory() as tmp:
            self.make_recording(tmp)
            folder = Path(tmp)
            bundle = json.loads((folder / "bundle.json").read_text())
            bundle["transitions"] = [
                {"from":0, "to":1, "kind":"click", "outcome":"changed", "observed":True},
                {"from":0, "to":0, "kind":"click", "outcome":"no-change", "observed":True},
            ]
            (folder / "bundle.json").write_text(json.dumps(bundle))
            # A JavaScript-only interface may have no href or route literals.
            (folder / "step-000.html").write_text(
                "<html><body><button>Open modal</button></body></html>"
            )
            har = json.loads((folder / "trace.har").read_text())
            har["log"]["entries"].extend([
                {"request":{"method":"GET", "url":"https://cdn.test/site.js"},
                 "response":{"content":{"mimeType":"text/javascript",
                                        "text":'router.push("/checkout")'}}},
                {"request":{"method":"GET", "url":"https://example.test/site.js"},
                 "response":{"content":{"mimeType":"text/javascript",
                                        "text":"document.body.classList.add('modal')"}}},
            ])
            (folder / "trace.har").write_text(json.dumps(har))
            report = analyze_recording(folder)
            self.assertEqual(report["html_route_count"], 0)
            self.assertEqual(report["html_coverage"]["button_tags"], 1)
            self.assertEqual(report["har_coverage"]["script_entries"], 2)
            self.assertEqual(report["har_coverage"]["external_scripts"], 1)
            self.assertEqual(report["har_coverage"]["first_party_scripts"], 1)
            self.assertEqual(report["har_coverage"]["script_bodies_analyzed"], 2)
            self.assertEqual(report["js_route_hint_count"], 1)
            self.assertEqual(report["js_route_hints"][0]["script_origin"], "external")
            self.assertFalse(report["js_route_hints"][0]["verified"])
            self.assertEqual(len(report["graph"]["observed_edges"]), 2)
            self.assertEqual(report["graph"]["reachable_states"], [0, 1])
            self.assertEqual(report["graph"]["no_change_edge_count"], 1)

    def test_static_same_origin_anchor_replay_requires_captured_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make_recording(tmp)
            folder = Path(tmp)
            (folder / "step-000.html").write_text(
                '<html><body><a href="/login">Login</a>'
                '<a href="https://external.test/">External</a>'
                '<a href="/unknown">Unknown</a></body></html>'
            )
            bundle = json.loads((folder / "bundle.json").read_text())
            bundle["steps"][1]["url"] = "https://example.test/login"
            (folder / "bundle.json").write_text(json.dumps(bundle))
            replay = CaptureReplay(tmp)
            self.assertEqual(len(replay.inferred_edges), 1)
            edge = replay.inferred_edges[0]
            self.assertEqual((edge["from"], edge["to"], edge["outcome"]),
                             (0, 1, "html-href"))
            self.assertEqual(edge["selector"], 'a[data-mock-link-index="0"]')
            status, body, _ = replay.respond("GET", "/a/b")
            self.assertEqual(status, 200)
            rendered = body.decode()
            self.assertIn('data-mock-link-index="0"', rendered)
            self.assertIn("html-href", rendered)
            self.assertNotIn("external.test", rendered)
            self.assertEqual(replay.respond("GET", "/login", "__mock_step=1")[0], 200)

    def test_history_navigation_is_recorded_as_a_graph_edge(self):
        import ast
        import hashlib
        import time
        source = (Path(__file__).resolve().parents[1] / "automatic_capture.py").read_text()
        tree = ast.parse(source)
        node = next(n for n in tree.body
                    if isinstance(n, ast.ClassDef) and n.name == "Recorder")
        scope = {"hashlib":hashlib, "time":time, "json":json,
                 "MARKER":"__MOCK_AUTO_EVENT__", "SNAPSHOT_JS":""}
        exec(compile(ast.Module(body=[node], type_ignores=[]),
                     "automatic_capture.py", "exec"), scope)

        class Page:
            def __init__(self):
                self.url = "https://example.test/start"
                self.dom = "<html><body>Start</body></html>"
                self.main_frame = object()
            def on(self, kind, callback):
                pass
            def evaluate(self, code):
                return self.dom
            def screenshot(self, path, **kwargs):
                Path(path).write_bytes(b"PNG")

        class Message:
            text = '__MOCK_AUTO_EVENT__{"kind":"history","operation":"popstate"}'

        with tempfile.TemporaryDirectory() as t:
            page = Page()
            rec = scope["Recorder"](page, Path(t), 10)
            rec.snapshot("initial")
            rec.on_console(Message())
            page.url = "https://example.test/back"
            page.dom = "<html><body>Back</body></html>"
            rec.snapshot("browser_navigation")
            self.assertEqual(rec.transitions[0]["kind"], "browser_navigation")
            self.assertEqual((rec.transitions[0]["from"], rec.transitions[0]["to"]), (0, 1))
            self.assertEqual(rec.navigation_events[0]["operation"], "popstate")

    def test_entry_skips_unaimed_loading_states(self):
        with tempfile.TemporaryDirectory() as t:
            self.make_recording(t)
            folder = Path(t)
            bundle = json.loads((folder / "bundle.json").read_text())
            bundle["steps"].append({
                "url": "https://example.test/a/b", "html": "step-002.html"
            })
            (folder / "step-002.html").write_text(
                "<html><body><button id='login'>Login</button></body></html>"
            )
            bundle["transitions"] = [{
                "from": 2, "to": 2, "kind": "change",
                "selector": "#login", "outcome": "no-change",
                "observed": True
            }]
            (folder / "bundle.json").write_text(json.dumps(bundle))
            replay = CaptureReplay(folder)
            self.assertEqual(replay.initial_step, 2)
            self.assertIn("Login", replay.respond("GET", "/a/b")[1].decode())
            self.assertEqual(replay.respond("GET", "/a/b", "__mock_step=0")[0], 200)
            self.assertEqual(replay.respond("GET", "/a/b", "__mock_step=1")[0], 200)

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
