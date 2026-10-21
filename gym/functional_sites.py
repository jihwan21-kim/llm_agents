"""First-party, offline functional JavaScript gym.

Only manually reviewed, repository-bundled synthetic applications can run.
Never import HAR scripts, external URLs, user-supplied directories or executable
third-party scripts into this runtime. This module performs no network I/O.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITES = {
    "js-demo": {
        "host": "fixture.test",
        "root": "gym/fixtures/js-demo",
        "files": {"/": "index.html", "/app.js": "app.js",
                  "/style.css": "style.css"},
        "api": "basket",
    },
    "study-board": {
        "host": "studyboard.test",
        "root": "gym/fixtures/study-board",
        "files": {"/": "index.html", "/app.js": "app.js",
                  "/style.css": "style.css"},
        "api": "study",
    },
}
MIMES = {".html": "text/html; charset=utf-8",
         ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8"}
STUDY_INITIAL = {
    "study": {"title": "Library study circle", "capacity": 4, "joined": 0},
    "lunch": {"title": "Campus lunch", "capacity": 3, "joined": 0},
    "coffee": {"title": "Coffee break", "capacity": 2, "joined": 0},
}


@dataclass(frozen=True)
class LocalReply:
    status: int
    body: bytes
    mime: str = "application/json; charset=utf-8"
    event: dict | None = None


def json_reply(status, data, event=None):
    return LocalReply(status, json.dumps(data, separators=(",", ":")).encode(),
                      event=event)


def json_payload(raw, *, fields):
    # Parse only small, deterministic, non-identifying synthetic schemas.
    if not isinstance(raw, bytes) or not 2 <= len(raw) <= 128:
        raise ValueError("Invalid local payload length")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid local JSON") from exc
    if not isinstance(obj, dict) or set(obj) != set(fields):
        raise ValueError("Unexpected local payload keys")
    return obj


class FunctionalSite:
    """Dispatch static reviewed assets and explicitly enumerated local APIs."""

    def __init__(self, name):
        if name not in SITES:
            raise ValueError("Unknown first-party fixture")
        config = SITES[name]
        self.name = name
        self.host = config["host"]
        if not self.host.endswith(".test") or self.host == "mock.test":
            raise ValueError("Fixture must use reserved .test origin")
        self.root = (ROOT / config["root"]).resolve(strict=True)
        if not self.root.is_relative_to((ROOT / "gym/fixtures").resolve()):
            raise ValueError("Fixture path outside reviewed source tree")
        self.api = config["api"]
        self.assets = {}
        self.hashes = {}
        for path, filename in config["files"].items():
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError("Invalid static URL path")
            source = (self.root / filename).resolve(strict=True)
            if not source.is_relative_to(self.root):
                raise ValueError("Path leaves reviewed fixture")
            data = source.read_bytes()
            if len(data) > 1024 * 1024:
                raise ValueError("Reviewed asset exceeds fixed size budget")
            self.assets[path] = (data, MIMES[source.suffix])
            self.hashes[path] = hashlib.sha256(data).hexdigest()
        self.events = []
        self.study = {key: dict(value) for key, value in STUDY_INITIAL.items()}

    @property
    def url(self):
        return "https://" + self.host + "/"

    def dispatch(self, method, request_path, body=b"", content_type=""):
        """Return an inert local response. No network and no raw body logging."""
        path = urlsplit(request_path).path
        if path in self.assets:
            if method not in {"GET", "HEAD"}:
                return json_reply(405, {"error": "method_not_allowed"})
            raw, mime = self.assets[path]
            return LocalReply(200, raw if method == "GET" else b"", mime)

        if self.api == "basket" and path == "/__mock_capture/fixture-receipt":
            if method != "POST":
                return json_reply(405, {"error": "method_not_allowed"})
            if content_type != "application/json":
                return json_reply(415, {"error": "json_required"})
            try:
                entry = json_payload(body, fields=("event", "sequence"))
                if entry["event"] != "basket_add" or (
                    type(entry["sequence"]) is not int
                    or not 1 <= entry["sequence"] <= 1000
                ):
                    raise ValueError("Invalid fixture event")
            except ValueError:
                return json_reply(400, {"error": "invalid_fixture_event"})
            event = {"kind": "basket_add", "sequence": entry["sequence"],
                     "local_receipt": True, "upstream_sent": False}
            self.events.append(event)
            return json_reply(200, {"recorded": True, "local_receipt": True,
                                    "upstream_sent": False}, event)

        if self.api == "study" and path == "/api/slots":
            if method != "GET":
                return json_reply(405, {"error": "method_not_allowed"})
            # No individual identities, accounts, email, or tokens.
            return json_reply(200, {"slots": [
                {"id": key, **slot} for key, slot in self.study.items()
            ]})

        if self.api == "study" and path == "/api/join":
            if method != "POST":
                return json_reply(405, {"error": "method_not_allowed"})
            if content_type != "application/json":
                return json_reply(415, {"error": "json_required"})
            try:
                entry = json_payload(body, fields=("slot",))
                slot = entry["slot"]
                if not isinstance(slot, str) or slot not in self.study:
                    raise ValueError("Unknown slot")
            except ValueError:
                return json_reply(400, {"error": "invalid_fixture_event"})
            state = self.study[slot]
            if state["joined"] >= state["capacity"]:
                return json_reply(409, {"error": "full"})
            state["joined"] += 1
            event = {"kind": "slot_join", "slot": slot,
                     "count": state["joined"], "local_receipt": True,
                     "upstream_sent": False}
            self.events.append(event)
            return json_reply(200, {"joined": True, "slot": slot,
                                    "count": state["joined"],
                                    "upstream_sent": False}, event)

        return json_reply(404, {"error": "no_reviewed_route"})

    def safe_events(self):
        return list(self.events[-1000:])
