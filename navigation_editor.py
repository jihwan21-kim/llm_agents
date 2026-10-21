"""Explicit, visually editable offline snapshot navigation for benign UI states.

Only recorded same-origin snapshots and non-sensitive button-like clicks are
eligible. No original JS executes, no cross-origin redirect is possible, and
the editor never stores input values, credentials, or request bodies.
"""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

EDITOR = "/__mock_capture/editor"
EDITOR_JS_PATH = "/__mock_capture/editor.js"
EDITOR_STATE = "/__mock_capture/editor/state"
EDITOR_SAVE = "/__mock_capture/editor/save"
OVERRIDES_NAME = "navigation-overrides.json"
MAX_OVERRIDES = 100
MAX_RAW_BYTES = 2048
# Conservative: credentials, authentication, verification and payment screens
# never receive manually authored forward navigation edges.
SENSITIVE_PATH = re.compile(
    r"(?:^|[/_-])(?:login|log-in|signin|sign-in|signup|sign-up|auth|"
    r"password|credential|session|account|verify|verification|otp|mfa|2fa|"
    r"checkout|payment|billing|wallet)(?:$|[/_-])", re.I)
SENSITIVE_ATTR = re.compile(
    r"(?:password|passcode|credential|one.time|verification|otp|"
    r"authenticat|sign.?in|log.?in|e.?mail|card.?number|cvv|cvc)", re.I)
# Keep selectors to simple, generated DOM identifiers, not arbitrary CSS.
SELECTOR = re.compile(
    r'^(?:#[a-zA-Z_][a-zA-Z0-9_-]{0,80}|'
    r'a\[data-mock-link-index="[0-9]{1,4}"\]|'
    r'(?:[a-z][a-z0-9-]*(?::nth-of-type\([1-9][0-9]{0,2}\))?'
    r'(?:\s*>\s*[a-z][a-z0-9-]*(?::nth-of-type\([1-9][0-9]{0,2}\))?){0,8}))$'
)


class NavigationEditError(ValueError):
    pass


class SensitivePageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sensitive = False
        self.heading_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"title", "h1", "h2"}:
            self.heading_depth += 1
        props = {k.lower(): str(v or "") for k, v in attrs if k}
        if tag == "input":
            kind = props.get("type", "text").lower()
            if kind in {"password", "email", "tel", "number"}:
                self.sensitive = True
            if any(SENSITIVE_ATTR.search(props.get(k, "")) for k in (
                    "autocomplete", "name", "id", "placeholder", "aria-label")):
                self.sensitive = True
        if tag == "form":
            if any(SENSITIVE_ATTR.search(props.get(k, "")) for k in ("action", "id", "name")):
                self.sensitive = True

    def handle_endtag(self, tag):
        if tag in {"title", "h1", "h2"}:
            self.heading_depth = max(0, self.heading_depth - 1)

    def handle_data(self, data):
        # Some authentication steps show a headline before any inputs.
        if self.heading_depth and re.search(
                r"\b(?:log\s*in|sign\s*in|password|verify|verification|"
                r"authentication|payment|checkout)\b", data, re.I):
            self.sensitive = True


EDITOR_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mock Navigation Editor</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#1b293b;background:#eef2f7}
*{box-sizing:border-box}body{margin:0}header{background:#132137;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;gap:10px}
h1{font-size:20px;margin:0}header p{font-size:12px;color:#cbd5e1;margin:5px 0 0}
header a{color:white;background:#304764;border:1px solid #5b779c;padding:8px 13px;border-radius:8px;text-decoration:none}
main{display:grid;grid-template-columns:minmax(200px,250px) minmax(320px,1fr) minmax(240px,290px);gap:16px;padding:16px;height:calc(100vh - 94px)}
section{background:white;border:1px solid #d8e2eb;border-radius:12px;min-height:0;display:flex;flex-direction:column;overflow:auto}
section h2{font-size:15px;margin:0;padding:17px 16px;border-bottom:1px solid #e1e8f0}
.pad{padding:15px;display:grid;gap:11px}label{font-size:12px;font-weight:700;color:#405266}
select,input,button{font:inherit;width:100%;min-height:39px;border:1px solid #adbed0;border-radius:8px;padding:7px 9px;background:white}
button{cursor:pointer}button.primary{background:#235cbd;color:white;border-color:#235cbd;font-weight:650}
button:disabled{opacity:.5;cursor:not-allowed}.muted{color:#64748b;font-size:12px;line-height:1.5}
code{word-break:break-all;background:#eef2f7;border-radius:5px;padding:5px;font-size:12px}
iframe{width:100%;flex:1;border:0;background:white;min-height:0}
#frameMessage{font-size:12px;color:#506278;padding:10px 14px;background:#e9f3ff;border-bottom:1px solid #d8e2eb}
#message{white-space:pre-wrap;font-size:12px;color:#23548b;line-height:1.5}
#existing{list-style:none;margin:0;padding:0;display:grid;gap:6px}
#existing li{border:1px solid #dce4f0;border-radius:8px;padding:8px;font-size:12px}
#existing li button{margin-top:6px;min-height:30px;font-size:11px}
.warn{background:#fff5db;border:1px solid #f2cf7b;padding:10px;border-radius:8px;color:#754b00;font-size:12px;line-height:1.4}
@media(max-width:1000px){main{display:flex;flex-direction:column;height:auto}section{min-height:190px}#preview{height:60vh;min-height:400px}}
</style>
<script defer src="/__mock_capture/editor.js"></script>
</head><body>
<header><div><h1>Mock Navigation Editor</h1><p>Recorded snapshots · Local edits only · No original JavaScript · No upstream requests</p></div>
<a id="openMock" href="/" target="_blank" rel="noopener noreferrer">Open mock ↗</a></header>
<main>
<section><h2>1. Choose a recorded screen</h2><div class="pad">
<label for="from">Source screen</label><select id="from"></select>
<div class="warn">Only benign screens are editable. Account, login, password, verification and payment screens are locked.</div>
<div class="muted">The recording itself is never changed. Your manual mappings are saved in a separate JSON file.</div>
<h2>Saved connections</h2><ul id="existing"></ul></div></section>
<section><h2>2. Click the button in this preview</h2>
<div id="frameMessage">Click a link, button, or visual DIV/SPAN control in the recorded snapshot to select it. This does not perform the action.</div>
<iframe id="preview" title="Recorded snapshot preview"></iframe></section>
<section><h2>3. Choose the destination</h2><div class="pad">
<label for="selector">Selected control (CSS selector)</label><input id="selector" readonly placeholder="Click a button in the preview">
<label for="to">Destination recorded screen</label><select id="to"></select>
<button id="save" class="primary" type="button">Save connection</button>
<button id="test" type="button">Preview selected destination</button>
<div id="message" role="status" aria-live="polite"></div>
<div class="muted">Saved connections have priority over inferred clicks. Only recorded same-origin, non-sensitive screens are selectable. Test after saving by opening the mock.</div>
</div></section>
</main></body></html>"""

EDITOR_JS = r"""(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let state = null;
  let selectedSelector = "";
  const sourceSelect = $("from");
  const targetSelect = $("to");
  const status = $("message");
  const preview = $("preview");
  const selectors = $("selector");
  const saved = $("existing");
  let selectedElement = null;

  function stepLabel(s) {
    return "#" + s.id + "  " + s.path + (s.blocked ? "  [locked]" : "");
  }
  function fill(select, steps) {
    select.replaceChildren();
    for (const s of steps) {
      const option = document.createElement("option");
      option.value = String(s.id);
      option.textContent = stepLabel(s);
      option.disabled = s.blocked;
      select.append(option);
    }
  }
  function stepPath(id) {
    const step = state.steps.find(s => s.id === id);
    return step ? step.path + "?__mock_step=" + id : "/";
  }
  function cssSelector(el, doc) {
    if (el.tagName === "A" && el.hasAttribute("data-mock-link-index")) {
      return 'a[data-mock-link-index="' + el.getAttribute("data-mock-link-index") + '"]';
    }
    if (el.id && /^[A-Za-z_][\w-]{0,80}$/.test(el.id) &&
        doc.querySelectorAll("#" + el.id).length === 1) return "#" + el.id;
    const path = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && path.length < 9) {
      const tag = cur.tagName.toLowerCase();
      if (!/^[a-z][a-z0-9-]*$/.test(tag)) return null;
      const siblings = cur.parentElement ?
        [...cur.parentElement.children].filter(e => e.tagName === cur.tagName) : [cur];
      const n = siblings.indexOf(cur) + 1;
      path.unshift(tag + (n > 0 ? ":nth-of-type(" + n + ")" : ""));
      if (cur.tagName === "BODY") break;
      cur = cur.parentElement;
    }
    const candidate = path.join(" > ");
    try { return doc.querySelectorAll(candidate).length === 1 ? candidate : null; }
    catch (_) { return null; }
  }
  function mark(el) {
    if (selectedElement) selectedElement.style.outline = "";
    selectedElement = el;
    selectedElement.style.outline = "3px solid #235cbd";
  }
  function handleClick(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
    event.stopPropagation();
    const doc = preview.contentDocument;
    if (!doc) return;
    const raw = event.target;
    // Many recorded UI buttons are plain DIV/SPAN elements. Let the
    // researcher select them as well, rather than guessing an event target.
    // No recorded scripts run, and form/editable controls remain excluded.
    const interactive = raw?.closest?.(
      "a, button, input[type=button], input[type=submit], [role=button], [onclick], [tabindex]"
    );
    const target = interactive || raw?.closest?.("div, span, label, section, article");
    if (!target || target.closest("form") || target.closest(
      "input:not([type=button]):not([type=submit]), textarea, [contenteditable]"
    )) {
      status.textContent = "Select a non-form button, link, or visual DIV/SPAN control.";
      return;
    }
    const selector = cssSelector(target, doc);
    if (!selector) {
      status.textContent = "Couldn't identify a unique CSS selector for this control.";
      return;
    }
    selectedSelector = selector;
    selectors.value = selector;
    mark(target);
    status.textContent = "Selected: " + (target.textContent || target.getAttribute("aria-label") || target.tagName).trim().slice(0, 80);
  }
  function loadPreview(id) {
    selectedSelector = "";
    selectors.value = "";
    selectedElement = null;
    const src = state.steps.find(s => s.id === id);
    if (!src || src.blocked) {
      preview.removeAttribute("src");
      status.textContent = "This screen is locked for navigation editing.";
      return;
    }
    preview.src = stepPath(id);
  }
  preview.addEventListener("load", () => {
    try {
      // Window-level capture runs before the shim's document click handler.
      preview.contentWindow.addEventListener("click", handleClick, true);
    } catch (_) {
      status.textContent = "Could not access preview document. Check that you are in the dedicated mock browser.";
    }
  });
  async function loadState(preserveSource) {
    const response = await fetch("/__mock_capture/editor/state", {cache: "no-store"});
    if (!response.ok) throw Error("Editor state unavailable");
    const previous = preserveSource ? Number(sourceSelect.value) : -1;
    state = await response.json();
    fill(sourceSelect, state.steps);
    fill(targetSelect, state.steps);
    const first = state.steps.find(s => !s.blocked);
    const chosen = state.steps.find(s => s.id === previous && !s.blocked) || first;
    if (chosen) {
      sourceSelect.value = String(chosen.id);
      targetSelect.value = String(state.steps.find(s => !s.blocked && s.id !== chosen.id)?.id ?? chosen.id);
      loadPreview(chosen.id);
    } else {
      status.textContent = "No editable benign snapshots were recorded.";
    }
    $("openMock").href = stepPath(state.initial_step);
    renderSaved();
  }
  function renderSaved() {
    saved.replaceChildren();
    for (const item of state.overrides) {
      const li = document.createElement("li");
      const title = document.createElement("div");
      title.textContent = "#" + item.from + "  " + item.selector + "  →  #" + item.to;
      const remove = document.createElement("button");
      remove.textContent = "Delete mapping";
      remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!confirm("Delete this saved connection?")) return;
        await write({operation: "delete", from: item.from, selector: item.selector});
      });
      li.append(title, remove);
      saved.append(li);
    }
    if (!state.overrides.length) {
      const li = document.createElement("li");
      li.textContent = "No manual connections yet.";
      saved.append(li);
    }
  }
  async function write(payload) {
    status.textContent = "Saving...";
    try {
      const response = await fetch("/__mock_capture/editor/save", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) throw Error(body.error || "Save failed");
      const chosen = Number(sourceSelect.value);
      await loadState(true);
      sourceSelect.value = String(chosen);
      status.textContent = "Saved locally. Open the mock to test this connection.";
    } catch (error) {
      status.textContent = error.message;
    }
  }
  sourceSelect.addEventListener("change", () => loadPreview(Number(sourceSelect.value)));
  $("save").addEventListener("click", () => {
    const from = Number(sourceSelect.value);
    const to = Number(targetSelect.value);
    if (!selectedSelector || !Number.isInteger(from) || !Number.isInteger(to)) {
      status.textContent = "Select a button in the preview and a destination.";
      return;
    }
    write({operation: "set", from, to, selector: selectedSelector});
  });
  $("test").addEventListener("click", () => {
    const to = Number(targetSelect.value);
    if (state?.steps.some(s => s.id === to && !s.blocked))
      window.open(stepPath(to), "_blank", "noopener");
  });
  loadState(false).catch(err => { status.textContent = err.message; });
})();
"""


class NavigationEditor:
    def __init__(self, recording, bundle):
        self.recording = Path(recording).resolve(strict=True)
        self.steps = bundle["steps"]
        self.start_url = bundle["startUrl"]
        self.host = urlsplit(self.start_url).hostname
        self.storage = self.recording / OVERRIDES_NAME
        self.states = []
        for i, step in enumerate(self.steps):
            url = urlsplit(step.get("url") or self.start_url)
            filename = step.get("html") or f"step-{i:03d}.html"
            path = (self.recording / filename).resolve(strict=True)
            if not path.is_relative_to(self.recording):
                raise NavigationEditError("Unsafe snapshot path")
            raw = path.read_text(encoding="utf-8", errors="replace")
            parser = SensitivePageParser()
            parser.feed(raw)
            # All paths and states are based on recorded snapshots, never
            # arbitrary URLs passed from a browser or user-edited JSON.
            blocked = (url.hostname != self.host
                       or bool(SENSITIVE_PATH.search(url.path))
                       or parser.sensitive)
            self.states.append({
                "id": i, "path": url.path or "/", "blocked": bool(blocked),
            })
        self.overrides = self.load()

    def _check_item(self, item):
        if not isinstance(item, dict) or set(item) != {"from", "to", "selector"}:
            raise NavigationEditError("Invalid mapping schema")
        a, b, selector = item["from"], item["to"], item["selector"]
        if (type(a) is not int or type(b) is not int
                or not 0 <= a < len(self.states) or not 0 <= b < len(self.states)
                or a == b or self.states[a]["blocked"] or self.states[b]["blocked"]):
            raise NavigationEditError("Sensitive or invalid recorded step")
        if (not isinstance(selector, str) or len(selector) > 256
                or not SELECTOR.fullmatch(selector)):
            raise NavigationEditError("Invalid or unsupported CSS selector")
        # No manually authored form submission and no cross-site URLs.
        return {"from": a, "to": b, "selector": selector}

    def load(self):
        if not self.storage.exists():
            return []
        if self.storage.is_symlink() or self.storage.stat().st_size > 32_768:
            raise NavigationEditError("Unsafe navigation override file")
        data = json.loads(self.storage.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise NavigationEditError("Unknown override format")
        items = data.get("overrides")
        if not isinstance(items, list) or len(items) > MAX_OVERRIDES:
            raise NavigationEditError("Invalid override list")
        checked = [self._check_item(item) for item in items]
        if len({(item["from"], item["selector"]) for item in checked}) != len(checked):
            raise NavigationEditError("Duplicate override")
        return checked

    def state(self, initial_step):
        return {
            "mode": "explicit_manual_navigation",
            "simulated": True,
            "initial_step": initial_step,
            "steps": self.states,
            "overrides": self.overrides,
        }

    def write(self, payload):
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_RAW_BYTES:
            raise NavigationEditError("Request too large")
        try:
            data = json.loads(payload)
        except (UnicodeError, ValueError) as exc:
            raise NavigationEditError("Malformed JSON") from exc
        if not isinstance(data, dict):
            raise NavigationEditError("Invalid payload")
        operation = data.get("operation")
        if operation == "set" and set(data) == {"operation", "from", "to", "selector"}:
            item = self._check_item({k: data[k] for k in ("from", "to", "selector")})
            result = [o for o in self.overrides
                      if (o["from"], o["selector"]) != (item["from"], item["selector"])]
            result.append(item)
        elif operation == "delete" and set(data) == {"operation", "from", "selector"}:
            if not isinstance(data["selector"], str) or type(data["from"]) is not int:
                raise NavigationEditError("Invalid deletion")
            result = [o for o in self.overrides
                      if (o["from"], o["selector"]) != (data["from"], data["selector"])]
            if len(result) == len(self.overrides):
                raise NavigationEditError("Mapping not found")
        else:
            raise NavigationEditError("Invalid edit operation")
        if len(result) > MAX_OVERRIDES:
            raise NavigationEditError("Too many manual connections")
        self.persist(result)
        self.overrides = result
        return result

    def persist(self, items):
        if self.storage.is_symlink():
            raise NavigationEditError("Refusing symlinked override file")
        # Atomic replacement, so an interrupted save cannot corrupt the
        # research recording's separately versioned override metadata.
        fd, temp = tempfile.mkstemp(prefix=".mock-nav-", suffix=".tmp", dir=self.recording)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "overrides": items}, stream, indent=2)
                stream.write("\n")
            os.replace(temp, self.storage)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
