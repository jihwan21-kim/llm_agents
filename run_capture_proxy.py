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
    def __init__(self, directory):
        super().__init__()
        self.capture = CaptureReplay(directory)
        if self.capture.host in {"mock.test"}:
            raise ValueError("Cannot shadow manager host")
        self.capture_events = []
        print(f"Offline replay: {self.capture.host} with "
              f"{len(self.capture.steps)} snapshots and {len(self.capture.assets)} assets",
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
                    "form_submit", "button_click"
                }:
                    raise ValueError("unknown event")
                step = payload.get("step")
                kinds = payload.get("filled_types")
                if type(step) is not int or step < 0 or step >= len(self.capture.steps):
                    raise ValueError("invalid step")
                if not isinstance(kinds, list) or len(kinds) > 6 or any(
                        k not in ALLOWED_FIELDS for k in kinds):
                    raise ValueError("invalid types")
            except (ValueError, TypeError, UnicodeError):
                return self._respond(flow, 400, b"Invalid synthetic event")
            event = {"time": datetime.now(timezone.utc).isoformat(),
                     "kind": payload["kind"], "step": step,
                     "filled_types": kinds, "upstream_sent": False,
                     "simulated": True}
            self.capture_events.append(event)
            self.capture_events = self.capture_events[-1000:]
            self._metadata_log("capture_simulated_event", path, "POST")
            return self._respond(flow, 200, b'{"recorded":true}',
                                 "application/json; charset=utf-8")

        if request.method not in {"GET", "HEAD"}:
            self._metadata_log("capture_write_blocked", path, request.method)
            return self._respond(flow, 405, b"Writes disabled")
        query = urlsplit(request.path).query
        status, body, mime = self.capture.respond(request.method, path, query)
        self._metadata_log("capture_asset_or_page" if status == 200 else "capture_miss",
                           path, request.method)
        return self._respond(flow, status, body, mime)


async def run(directory):
    options = Options(listen_host="127.0.0.1", listen_port=8080,
                      confdir=str(ROOT / "mitm-ca"))
    master = DumpMaster(options)
    master.options.update(connection_strategy="lazy", upstream_cert=False,
                          stream_large_bodies=None, body_size_limit="1m")
    addon = RecordedMockProxy(directory)
    master.addons.add(addon)
    print("Dedicated proxy browser only. All upstream connections are DENIED.", flush=True)
    print("Open recorded URL:", addon.capture.start_url, flush=True)
    print("Synthetic events: http://mock.test/__mock_capture/events", flush=True)
    await master.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording", required=True, help="Recording folder with bundle.json")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.recording))
    except KeyboardInterrupt:
        pass
