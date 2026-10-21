"""Run the existing deny-upstream mitmproxy with one recorded-origin replay."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from capture_replay import CaptureReplay, SCRIPT_INDEX
from navigation_editor import (NavigationEditError, EDITOR, EDITOR_JS_PATH,
                               EDITOR_STATE, EDITOR_SAVE, EDITOR_HTML, EDITOR_JS,
                               SENSITIVE_PATH, SENSITIVE_ATTR)
from gym.fixture_receipt import parse_fixture_receipt, FixtureReceiptError
from proxy_app import MockProxy, SITES
from browser_mail import BrowserMailbox, MAIL_URL
from mailbox_recordings import load_recording_directories

ROOT = Path(__file__).resolve().parent
CSP = (
    "default-src 'none'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; form-action 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
ALLOWED_FIELDS = {"email", "password", "tel", "number", "other"}


class RecordedMockProxy(MockProxy):
    def __init__(self, directory, preview_dom_settling=False,
                 trusted_fixture_js=False, agent_js_inspection=False,
                 edit_navigation=False):
        super().__init__()
        if edit_navigation and trusted_fixture_js:
            raise ValueError("Cannot combine navigation editor and trusted JS runtime")
        self.edit_navigation = bool(edit_navigation)
        self.replay_settings = dict(
            preview_dom_settling=preview_dom_settling,
            trusted_fixture_js=trusted_fixture_js,
            agent_js_inspection=agent_js_inspection)
        self.capture = CaptureReplay(
            directory, preview_dom_settling=preview_dom_settling,
            trusted_fixture_js=trusted_fixture_js,
            agent_js_inspection=agent_js_inspection)
        if self.capture.host in {"mock.test", "inbox.cedarpostmail.net"}:
            raise ValueError("Cannot shadow manager or mailbox host")
        self.mailbox = BrowserMailbox([
            *SITES.values(),
            {"host": self.capture.host, "entry": urlsplit(
                self.capture.start_url).path or "/", "id": "recorded-page"},
        ])
        self.capture_events = []
        print(f"Offline replay: {self.capture.host} with "
              f"{len(self.capture.steps)} snapshots and {len(self.capture.assets)} assets",
              flush=True)
        if self.capture.trusted_fixture_js:
            print("TRUSTED SYNTHETIC FIXTURE: one exact-hash, reviewed external "
                  "JavaScript resource is executable; no original backend. "
                  "All upstream connections remain denied.", flush=True)
        else:
            print("FIDELITY WARNING: this is sanitized static snapshot replay. "
                  "Captured original JS does NOT run; backend effects are not reproduced. "
                  "Use fidelity_audit.py for a case-specific gap report.",
                  flush=True)
        print(f"Initial displayed state: {self.capture.initial_step}",
              flush=True)
        print(f"HTML href destinations mapped: {len(self.capture.inferred_edges)} (inferred, not observed)",
              flush=True)
        print(f"DOM settling candidates: {len(self.capture.dom_settle_candidates)}; "
              f"preview {'ENABLED' if self.capture.preview_dom_settling else 'DISABLED'}",
              flush=True)
        print(f"Captured JS available for read-only inspection: "
              f"{len(self.capture.script_index)} files; "
              f"{self.capture.script_sources_skipped} skipped by safety limits.",
              flush=True)

    def _respond(self, flow, status, body=b"", mime="text/plain"):
        flow.response = http.Response.make(status, body, {
            "Content-Type": mime,
            "Cache-Control": "no-store",
            "X-Mock-Proxy": "offline-no-upstream",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                CSP.replace("frame-src 'none'", "frame-src 'self'")
                   .replace("frame-ancestors 'none'", "frame-ancestors 'self'")
                if self.edit_navigation and flow.request.host == self.capture.host
                else CSP),
        })

    def _metadata_log(self, kind, path, method):
        # Only synthetic event metadata. No query strings, headers or body.
        row = {"time": datetime.now(timezone.utc).isoformat(),
               "method": method, "path": path, "outcome": kind,
               "upstream_sent": False}
        with self.logfile.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def handle(self, flow):
        request = flow.request
        path = urlsplit(request.path).path
        # Keep the original manager and legacy mock sites unchanged.
        if request.host == "mock.test" and path == "/__mock_capture/events":
            if request.method != "GET":
                return self._respond(flow, 405)
            return self._respond(flow, 200, json.dumps(self.capture_events).encode(),
                                 "application/json; charset=utf-8")
        if request.host != self.capture.host:
            return super().handle(flow)

        if request.port not in {80, 443} or request.headers.get("Upgrade"):
            self._metadata_log("capture_blocked", path, request.method)
            return self._respond(flow, 403, b"Blocked")
        origin = request.headers.get("Origin")
        if origin is not None and origin not in {
            "http://" + self.capture.host, "https://" + self.capture.host
        }:
            self._metadata_log("capture_origin_blocked", path, request.method)
            return self._respond(flow, 403, b"Blocked")

        if self.edit_navigation and path in {
            EDITOR, EDITOR_JS_PATH, EDITOR_STATE, EDITOR_SAVE
        }:
            if path == EDITOR_SAVE:
                if (request.method != "POST" or
                        request.headers.get("Origin") !=
                        "https://" + self.capture.host):
                    return self._respond(flow, 403, b"Editor write denied")
                if request.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                    return self._respond(flow, 415, b"JSON required")
                try:
                    self.capture.navigation_editor.write(request.raw_content or b"")
                    # Rebuild the pages; do not alter bundle.json or HAR.
                    self.capture = CaptureReplay(
                        self.capture.directory, **self.replay_settings)
                except (NavigationEditError, ValueError, OSError) as exc:
                    self._metadata_log("editor_rejected", path, "POST")
                    return self._respond(flow, 400, json.dumps({
                        "error": str(exc)[:180]
                    }).encode(), "application/json; charset=utf-8")
                self._metadata_log("editor_saved", path, "POST")
                return self._respond(flow, 200, b'{"saved":true}',
                                     "application/json; charset=utf-8")
            if request.method not in {"GET", "HEAD"}:
                return self._respond(flow, 405, b"Editor is read-only for this method")
            if path == EDITOR:
                data, mime = EDITOR_HTML.encode(), "text/html; charset=utf-8"
            elif path == EDITOR_JS_PATH:
                data, mime = EDITOR_JS.encode(), "text/javascript; charset=utf-8"
            else:
                data = json.dumps(self.capture.navigation_editor.state(
                    self.capture.initial_step)).encode()
                mime = "application/json; charset=utf-8"
            return self._respond(flow, 200, data if request.method == "GET" else b"", mime)

        if path == "/__mock_capture/fixture-receipt":
            # Only the packaged trusted demo may post fixed, non-sensitive
            # request metadata. Any captured external site stays read-only.
            if not self.capture.trusted_fixture_js:
                self._metadata_log("fixture_receipt_denied", path, request.method)
                return self._respond(flow, 403, b"Fixture event disabled")
            if request.method != "POST":
                return self._respond(flow, 405, b"Method not allowed")
            if request.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                return self._respond(flow, 415, b"JSON required")
            try:
                event = parse_fixture_receipt(request.raw_content or b"")
            except FixtureReceiptError:
                self._metadata_log("fixture_receipt_rejected", path, "POST")
                return self._respond(flow, 400, b"Invalid synthetic fixture event")
            # No raw body, headers, arbitrary fields, cookies, credentials,
            # or outbound transmission are retained.
            receipt = {
                "time": datetime.now(timezone.utc).isoformat(),
                "kind": "fixture_local_receipt",
                "event": event["event"],
                "sequence": event["sequence"],
                "local_receipt": True,
                "upstream_sent": False,
                "simulated": True,
            }
            self.capture_events.append(receipt)
            self.capture_events = self.capture_events[-1000:]
            self._metadata_log("fixture_receipt_recorded", path, "POST")
            return self._respond(flow, 200, json.dumps({
                "recorded": True,
                "local_receipt": True,
                "upstream_sent": False
            }).encode(), "application/json; charset=utf-8")

        if path == "/__mock_capture/event":
            if request.method != "POST" or len(request.raw_content or b"") > 1024:
                return self._respond(flow, 413, b"Blocked")
            try:
                payload = json.loads((request.raw_content or b"").decode("utf-8"))
                if not isinstance(payload, dict) or payload.get("kind") not in {
                    "form_submit", "button_click", "field_change"
                }:
                    raise ValueError("unknown event")
                step = payload.get("step")
                kinds = payload.get("filled_types")
                target = payload.get("to")
                selector = payload.get("selector", "")
                if type(step) is not int or step < 0 or step >= len(self.capture.steps):
                    raise ValueError("invalid step")
                if type(target) is not int or target < 0 or target >= len(self.capture.steps):
                    raise ValueError("invalid target step")
                if not isinstance(selector, str) or len(selector) > 256:
                    raise ValueError("invalid selector")
                if not isinstance(kinds, list) or len(kinds) > 6 or any(
                        k not in ALLOWED_FIELDS for k in kinds):
                    raise ValueError("invalid types")
            except (ValueError, TypeError, UnicodeError):
                return self._respond(flow, 400, b"Invalid synthetic event")
            action_kinds = {
                "button_click": {"click", "submit"},
                "form_submit": {"submit"},
                "field_change": {"change"},
            }
            observed = any(
                edge.get("from") == step and edge.get("to") == target
                and edge.get("kind") in action_kinds[payload["kind"]]
                and edge.get("selector") == selector
                and bool(edge.get("observed"))
                for edge in self.capture.transitions
            )
            static_navigation = any(
                edge["from"] == step and edge["to"] == target
                and edge["selector"] == selector and edge["kind"] == "click"
                and edge["outcome"] == "html-href"
                for edge in self.capture.inferred_edges
            ) if payload["kind"] == "button_click" else False
            manual_navigation = any(
                item["from"] == step and item["to"] == target
                and item["selector"] == selector
                for item in self.capture.manual_edges
            ) if payload["kind"] == "button_click" else False
            allowed = observed or static_navigation or manual_navigation
            event = {"time": datetime.now(timezone.utc).isoformat(),
                     "kind": payload["kind"], "step": step,
                     "to": target if allowed else step,
                     "observed_transition": observed,
                     "static_navigation": static_navigation,
                     "manual_navigation": manual_navigation,
                     "filled_types": kinds, "upstream_sent": False,
                     "simulated": True}
            self.capture_events.append(event)
            self.capture_events = self.capture_events[-1000:]
            self._metadata_log("capture_simulated_event", path, "POST")
            return self._respond(flow, 200, json.dumps({"recorded": True, "observed": observed,
                                                       "static_navigation": static_navigation,
                                                       "manual_navigation": manual_navigation,
                                                       "to": target if allowed else step}).encode(),
                                 "application/json; charset=utf-8")

        if request.method not in {"GET", "HEAD"}:
            self._metadata_log("capture_write_blocked", path, request.method)
            return self._respond(flow, 405, b"Writes disabled")
        query = urlsplit(request.path).query
        status, body, mime = self.capture.respond(request.method, path, query)
        self._metadata_log("capture_asset_or_page" if status == 200 else "capture_miss",
                           path, request.method)
        return self._respond(flow, status, body, mime)


class _BenignPageParser(HTMLParser):
    """Only permit ordinary recorded button clicks on non-form UI screens."""

    def __init__(self):
        super().__init__()
        self.sensitive = False
        self.heading_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"title", "h1", "h2"}:
            self.heading_depth += 1
        attrs = {key.lower(): str(value or "") for key, value in attrs if key}
        # A form can submit credentials, an OTP, or other entered data. It
        # remains inert even when its button looks visually ordinary.
        if tag in {"form", "textarea", "select"}:
            self.sensitive = True
        if tag == "input":
            kind = attrs.get("type", "text").lower()
            if kind not in {"hidden", "button", "submit", "reset",
                            "checkbox", "radio", "search"}:
                self.sensitive = True
            if any(SENSITIVE_ATTR.search(attrs.get(name, "")) for name in
                   ("type", "name", "id", "placeholder", "autocomplete", "aria-label")):
                self.sensitive = True

    def handle_endtag(self, tag):
        if tag in {"title", "h1", "h2"}:
            self.heading_depth = max(0, self.heading_depth - 1)

    def handle_data(self, data):
        if self.heading_depth and re.search(
                r"\\b(?:log\\s*in|sign\\s*in|password|otp|verify|verification|"
                r"authentication|payment|checkout)\\b", data, re.I):
            self.sensitive = True


class ConfiguredMailboxProxy(MockProxy):
    """Serve registered offline recordings together in a local-only inbox.

    The existing simulator may replay verified non-form, non-sensitive button
    transitions. Original captured scripts and all actual form submissions are
    still disabled. Each host keeps an independent recorded state graph.
    """

    INERT_CSP = (
        "default-src 'none'; script-src 'none'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'none'; form-action 'none'; "
        "frame-src 'none'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'"
    )
    REPLAY_CSP = INERT_CSP.replace("script-src 'none'", "script-src 'self'").replace(
        "connect-src 'none'", "connect-src 'self'")

    def __init__(self, config_path):
        super().__init__()
        self.captures = {}
        self.benign_steps = {}
        for folder in load_recording_directories(config_path):
            capture = CaptureReplay(folder)
            scheme = urlsplit(capture.start_url).scheme
            if scheme != "https":
                raise ValueError(f"Mailbox recording needs HTTPS startUrl: {folder}")
            if capture.host in {*SITES, "mock.test", "inbox.cedarpostmail.net"}:
                raise ValueError(f"Recording host conflicts with a built-in host: {capture.host}")
            if capture.host in self.captures:
                raise ValueError(f"Two recordings use the same host: {capture.host}")
            self.captures[capture.host] = capture
            safe = set()
            for index, step in enumerate(capture.steps):
                step_url = urlsplit(step.get("url") or capture.start_url)
                if (step_url.hostname != capture.host or
                        SENSITIVE_PATH.search(step_url.path)):
                    continue
                filename = step.get("html") or f"step-{index:03d}.html"
                raw = (capture.directory / filename).read_text(
                    encoding="utf-8", errors="replace")
                parser = _BenignPageParser()
                parser.feed(raw)
                if not parser.sensitive:
                    safe.add(index)
            self.benign_steps[capture.host] = safe
        if not self.captures:
            raise ValueError("No local recording could be loaded from mailbox config")
        self.mailbox = BrowserMailbox([
            *SITES.values(),
            *[
                {"host": capture.host,
                 "entry": urlsplit(capture.start_url).path or "/",
                 "id": "recording-preview"}
                for capture in self.captures.values()
            ],
        ])
        for capture in self.captures.values():
            print(f"Mailbox recording: {capture.host} from {capture.directory} "
                  f"({len(capture.steps)} screens, "
                  f"{len(self.benign_steps[capture.host])} non-form states eligible "
                  "for recorded button navigation)", flush=True)

    def _displayed_step(self, capture, path, query):
        requested = parse_qs(query).get("_step")
        if requested is not None:
            if len(requested) != 1 or not requested[0].isdecimal():
                return None
            index = int(requested[0])
        elif path == (urlsplit(capture.start_url).path or "/"):
            index = capture.initial_step
        else:
            index = next((i for i, st in enumerate(capture.steps)
                          if (urlsplit(st.get("url") or capture.start_url).path
                              or "/") == path), None)
        if index is None or index >= len(capture.steps):
            return None
        step_url = urlsplit(capture.steps[index].get("url") or capture.start_url)
        return index if (step_url.hostname == capture.host and
                         (step_url.path or "/") == path) else None

    def _replay_click(self, flow, capture):
        request = flow.request
        if request.method != "POST":
            return self.reply(flow, 405, b"Method not allowed", "text/plain")
        if (request.headers.get("Origin") != "https://" + capture.host or
                request.headers.get("Content-Type", "").split(";", 1)[0].lower()
                != "application/json"):
            return self.reply(flow, 403, b"Local event refused", "text/plain")
        raw = request.raw_content or b""
        if not 1 <= len(raw) <= 1024:
            return self.reply(flow, 413, b"Invalid event length", "text/plain")
        try:
            data = json.loads(raw.decode("utf-8"))
            source = data.get("step")
            dest = data.get("to")
            selector = data.get("selector")

        except (ValueError, TypeError, UnicodeDecodeError, AttributeError):
            return self.reply(flow, 400, b"Non-form recorded click required", "text/plain")
        # Never trust the JS-supplied destination or observed flag: independently
        # match an observed click, a unique static anchor, or a saved benign edge.
        observed = any(
            edge.get("from") == source and edge.get("to") == dest and
            edge.get("selector") == selector and edge.get("kind") == "click" and
            edge.get("outcome") == "changed" and edge.get("observed") is True
            for edge in capture.transitions
        )
        static_navigation = any(
            edge["from"] == source and edge["to"] == dest and
            edge["selector"] == selector and edge["kind"] == "click" and
            edge["outcome"] == "html-href"
            for edge in capture.inferred_edges
        )
        manual_navigation = any(
            edge["from"] == source and edge["to"] == dest and
            edge["selector"] == selector
            for edge in capture.manual_edges
        )
        allowed = observed or static_navigation or manual_navigation
        response = {
            "recorded": True, "observed": observed,
            "static_navigation": static_navigation,
            "manual_navigation": manual_navigation,
            "to": dest if allowed else source
        }
        return self.reply(flow, 200, json.dumps(response).encode(),
                          "application/json; charset=utf-8")

    def handle(self, flow):
        request = flow.request
        capture = self.captures.get(request.host)
        if capture is None:
            return super().handle(flow)
        path = urlsplit(request.path).path
        if (request.port not in {80, 443} or request.headers.get("Upgrade")
                or request.headers.get("Origin") not in {
                    None, "http://" + capture.host, "https://" + capture.host
                }):
            return self.reply(flow, 403, b"Offline mock request blocked", "text/plain")
        if path == "/__mock_capture/event":
            return self._replay_click(flow, capture)
        # No external HTTP writes, original captured JS, or credential receipt.
        if request.method not in {"GET", "HEAD"}:
            return self.reply(flow, 405, b"Read-only recording", "text/plain")
        query = urlsplit(request.path).query
        status, body, mime = capture.respond(request.method, path, query)
        self.reply(flow, status, body, mime)
        index = self._displayed_step(capture, path, query)
        # Only non-form states can execute our own offline simulator script.
        # Captured original site scripts are stripped by CaptureReplay.
        csp = (self.REPLAY_CSP if index in self.benign_steps[capture.host]
               else self.INERT_CSP)
        flow.response.headers["Content-Security-Policy"] = csp
        flow.response.headers["X-Mock-Proxy"] = "offline-static-no-upstream"

async def run(directory=None, preview_dom_settling=False, trusted_fixture_js=False,
              agent_js_inspection=False, edit_navigation=False,
              config_path=None):
    options = Options(listen_host="127.0.0.1", listen_port=8080,
                      confdir=str(ROOT / "mitm-ca"))
    master = DumpMaster(options)
    master.options.update(connection_strategy="lazy", upstream_cert=False,
                          stream_large_bodies=None, body_size_limit="1m")
    if config_path is not None:
        if any((preview_dom_settling, trusted_fixture_js, agent_js_inspection,
                edit_navigation)):
            raise ValueError("Configured mailbox mode is read-only and cannot use replay flags")
        addon = ConfiguredMailboxProxy(config_path)
    else:
        addon = RecordedMockProxy(directory, preview_dom_settling=preview_dom_settling,
                                  trusted_fixture_js=trusted_fixture_js,
                                  agent_js_inspection=agent_js_inspection,
                                  edit_navigation=edit_navigation)
    master.addons.add(addon)
    print("Dedicated proxy browser only. All upstream connections are DENIED.", flush=True)
    if isinstance(addon, RecordedMockProxy):
        print("Open recorded URL:", addon.capture.start_url, flush=True)
        parts = urlsplit(addon.capture.start_url)
        print("Read-only JavaScript listing:",
              parts.scheme + "://" + parts.netloc + SCRIPT_INDEX,
              "(research inspection only; does not execute sources)", flush=True)
        if agent_js_inspection:
            print("RESEARCH SOURCE-VISIBLE MODE: Page includes a visible source index link.", flush=True)
            print("Never use this condition as an unmodified page-fidelity baseline.", flush=True)
        if edit_navigation:
            print("Visual navigation editor:", parts.scheme + "://" + parts.netloc + EDITOR,
                  "(benign screens only; persisted local overrides)", flush=True)
        print("Synthetic events: http://mock.test/__mock_capture/events", flush=True)
    else:
        print("Configured recordings: recorded benign button clicks only; no form submission or captured JS.", flush=True)
    print("Browser inbox:", MAIL_URL, flush=True)
    print("Mailbox click metadata: http://mock.test/__mock/mail-events", flush=True)
    await master.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--recording", help="One recording folder with bundle.json")
    sources.add_argument("--recordings-config",
                         help="JSON listing local recordings to show together in the inbox")
    parser.add_argument("--preview-dom-settling", action="store_true",
                        help="Opt in to automatic local playback of unverified same-URL DOM-only snapshots")
    parser.add_argument("--trusted-fixture-js", action="store_true",
                        help="Execute only exact-hash, reviewed synthetic fixture.test app.js; "
                             "not available for captured external/phishing hosts")
    parser.add_argument("--agent-js-inspection", action="store_true",
                        help="Show a visible link to byte-preserved HAR JS sources; "
                             "sources remain text-only and unexecuted")
    parser.add_argument("--edit-navigation", action="store_true",
                        help="Enable the visual editor for benign recorded navigation")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.recording, preview_dom_settling=args.preview_dom_settling,
                        trusted_fixture_js=args.trusted_fixture_js,
                        agent_js_inspection=args.agent_js_inspection,
                        edit_navigation=args.edit_navigation,
                        config_path=args.recordings_config))
    except KeyboardInterrupt:
        pass
