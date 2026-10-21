"""Local-only simulator regressions: focusing fields must not navigate.

Runs generated replay JavaScript in a minimal Node VM; no network or live site.
"""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import unittest


class EditableFocusReplayTests(unittest.TestCase):
    def test_editable_focus_does_not_trigger_click_navigation_or_preview(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable")
        source = (Path(__file__).resolve().parents[1] / "capture_replay.py").read_text()
        tree = ast.parse(source)
        simulator = next(n.value.value for n in tree.body
                         if isinstance(n, ast.Assign)
                         and any(isinstance(x, ast.Name) and x.id == "SIM_JS"
                                 for x in n.targets))
        harness = r"""
const vm = require("vm");
const sim = SIMULATOR;
function runCase(editable) {
  class Element {}
  const input = new Element();
  const main = new Element();
  input.parentElement = main;
  main.parentElement = null;
  input.closest = selector => selector.includes("input:not") ? input
    : selector === "main" ? main : null;
  input.matches = selector => selector === "button" ? false : false;
  const listeners = {};
  let previewTimer = null;
  let navigated = null;
  let fetchCalls = 0;
  const pathname = editable ? "/login" : "/cart";
  const doc = {
    currentScript: {dataset:{
      step: editable ? "4" : "2",
      domSettleTo: editable ? "5" : "3",
      transitions: JSON.stringify([{
        kind:"click",selector:"main",to:editable ? 5 : 3,
        to_path:pathname,outcome:"changed",observed:true
      }])
    }},
    activeElement: editable ? input : null,
    addEventListener: (kind, fn) => { listeners[kind] = fn; },
    querySelector: () => editable ? input : null,
    querySelectorAll: () => []
  };
  const location = {
    origin:"https://example.test", pathname,
    replace:url => navigated = url,
    assign:url => navigated = url
  };
  vm.runInNewContext(sim, {
    document:doc, Element, URL, location,
    window:{setTimeout:fn => previewTimer = fn},
    console, fetch:async() => { fetchCalls++; return {ok:true,json:async()=>({})} }
  });
  if (editable) {
    // This click must remain a focus action even though a broad recorded
    // click selector ("main") could otherwise match the input ancestor.
    listeners.focusin({target:input});
    listeners.click({composedPath:()=>[input],target:input,preventDefault:()=>{}});
    if (fetchCalls !== 0) throw Error("Input click generated a synthetic event");
  }
  if (typeof previewTimer !== "function") throw Error("Preview was not scheduled");
  previewTimer();
  if (editable && navigated !== null) throw Error("Editable input was reloaded");
  if (!editable && navigated !== "/cart?__mock_step=3")
    throw Error("Noneditable cart settling preview stopped: " + navigated);
}
runCase(true);
runCase(false);
""".replace("SIMULATOR", json.dumps(simulator))
        result = subprocess.run([node, "-e", harness], capture_output=True,
                                text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_replay_source_keeps_form_value_private(self):
        source = (Path(__file__).resolve().parents[1] / "capture_replay.py").read_text()
        self.assertIn("if (target.closest(EDITABLE_FIELD)) return;", source)
        self.assertIn("editingStarted", source)
        self.assertIn("document.querySelector(MAIN_TEXT_FIELD)", source)
        # Replay posts metadata-only field types; do not add form field values.
        self.assertIn("filled_types: filledFieldTypes(container)", source)
        self.assertNotIn("new FormData(", source)


if __name__ == "__main__":
    unittest.main()
