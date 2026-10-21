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

from capture_replay import CaptureReplay
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
    def __init__(self, directory, preview_dom_settling=False):
        super().__init__()
        self.capture = CaptureReplay(directory, preview_dom_settling=preview_dom_settling)
        if self.capture.host in {"mock.test"}:
            raise ValueError("Cannot shadow manager host")
        self.capture_events = []
        print(f"Offline replay: {self.capture.host} with "
              f"{len(self.capture.steps)} snapshots and {len(self.capture.assets)} assets",
              flush=True)
        print(f"Initial displayed state: {self.capture.initial_step}",
              flush=True)
        print(f"HTML href destinations mapped: {len(self.capture.inferred_edges)} (inferred, not observed)",
              flush=True)
        print(f"DOM settling candidates: {len(self.capture.dom_settle_candidates)}; "
              f"preview {'ENABLED' if self.capture.preview_dom_settling else 'DISABLED'}",
              flush=True)

    def _respond(self, flow, status, body=b"", mime="text/plain"):
        flow.response = http.Response.make(status, body, {
            "Content-Type": mime,
            "Cache-Control": "no-store",
            "X-Mock-Proxy": "offline-no-upstream",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CSP,
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


async def run(directory, preview_dom_settling=False):
    options = Options(listen_host="127.0.0.1", listen_port=8080,
                      confdir=str(ROOT / "mitm-ca"))
    master = DumpMaster(options)
    master.options.update(connection_strategy="lazy", upstream_cert=False,
                          stream_large_bodies=None, body_size_limit="1m")
    addon = RecordedMockProxy(directory, preview_dom_settling=preview_dom_settling)
    master.addons.add(addon)
    print("Dedicated proxy browser only. All upstream connections are DENIED.", flush=True)
    print("Open recorded URL:", addon.capture.start_url, flush=True)
    print("Synthetic events: http://mock.test/__mock_capture/events", flush=True)
    await master.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording", required=True, help="Recording folder with bundle.json")
    parser.add_argument("--preview-dom-settling", action="store_true",
                        help="Opt in to automatic local playback of unverified same-URL DOM-only snapshots")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.recording, preview_dom_settling=args.preview_dom_settling))
    except KeyboardInterrupt:
        pass
