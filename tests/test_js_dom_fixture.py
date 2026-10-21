"""Exercise the browser-visible JavaScript fixture without network access."""
from pathlib import Path
import shutil
import subprocess
import unittest


class JavaScriptDomFixtureTests(unittest.TestCase):
    def test_dom_updates_after_user_interaction(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed")
        script = Path(__file__).resolve().parents[1] / "gym/fixtures/js-demo/app.js"
        harness = r"""
const vm = require("vm");
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
class Element {
  constructor(item = null) {
    this.dataset = item ? {item} : {};
    this.listeners = {};
    this.attrs = {};
    this.textContent = "";
  }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(name, value) { this.attrs[name] = value; }
  click() {
    if (!this.listeners.click) throw Error("Missing click callback");
    this.listeners.click();
  }
}
const items = ["notebook", "pen", "lamp"].map(id => new Element(id));
const fields = {};
for (const id of ["selected-name", "selected-detail", "basket-count",
                   "last-action", "add-item"]) fields[id] = new Element();
const document = {
  querySelectorAll: q => {
    if (q !== "button[data-item]") throw Error("Unexpected DOM query " + q);
    return items;
  },
  getElementById: id => fields[id]
};
// No fetch, XMLHttpRequest, WebSocket or browser network global is exposed.
vm.runInNewContext(source, {document, console}, {timeout: 1000});
items[1].click();
if (fields["selected-name"].textContent !== "Pen")
  throw Error("Selected item not reflected in live DOM");
if (items[1].attrs["aria-pressed"] !== "true" ||
    items[0].attrs["aria-pressed"] !== "false")
  throw Error("Accessibility state did not update");
fields["add-item"].click();
fields["add-item"].click();
if (fields["basket-count"].textContent !== "Basket: 2 items")
  throw Error("Basket counter did not increment through JS");
if (fields["last-action"].textContent !== "Added pen")
  throw Error("Last action state did not update");
"""
        result = subprocess.run([node, "-e", harness, str(script)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixture_is_network_free_and_source_linked(self):
        root = Path(__file__).resolve().parents[1] / "gym/fixtures/js-demo"
        source = (root / "app.js").read_text(encoding="utf-8")
        markup = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script defer src="./app.js"></script>', markup)
        self.assertIn('<a href="./app.js">', markup)
        self.assertNotIn("fetch(", source)
        self.assertNotIn("XMLHttpRequest", source)
        self.assertNotIn("new WebSocket(", source)
        self.assertNotIn("http://", source)
        self.assertNotIn("https://", source)


if __name__ == "__main__":
    unittest.main()
