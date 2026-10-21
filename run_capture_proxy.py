"""Run the existing deny-upstream mitmproxy with one recorded-origin replay."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from capture_replay import CaptureReplay, SCRIPT_INDEX
from navigation_editor import (NavigationEditError, EDITOR, EDITOR_JS_PATH,
                               EDITOR_STATE, EDITOR_SAVE, EDITOR_HTML, EDITOR_JS)
from gym.fixture_receipt import parse_fixture_receipt, FixtureReceiptError
from proxy_app import MockProxy

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
        if self.capture.host in {"mock.test"}:
            raise ValueError("Cannot shadow manager host")
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
            allowed = observed or static_navigation
            event = {"time": datetime.now(timezone.utc).isoformat(),
                     "kind": payload["kind"], "step": step,
                     "to": target if allowed else step,
                     "observed_transition": observed,
                     "static_navigation": static_navigation,
                     "filled_types": kinds, "upstream_sent": False,
                     "simulated": True}
            self.capture_events.append(event)
            self.capture_events = self.capture_events[-1000:]
            self._metadata_log("capture_simulated_event", path, "POST")
            return self._respond(flow, 200, json.dumps({"recorded": True, "observed": observed,
                                                       "static_navigation": static_navigation,
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


async def run(directory, preview_dom_settling=False, trusted_fixture_js=False,
              agent_js_inspection=False):
    options = Options(listen_host="127.0.0.1", listen_port=8080,
                      confdir=str(ROOT / "mitm-ca"))
    master = DumpMaster(options)
    master.options.update(connection_strategy="lazy", upstream_cert=False,
                          stream_large_bodies=None, body_size_limit="1m")
    addon = RecordedMockProxy(directory, preview_dom_settling=preview_dom_settling,
                              trusted_fixture_js=trusted_fixture_js,
                              agent_js_inspection=agent_js_inspection)
    master.addons.add(addon)
    print("Dedicated proxy browser only. All upstream connections are DENIED.", flush=True)
    print("Open recorded URL:", addon.capture.start_url, flush=True)
    parts = urlsplit(addon.capture.start_url)
    print("Read-only JavaScript listing:",
          parts.scheme + "://" + parts.netloc + SCRIPT_INDEX,
          "(research inspection only; does not execute sources)", flush=True)
    if agent_js_inspection:
        print("RESEARCH SOURCE-VISIBLE MODE: Page includes a visible source index link.", flush=True)
        print("Never use this condition as an unmodified page-fidelity baseline.", flush=True)
    print("Synthetic events: http://mock.test/__mock_capture/events", flush=True)
    await master.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording", required=True, help="Recording folder with bundle.json")
    parser.add_argument("--preview-dom-settling", action="store_true",
                        help="Opt in to automatic local playback of unverified same-URL DOM-only snapshots")
    parser.add_argument("--trusted-fixture-js", action="store_true",
                        help="Execute only exact-hash, reviewed synthetic fixture.test app.js; "
                             "not available for captured external/phishing hosts")
    parser.add_argument("--agent-js-inspection", action="store_true",
                        help="Show a visible link to byte-preserved HAR JS sources; "
                             "sources remain text-only and unexecuted")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.recording, preview_dom_settling=args.preview_dom_settling,
                        trusted_fixture_js=args.trusted_fixture_js,
                        agent_js_inspection=args.agent_js_inspection))
    except KeyboardInterrupt:
        pass
