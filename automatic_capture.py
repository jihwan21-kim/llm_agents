"""Automatically record browser screen transitions for offline research mocks.

The recorder observes visible DOM changes, navigation and user actions. It
writes a graph of observed actions, HAR assets, screenshots and DOM snapshots.
Use synthetic input only; do not use this with real credentials or personal data.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError
from record_site import ROOT, sanitize_har
from navigation_analysis import analyze_recording

MARKER = "__MOCK_AUTO_EVENT__"

# Do not attribute the first transient DOM state to an action. Wait for a
# quiet interval, but bound the wait on pages with perpetual mutations.
SETTLE_QUIET_SECONDS = 1.75
NO_CHANGE_WAIT_SECONDS = 3.5
MAX_SETTLE_SECONDS = 10.0
EVENT_SCRIPT = r"""
(() => {
  if (window.__mockAutoCapture) return;
  window.__mockAutoCapture = true;
  const emit = e => console.log("__MOCK_AUTO_EVENT__" + JSON.stringify(e));
  let nextActionId = 0;
  const emitAction = e => emit({...e, action_id: ++nextActionId});
  // Many JS-driven sites use clickable DIV/SPAN elements instead of BUTTON.
  // Capture all non-input clicks, preferring a stable interactive ancestor,
  // so we can replay the observed choice rather than any arbitrary button.
  const interactive = "button, a, label, summary, select, input[type=submit], input[type=button], [role=button], [onclick], [tabindex], [data-testid]";
  const elementFor = event => {
    const path = event.composedPath?.() || [];
    return path.find(item => item instanceof Element)
      || (event.target instanceof Element ? event.target : null);
  };
  const selector = node => {
    if (!(node instanceof Element)) return "";
    const item = node.closest(interactive) || node;
    if (item.id && /^[a-zA-Z][a-zA-Z0-9_-]{0,79}$/.test(item.id))
      return "#" + item.id;
    const attr = item.getAttribute("data-testid");
    if (attr && /^[a-zA-Z0-9_-]{1,79}$/.test(attr))
      return '[data-testid="' + attr + '"]';
    // The path is a fallback only. The replay uses the same selector on the
    // saved DOM and logs unmatched actions rather than inventing transitions.
    const path = [];
    let el = item;
    while (el && el.nodeType === 1 && el !== document.documentElement && path.length < 18) {
      const tag = el.tagName.toLowerCase();
      const peers = el.parentElement
        ? Array.from(el.parentElement.children).filter(x => x.tagName === el.tagName) : [];
      path.unshift(tag + (peers.length > 1
        ? ":nth-of-type(" + (peers.indexOf(el) + 1) + ")" : ""));
      el = el.parentElement;
    }
    return path.join(" > ");
  };
  document.addEventListener("click", e => {
    const el = elementFor(e);
    if (!el || el.closest("input[type=password], textarea, [contenteditable]")) return;
    const picked = el.closest(interactive) || el;
    emitAction({kind:"click", selector:selector(picked), tag:picked.tagName.toLowerCase()});
  }, true);
  document.addEventListener("submit", e => {
    emitAction({kind:"submit", selector:selector(e.target), tag:"form"});
  }, true);
  document.addEventListener("change", e => {
    const el = e.target;
    if (el && ["SELECT", "INPUT"].includes(el.tagName) && el.type !== "password")
      emitAction({kind:"change", selector:selector(el), tag:el.tagName.toLowerCase()});
  }, true);
  // Observe JS routing while the original site is running in the isolated
  // capture browser. Keep the original history methods' behavior intact.
  for (const operation of ["pushState", "replaceState"]) {
    const original = history[operation];
    if (typeof original !== "function") continue;
    try {
      history[operation] = function(...args) {
        const result = original.apply(this, args);
        emit({kind:"history", operation});
        return result;
      };
    } catch (_) { /* Some sites lock down history methods. */ }
  }
  addEventListener("hashchange", () => emit({kind:"history", operation:"hashchange"}));
  addEventListener("popstate", () => emit({kind:"history", operation:"popstate"}));
  let queued = false;
  const schedule = () => {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; emit({kind:"mutation"}); }, 175);
  };
  const observe = () => {
    if (!document.documentElement) return;
    new MutationObserver(schedule).observe(document.documentElement, {
      childList:true, subtree:true, attributes:true, characterData:true,
      attributeFilter:["class", "style", "hidden", "aria-expanded"]
    });
  };
  if (document.documentElement) observe();
  else document.addEventListener("DOMContentLoaded", observe, {once:true});
})();
"""

# Remove scripts, input values and inline event handlers from saved DOM. The
# original browser runs source scripts while RECORDING, not during REPLAY.
SNAPSHOT_JS = r"""
() => {
  const root = document.documentElement.cloneNode(true);
  root.querySelectorAll("script, iframe, object, embed, noscript").forEach(el => el.remove());
  root.querySelectorAll("input, textarea, select, [contenteditable]").forEach(el => {
    el.removeAttribute("value");
    el.removeAttribute("checked");
    if (el.tagName === "TEXTAREA" || el.hasAttribute("contenteditable")) el.textContent = "";
    if (el.tagName === "SELECT") {
      el.querySelectorAll("option[selected]").forEach(option => option.removeAttribute("selected"));
    }
  });
  root.querySelectorAll("*").forEach(el => {
    [...el.attributes].forEach(a => {
      if (a.name.toLowerCase().startsWith("on") || a.name === "srcdoc")
        el.removeAttribute(a.name);
    });
  });
  return "<!DOCTYPE html>\n" + root.outerHTML;
}
"""


def export_static_assets(har_path, output):
    """Also unpack CSS/images/fonts into inspectable files, with a manifest."""
    data = json.loads(Path(har_path).read_text(encoding="utf-8"))
    folder = Path(output) / "assets"
    manifest = []
    for item in data.get("log", {}).get("entries", []):
        req, resp = item.get("request") or {}, item.get("response") or {}
        payload = resp.get("content") or {}
        url, body = req.get("url"), payload.get("text")
        if not url or not isinstance(body, str):
            continue
        mime = (payload.get("mimeType") or mimetypes.guess_type(urlsplit(url).path)[0] or "").split(";")[0]
        if not (mime == "text/css" or mime.startswith("image/") or mime.startswith("font/") or
                mime in {"application/font-woff", "application/font-woff2",
                         "application/vnd.ms-fontobject", "application/octet-stream"}):
            continue
        try:
            binary = (base64.b64decode(body, validate=True)
                      if payload.get("encoding") == "base64" else body.encode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if len(binary) > 12 * 1024 * 1024:
            continue
        name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        ext = mimetypes.guess_extension(mime) or ".bin"
        if not re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", ext):
            ext = ".bin"
        folder.mkdir(parents=True, exist_ok=True)
        filename = name + ext
        (folder / filename).write_bytes(binary)
        manifest.append({"file": "assets/" + filename, "mime": mime, "url": url})
    (Path(output) / "assets.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(manifest)


class Recorder:
    def __init__(self, page, out, limit):
        self.page, self.out, self.limit = page, out, limit
        self.steps, self.transitions, self.action_events = [], [], []
        self.navigation_events = []
        self.blocked_writes = []
        self.completed_actions = []
        self.pending, self.last_change = None, 0
        self.seen_mutation = False
        self.mutation_started = None
        self.saved_signature = ""
        self.current_index = -1
        self.state_index = {}
        page.on("console", self.on_console)
        page.on("framenavigated", self.on_frame_navigation)

    def on_frame_navigation(self, frame):
        # Full-document navigation, including browser back/forward, does not
        # always cause an in-page popstate event.
        if frame is not getattr(self.page, "main_frame", None) or self.current_index < 0:
            return
        now = time.monotonic()
        self.navigation_events.append({
            "operation": "document_navigation", "from": self.current_index,
        })
        if self.pending is None:
            self.pending = {
                "kind": "browser_navigation", "selector": "", "tag": "",
                "from": self.current_index, "started": now,
            }
        self.last_change = now

    def on_console(self, msg):
        raw = msg.text
        if not raw.startswith(MARKER):
            return
        try:
            event = json.loads(raw[len(MARKER):])
        except (ValueError, TypeError):
            return
        now = time.monotonic()
        if event.get("kind") == "history":
            operation = str(event.get("operation", ""))[:32]
            if operation not in {"pushState", "replaceState", "popstate", "hashchange"}:
                return
            self.navigation_events.append({
                "operation": operation, "from": self.current_index,
            })
            if self.pending is None and self.current_index >= 0:
                self.pending = {
                    "kind": "browser_navigation", "selector": "", "tag": "",
                    "from": self.current_index, "started": now,
                }
            if not self.seen_mutation:
                self.mutation_started = now
            self.seen_mutation = True
            self.last_change = now
        elif event.get("kind") == "mutation":
            if not self.seen_mutation:
                self.mutation_started = now
            self.seen_mutation = True
            self.last_change = now
        elif event.get("kind") in {"click", "submit", "change"}:
            # Do not silently merge different human actions into one edge.
            # If a new action arrives before the previous one has settled,
            # its cause is ambiguous: record that explicitly.
            if self.pending:
                self._complete_pending("interrupted", observed=False)
            seq = len(self.action_events)
            incoming = event.get("action_id")
            action_id = incoming if type(incoming) is int and incoming >= 0 else seq + 1
            selector = str(event.get("selector", ""))[:256]
            self.action_events.append({
                "action_id": action_id, "kind": event["kind"],
                "selector": selector, "from": self.current_index,
                "seq": seq, "outcome": "pending"
            })
            self.pending = {
                "kind": event["kind"], "selector": selector,
                "tag": str(event.get("tag", ""))[:32],
                "from": self.current_index,
                "started": now, "action_id": action_id,
                "seq": seq, "blocked_write": False,
            }
            self.last_change = now

    def _complete_pending(self, outcome, destination=None, observed=False):
        """Close exactly one action; never label a blocked/overlapped action verified."""
        if self.pending is None:
            return
        action = self.pending
        src = action["from"]
        if type(src) is int and 0 <= src < len(self.steps):
            if destination is None:
                destination = src
            edge = {
                "kind": action["kind"], "selector": action["selector"],
                "tag": action["tag"], "from": src, "to": destination,
                "outcome": outcome, "observed": observed,
                "action_id": action["action_id"],
            }
            if action.get("blocked_write"):
                edge["blocked_write"] = True
            if edge not in self.transitions:
                self.transitions.append(edge)
        seq = action.get("seq")
        if type(seq) is int and seq < len(self.action_events):
            self.action_events[seq].update({
                "outcome": outcome, "to": destination,
                "observed_transition": observed,
                "blocked_write": bool(action.get("blocked_write")),
            })
        self.completed_actions.append({
            "action_id": action["action_id"], "outcome": outcome,
            "from": src, "to": destination, "blocked_write": bool(action.get("blocked_write"))
        })
        self.pending = None

    def on_blocked_write(self, method):
        """Read-only capture guard; never stores request bodies or destinations."""
        allowed = {"POST", "PUT", "PATCH", "DELETE"}
        if method.upper() not in allowed:
            return
        row = {
            "method": method.upper(),
            "pending_action_id": self.pending["action_id"] if self.pending else None,
        }
        self.blocked_writes.append(row)
        if self.pending:
            self.pending["blocked_write"] = True

    def state(self):
        try:
            html = self.page.evaluate(SNAPSHOT_JS)
            url = self.page.url
            return url, html
        except Exception:
            return None

    def snapshot(self, reason, observed=None):
        state = observed or self.state()
        if not state:
            return False
        url, html = state
        signature = hashlib.sha256((url + "\n" + html).encode()).hexdigest()
        if self.steps and signature == self.saved_signature:
            return False
        # Revisiting a byte-identical recorded DOM is a graph edge, not a
        # new screen. This allows branches from the same starting state.
        previous_idx = self.current_index
        previous_url = self.steps[previous_idx]["url"] if previous_idx >= 0 else None
        revisited = signature in self.state_index
        if revisited:
            idx = self.state_index[signature]
        else:
            if len(self.steps) >= self.limit:
                print(f"Reached max {self.limit} snapshots; use q to finish.")
                return False
            idx = len(self.steps)
            filename = f"step-{idx:03d}"
            (self.out / (filename + ".html")).write_text(html, encoding="utf-8")
            try:
                self.page.screenshot(path=str(self.out / (filename + ".png")), full_page=True,
                                     timeout=8000, animations="disabled")
            except Exception:
                print("Screenshot failed for step", idx)
            self.steps.append({
                "index": idx, "url": url, "html": filename + ".html",
                "screenshot": filename + ".png", "reason": reason,
                "fingerprint": signature,
            })
            self.state_index[signature] = idx
        if self.pending and self.pending["from"] >= 0:
            self._complete_pending("changed", destination=idx, observed=True)
        elif (reason == "dom-change" and previous_idx >= 0 and idx != previous_idx
              and previous_url == url):
            # DOM-only settling is observed chronology, not observed action
            # causality. Preserve for graph auditing but don't replay it as a
            # button edge or count it as a verified click.
            edge = {"kind": "dom_settle", "selector": "", "tag": "",
                    "from": previous_idx, "to": idx,
                    "outcome": "changed", "observed": False,
                    "temporal_observation": True, "replayable": False}
            if edge not in self.transitions:
                self.transitions.append(edge)
        self.current_index = idx
        self.saved_signature = signature
        self.pending = None
        self.seen_mutation = False
        self.mutation_started = None
        print(f"{'Revisited' if revisited else 'Auto snapshot'} {idx}: {reason} ({url})")
        return True

    def poll(self):
        if not self.steps:
            self.snapshot("initial")
            return
        now = time.monotonic()
        if not self.pending and not self.seen_mutation:
            # The URL can change without a DOM mutation (History API).
            if self.page.url == self.steps[self.current_index]["url"]:
                return
            self.seen_mutation = True
            self.mutation_started = now
            self.last_change = now
        quiet = now - self.last_change
        if self.pending:
            age = now - self.pending["started"]
            if quiet < SETTLE_QUIET_SECONDS and age < MAX_SETTLE_SECONDS:
                return
        elif quiet < SETTLE_QUIET_SECONDS and (
                now - (self.mutation_started or now)) < MAX_SETTLE_SECONDS:
            return

        state = self.state()
        if not state:
            return
        signature = hashlib.sha256((state[0] + "\\n" + state[1]).encode()).hexdigest()
        if signature != self.saved_signature:
            self.snapshot(self.pending["kind"] if self.pending else "dom-change", state)
            return
        if self.pending:
            # A click with no UI change is *not* a recorded navigation.
            # Give delayed application callbacks enough time to run.
            if age >= NO_CHANGE_WAIT_SECONDS:
                outcome = "blocked-write" if self.pending.get("blocked_write") else "no-change"
                self._complete_pending(outcome, observed=outcome == "no-change")
                self.seen_mutation = False
                self.mutation_started = None
            return
        self.seen_mutation = False
        self.mutation_started = None

    def finish(self):
        # A final snapshot is allowed, but don't invent an action outcome if
        # the browser closes during a delayed callback.
        self.poll()
        if self.pending:
            state = self.state()
            if state:
                url, html = state
                signature = hashlib.sha256((url + "\\n" + html).encode()).hexdigest()
                if signature != self.saved_signature:
                    self.snapshot(self.pending["kind"], state)
        if self.pending:
            self._complete_pending("unfinished", observed=False)
        self.snapshot("final")
        return self.steps, self.transitions


def command_reader(commands):
    while True:
        try:
            key = input().strip().lower()
        except (EOFError, OSError):
            break
        commands.put(key)
        if key == "q":
            break


def main():
    parser = argparse.ArgumentParser(description="Auto-record page transitions, HAR and static assets")
    parser.add_argument("--url", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--name", default="workflow")
    parser.add_argument("--browser-channel", choices=["chrome", "chromium"], default="chrome")
    parser.add_argument("--max-steps", type=int, default=120)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        parser.error("--url must be http(s)")
    if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", v) for v in [args.app, args.name]):
        parser.error("--app and --name must be short labels without spaces")
    if args.max_steps < 1 or args.max_steps > 500:
        parser.error("--max-steps must be 1 through 500")
    run_id = args.name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "recordings" / args.app / run_id
    out.mkdir(parents=True, exist_ok=False)
    raw_har = out / "trace.raw.har"
    print("Recording:", out)
    print("Navigate in Chrome; each changed screen is saved automatically.")
    print("In THIS PowerShell window: Enter = check, s + Enter = snapshot, q + Enter = stop.")
    print("Live non-read requests are BLOCKED; server-dependent transitions may not appear.")
    print("Use only synthetic values. Do not use real account, payment or personal data.")
    commands = queue.Queue()
    threading.Thread(target=command_reader, args=(commands,), daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, **(
            {"channel": "chrome"} if args.browser_channel == "chrome" else {}
        ))
        context = browser.new_context(
            viewport={"width": 1365, "height": 900},
            record_har_path=str(raw_har),
            record_har_content="embed",
            service_workers="block",
        )
        context.add_init_script(EVENT_SCRIPT)

        # Never send write requests from the capture browser to the live site.
        # Server-driven POST transitions must be modeled later as synthetic
        # local mock states, not observed live login successes.
        def capture_read_only(route):
            if route.request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                print("Blocked live write:", route.request.method)
                recorder.on_blocked_write(route.request.method)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", capture_read_only)
        page = context.new_page()
        recorder = Recorder(page, out, args.max_steps)
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            print("Initial navigation timed out; capture will continue.")
        except PlaywrightError as exc:
            # TLS failures are valuable research observations, not something
            # to suppress with ignore_https_errors=True.
            message = str(exc)
            code = re.search(r"net::(ERR_[A-Z_]+)", message)
            error_code = code.group(1) if code else "PLAYWRIGHT_NAVIGATION_ERROR"
            if error_code.startswith("ERR_CERT_"):
                print(f"HTTPS certificate rejected: {error_code}")
                print("The recording did not start because Chrome could not verify the site's certificate.")
                print("Inspect the certificate in a dedicated browser/VM and verify the")
                print("issuer, hostname, date, and any HTTPS-intercepting proxy.")
                print("Do not disable TLS verification for a security experiment.")
            else:
                print(f"Initial page navigation failed: {error_code}")
            (out / "capture_failure.json").write_text(
                json.dumps({"kind": "navigation_blocked", "code": error_code,
                            "recording_created": False}, indent=2), encoding="utf-8"
            )
            context.close()
            browser.close()
            raw_har.unlink(missing_ok=True)
            raise SystemExit(2) from None
        recorder.snapshot("initial")
        try:
            running = True
            while running:
                page.wait_for_timeout(180)  # Dispatch Playwright browser events.
                while not commands.empty():
                    command = commands.get_nowait()
                    if command == "q":
                        running = False
                        break
                    if command == "s":
                        recorder.snapshot("manual")
                if running:
                    recorder.poll()
        except KeyboardInterrupt:
            print("Finishing on Ctrl+C")
        finally:
            steps, transitions = recorder.finish()
            context.close()  # Flush raw HAR.
            browser.close()
    try:
        count = sanitize_har(raw_har, out / "trace.har")
    finally:
        raw_har.unlink(missing_ok=True)
    assets = export_static_assets(out / "trace.har", out)
    bundle = {
        "version": 2, "app": args.app, "id": run_id, "name": args.name,
        "startUrl": args.url, "steps": steps, "transitions": transitions,
        "harFile": "trace.har", "harGetEntries": count, "exportedAssets": assets,
    }
    (out / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "transitions.json").write_text(json.dumps(transitions, indent=2), encoding="utf-8")
    (out / "action-events.json").write_text(
        json.dumps(recorder.action_events, indent=2), encoding="utf-8"
    )
    (out / "navigation-events.json").write_text(
        json.dumps(recorder.navigation_events, indent=2), encoding="utf-8"
    )
    # Request METHODS and action ids only. Never capture request bodies.
    (out / "blocked-writes.json").write_text(
        json.dumps(recorder.blocked_writes, indent=2), encoding="utf-8"
    )
    navigation_report = analyze_recording(out)
    (out / "navigation-analysis.json").write_text(
        json.dumps(navigation_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Navigation clues: {navigation_report['html_route_count']} HTML links/forms, "
          f"{navigation_report['js_route_hint_count']} JavaScript literal routes.")
    clicks = sum(a["kind"] == "click" for a in recorder.action_events)
    print(f"Saved {len(steps)} states, {len(transitions)} action edges, {assets} assets and {count} HAR entries.")
    print(f"Captured {clicks} clicks and {len(recorder.action_events)} total user actions.")
    if len(steps) > 1 and not transitions:
        print("WARNING: Multiple screens but no action edges. The replay cannot infer which button navigates.")
        print("Check whether the workflow uses new tabs, cross-origin frames, or unsupported clicks.")
    print("Replay:", "start-har-mock-windows.bat", str(out))

if __name__ == "__main__":
    main()
