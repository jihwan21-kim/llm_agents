"""Run an offline functional gym site with native, site-specific JS.

Only manually reviewed built-in .test fixtures are eligible. No imported HAR,
external script, live account, dynamic third-party site, or upstream request
is supported by this entrypoint.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from gym.functional_sites import FunctionalSite, SITES
from gym.build_approved_mock import load_approved_mock
from proxy_app import MockProxy
from browser_mail import BrowserMailbox, MAIL_HOST, MAIL_URL

ROOT = Path(__file__).resolve().parent
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "form-action 'none'; frame-src 'none'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


class FunctionalGymProxy(MockProxy):
    def __init__(self, site, generated=False):
        super().__init__()
        self.site = (load_approved_mock(site) if generated else FunctionalSite(site))
        # The functional runner serves a single reviewed synthetic fixture.
        # Never advertise legacy sites here, because they are not loaded in
        # this process.
        self.mailbox = BrowserMailbox([{
            "host": self.site.host, "entry": "/", "id": "reviewed-fixture"
        }])
        print("Functional JS gym:", self.site.url, flush=True)
        print("Site-specific JavaScript loaded at /app.js; no generic sim.js",
              flush=True)
        print("All upstream connections denied; local metadata-only APIs",
              flush=True)

    def respond(self, flow, status, body=b"", mime="application/json; charset=utf-8"):
        flow.response = http.Response.make(status, body, {
            "Content-Type": mime,
            "Cache-Control": "no-store",
            "X-Mock-Proxy": "functional-gym-local-only",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CSP,
        })

    def log_metadata(self, method, path, outcome, status):
        # Never store arbitrary request bodies, cookies, headers, or query strings.
        safe = path if path in {
            "/", "/app.js", "/style.css", "/api/slots", "/api/join",
            "/__mock_capture/fixture-receipt", "/__gym/events", "/__gym/status",
        } else "<unmapped>"
        entry = {"time": datetime.now(timezone.utc).isoformat(),
                 "site": self.site.name, "method": method,
                 "path": safe, "outcome": outcome, "status": status,
                 "upstream_sent": False}
        with self.logfile.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

    def handle(self, flow):
        request = flow.request
        method = request.method.upper()
        path = urlsplit(request.path).path
        if request.port not in {80, 443} or request.headers.get("Upgrade"):
            self.log_metadata(method, path, "blocked", 403)
            return self.respond(flow, 403, b'{"error":"blocked"}')

        if request.host == MAIL_HOST:
            return super().handle(flow)

        if request.host == "mock.test":
            if path == "/__mock/mail-events":
                return super().handle(flow)
            if method != "GET":
                self.log_metadata(method, path, "manager_denied", 405)
                return self.respond(flow, 405, b'{"error":"method_not_allowed"}')
            if path == "/__gym/events":
                body = json.dumps(self.site.safe_events()).encode()
                return self.respond(flow, 200, body)
            if path == "/__gym/status":
                body = json.dumps({
                    "site": self.site.name, "url": self.site.url,
                    "source_sha256": self.site.hashes,
                    "upstream_denied": True, "mode": "functional",
                }).encode()
                return self.respond(flow, 200, body)
            self.log_metadata(method, path, "manager_unmapped", 404)
            return self.respond(flow, 404, b'{"error":"unmapped"}')

        if request.host != self.site.host:
            self.log_metadata(method, "<unmapped>", "external_blocked", 403)
            return self.respond(flow, 403, b'{"error":"no_upstream"}')

        # A JS POST must originate on the single reviewed .test origin.
        origin = request.headers.get("Origin")
        if origin is not None and origin != "https://" + self.site.host:
            self.log_metadata(method, path, "cross_origin_denied", 403)
            return self.respond(flow, 403, b'{"error":"cross_origin"}')
        if method not in {"GET", "HEAD"} and origin != "https://" + self.site.host:
            self.log_metadata(method, path, "missing_origin_denied", 403)
            return self.respond(flow, 403, b'{"error":"origin_required"}')

        mime = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        local = self.site.dispatch(method, request.path, request.raw_content or b"",
                                   content_type=mime)
        self.log_metadata(method, path,
                          "local_receipt" if local.event else "local_route",
                          local.status)
        self.respond(flow, local.status, local.body, local.mime)


async def run(site, generated=False):
    opts = Options(listen_host="127.0.0.1", listen_port=8080,
                   confdir=str(ROOT / "mitm-ca"))
    master = DumpMaster(opts)
    master.options.update(connection_strategy="lazy", upstream_cert=False,
                          body_size_limit="1m")
    addon = FunctionalGymProxy(site, generated=generated)
    master.addons.add(addon)
    print("Browser inbox:", MAIL_URL, flush=True)
    print("Opened site:", addon.site.url, flush=True)
    print("Events: http://mock.test/__gym/events", flush=True)
    print("Script hashes: http://mock.test/__gym/status", flush=True)
    print("Restart this proxy to reset deterministic fixture state.", flush=True)
    await master.run()


def main():
    parser = argparse.ArgumentParser(description="Functional first-party JS gym")
    parser.add_argument("--site", choices=sorted(SITES), required=True)
    parser.add_argument("--generated", action="store_true",
                        help="Serve byte-verified auto-generated approved site mock")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.site, generated=args.generated))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
