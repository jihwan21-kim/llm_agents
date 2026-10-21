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

MARKER = "__MOCK_AUTO_EVENT__"
EVENT_SCRIPT = r"""
(() => {
  if (window.__mockAutoCapture) return;
  window.__mockAutoCapture = true;
  const emit = e => console.log("__MOCK_AUTO_EVENT__" + JSON.stringify(e));
  const selector = node => {
    if (!(node instanceof Element)) return "";
    const item = node.closest("button, a, input[type=submit], input[type=button], select, [role=button], form") || node;
    if (item.id && /^[a-zA-Z][a-zA-Z0-9_-]{0,79}$/.test(item.id)) return "#" + item.id;
    const attr = item.getAttribute("data-testid");
    if (attr && /^[a-zA-Z0-9_-]{1,79}$/.test(attr))
      return '[data-testid="' + attr + '"]';
    const path = [];
    let el = item;
    while (el && el.nodeType === 1 && el !== document.documentElement && path.length < 12) {
      const tag = el.tagName.toLowerCase();
      const peers = el.parentElement
        ? Array.from(el.parentElement.children).filter(x => x.tagName === el.tagName) : [];
      path.unshift(tag + (peers.length > 1 ? ":nth-of-type(" + (peers.indexOf(el) + 1) + ")" : ""));
      el = el.parentElement;
    }
    return path.join(" > ");
  };
  document.addEventListener("click", e => {
    const el = e.target instanceof Element
      ? e.target.closest("button, a, input[type=submit], input[type=button], [role=button]") : null;
    if (el) emit({kind:"click", selector:selector(el), tag:el.tagName.toLowerCase()});
  }, true);
  document.addEventListener("submit", e => {
    emit({kind:"submit", selector:selector(e.target), tag:"form"});
  }, true);
  document.addEventListener("change", e => {
    const el = e.target;
    if (el && ["SELECT", "INPUT"].includes(el.tagName) && el.type !== "password")
      emit({kind:"change", selector:selector(el), tag:el.tagName.toLowerCase()});
  }, true);
  addEventListener("hashchange", () => emit({kind:"mutation"}));
  addEventListener("popstate", () => emit({kind:"mutation"}));
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
        self.steps, self.transitions = [], []
        self.pending, self.last_change = None, 0
        self.seen_mutation = False
        self.mutation_started = None
        self.saved_signature = ""
        self.current_index = -1
        self.state_index = {}
        page.on("console", self.on_console)

    def on_console(self, msg):
        raw = msg.text
        if not raw.startswith(MARKER):
            return
        try:
            event = json.loads(raw[len(MARKER):])
        except (ValueError, TypeError):
            return
        now = time.monotonic()
        if event.get("kind") == "mutation":
            if not self.seen_mutation:
                self.mutation_started = now
            self.seen_mutation = True
            self.last_change = now
        elif event.get("kind") in {"click", "submit", "change"}:
            if self.pending is None:
                self.pending = {
                    "kind": event["kind"],
                    "selector": str(event.get("selector", ""))[:256],
                    "tag": str(event.get("tag", ""))[:32],
                    "from": self.current_index,
                    "started": now,
                }
            self.last_change = now

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
            edge = {k: self.pending[k] for k in ["kind", "selector", "tag", "from"]}
            edge.update({"to": idx, "outcome": "changed", "observed": True})
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
        if not self.pending and not self.seen_mutation and self.page.url == self.steps[-1]["url"]:
            return
        # Debounce rapidly changing pages, but avoid waiting forever on animations.
        age = now - self.pending["started"] if self.pending else 0
        quiet = now - self.last_change
        activity_age = age if self.pending else (now - (self.mutation_started or now))
        if quiet < 0.65 and activity_age < 2.5:
            return
        state = self.state()
        if not state:
            return
        current_signature = hashlib.sha256((state[0] + "\n" + state[1]).encode()).hexdigest()
        if current_signature != self.saved_signature:
            self.snapshot(self.pending["kind"] if self.pending else "dom-change", state)
        elif self.pending and age > 1.5:
            edge = {k: self.pending[k] for k in ["kind", "selector", "tag", "from"]}
            edge.update({"to": edge["from"], "outcome": "no-change", "observed": True})
            self.transitions.append(edge)
            self.pending = None
            self.seen_mutation = False
            self.mutation_started = None
        elif not self.pending:
            self.seen_mutation = False
            self.mutation_started = None

    def finish(self):
        self.poll()
        self.snapshot("final")
        if self.pending and self.pending["from"] >= 0:
            edge = {k: self.pending[k] for k in ["kind", "selector", "tag", "from"]}
            edge.update({"to": self.current_index, "outcome": "final", "observed": True})
            self.transitions.append(edge)
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
    print(f"Saved {len(steps)} states, {len(transitions)} action edges, {assets} assets and {count} HAR entries.")
    print("Replay:", "start-har-mock-windows.bat", str(out))

if __name__ == "__main__":
    main()
