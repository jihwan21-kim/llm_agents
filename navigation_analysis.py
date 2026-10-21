"""Offline navigation evidence extractor. Never executes captured JavaScript.

Recorded pages and GET/HEAD HAR script bodies can reveal explicit navigation
targets. Findings are clues, not evidence that a UI interaction reached them.
Passwords, form values, cookies, queries and script bodies are not exported.
"""
import argparse
import base64
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit


def local_path(raw, page_url):
    """Return a same-origin path without query/fragment, or None."""
    if not isinstance(raw, str) or not raw.strip() or raw.strip().startswith(("#", "javascript:", "data:")):
        return None
    base, target = urlsplit(page_url), urlsplit(urljoin(page_url, raw))
    if (target.scheme, target.netloc.lower()) != (base.scheme, base.netloc.lower()):
        return None
    path = target.path or "/"
    if len(path) > 300 or any(ord(c) < 32 for c in path):
        return None
    return path


class HTMLNavigationParser(HTMLParser):
    def __init__(self, source_url):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.anchors = 0
        self.forms = 0
        self.routes = []
        self.button_count = 0
        self.role_button_count = 0

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "button":
            self.button_count += 1
        if props.get("role", "").lower() == "button":
            self.role_button_count += 1
        if tag == "a":
            index = self.anchors
            self.anchors += 1
            path = local_path(props.get("href"), self.source_url)
            if path is not None:
                self.routes.append({
                    "source": "html_href", "kind": "anchor",
                    "selector": f'a[data-mock-link-index="{index}"]',
                    "target_path": path, "verified": False,
                })
        elif tag == "form":
            self.forms += 1
            path = local_path(props.get("action"), self.source_url)
            if path is not None:
                self.routes.append({
                    "source": "html_form", "kind": "form",
                    "method": (props.get("method") or "GET").upper()[:8],
                    "target_path": path, "verified": False,
                })

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def extract_html_navigation(source, source_url):
    parser = HTMLNavigationParser(source_url)
    parser.feed(source)
    parser.close()
    return parser.routes


# Only recognize explicit literal local paths. Don't claim to resolve closure
# variables, minified dispatch tables, computed routes or server responses.
JS_ROUTE = re.compile(
    r"""(?:\b(?:navigate|router\.(?:push|replace)|location\.(?:assign|replace)|"""
    r"""window\.location\.(?:assign|replace))\s*\(\s*"""
    r"""|\b(?:window\.)?location(?:\.href)?\s*=\s*)"""
    r"""(["'])(/[^"'\s\\]{1,160})\1""",
    re.I,
)


def extract_js_route_literals(source, page_url, limit=100):
    result = []
    seen = set()
    for match in JS_ROUTE.finditer(source):
        path = local_path(match.group(2), page_url)
        if path is not None and path not in seen:
            seen.add(path)
            result.append(path)
            if len(result) >= limit:
                break
    return result



def graph_coverage(steps, transitions):
    """Audit observed links without inventing paths for orphaned states."""
    adjacency, edges, invalid = {}, [], 0
    for t in transitions:
        source, dest = t.get("from"), t.get("to")
        if (type(source) is not int or type(dest) is not int or source < 0 or
                dest < 0 or source >= len(steps) or dest >= len(steps)):
            invalid += 1
            continue
        edges.append({"from": source, "to": dest, "kind": t.get("kind"),
                      "outcome": t.get("outcome"), "observed": bool(t.get("observed"))})
        if source != dest and t.get("observed"):
            adjacency.setdefault(source, set()).add(dest)
    entry = next((e["from"] for e in edges if e["from"] != e["to"]), 0)
    reachable, pending = set(), [entry] if steps else []
    while pending:
        node = pending.pop()
        if node in reachable:
            continue
        reachable.add(node)
        pending.extend(adjacency.get(node, set()) - reachable)
    return {"entry_state_candidate": entry, "observed_edges": edges,
            "invalid_edges": invalid,
            "no_change_edge_count": sum(e["from"] == e["to"] for e in edges),
            "reachable_states": sorted(reachable),
            "unreachable_states": sorted(set(range(len(steps))) - reachable)}


def script_entry(request, response):
    path = urlsplit(request.get("url") or "").path.lower()
    mime = str((response.get("content") or {}).get("mimeType") or "").lower()
    return "javascript" in mime or path.endswith((".js", ".mjs", ".cjs"))


def decode_script(payload):
    raw = payload.get("text")
    if not isinstance(raw, str) or len(raw) > 6_000_000:
        return None
    try:
        source = (base64.b64decode(raw, validate=True).decode("utf-8", "replace")
                  if payload.get("encoding") == "base64" else raw)
    except (UnicodeError, ValueError):
        return None
    return source if len(source) <= 3_000_000 else None



def analyze_recording(directory):
    folder = Path(directory)
    bundle = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    pages = bundle.get("steps") or []
    start_url = bundle["startUrl"]
    summary = {
        "version": 1, "analysis_only": True,
        "caution": "HTML href and JavaScript literals are hypotheses, not observed transitions.",
        "recorded_states": len(pages),
        "observed_transition_count": len(bundle.get("transitions") or []),
        "html_routes": [], "js_route_hints": [],
        "html_coverage": {"anchor_tags": 0, "form_tags": 0, "button_tags": 0,
                          "role_button_tags": 0},
        "har_coverage": {"entries": 0, "script_entries": 0,
                         "first_party_scripts": 0, "external_scripts": 0,
                         "script_bodies_analyzed": 0, "unavailable_script_bodies": 0},
        "graph": graph_coverage(pages, bundle.get("transitions") or []),
    }
    for idx, state in enumerate(pages):
        filename = state.get("html") or f"step-{idx:03d}.html"
        item = (folder / filename).resolve(strict=True)
        if not item.is_relative_to(folder.resolve()):
            raise ValueError("Snapshot path escapes recording")
        text = item.read_text(encoding="utf-8", errors="replace")
        parser = HTMLNavigationParser(state.get("url") or start_url)
        parser.feed(text)
        parser.close()
        summary["html_routes"].extend({"from": idx, **hint} for hint in parser.routes)
        summary["html_coverage"]["anchor_tags"] += parser.anchors
        summary["html_coverage"]["form_tags"] += parser.forms
        summary["html_coverage"]["button_tags"] += parser.button_count
        summary["html_coverage"]["role_button_tags"] += parser.role_button_count

    har_path = folder / "trace.har"
    if har_path.exists():
        har = json.loads(har_path.read_text(encoding="utf-8"))
        items = har.get("log", {}).get("entries", [])
        coverage = summary["har_coverage"]
        coverage["entries"] = len(items)
        seen = set()
        for item in items:
            request = item.get("request") or {}
            response = item.get("response") or {}
            if request.get("method") not in {"GET", "HEAD"}:
                continue
            if not script_entry(request, response):
                continue
            coverage["script_entries"] += 1
            origin = ("first_party" if urlsplit(request.get("url") or "").netloc.lower()
                      == urlsplit(start_url).netloc.lower() else "external")
            coverage["first_party_scripts" if origin == "first_party" else "external_scripts"] += 1
            source = decode_script(response.get("content") or {})
            if source is None:
                coverage["unavailable_script_bodies"] += 1
                continue
            coverage["script_bodies_analyzed"] += 1
            # Paths in CDN/vendor bundles are less reliable hints. Source
            # origin is always labeled; these do not become replay edges.
            for route in extract_js_route_literals(source, start_url):
                key = (origin, route)
                if key in seen:
                    continue
                seen.add(key)
                summary["js_route_hints"].append({
                    "source": "javascript_literal", "target_path": route,
                    "script_origin": origin, "verified": False,
                    "trigger_unknown": True,
                })
                if len(seen) >= 200:
                    break
            if len(seen) >= 200:
                break
    summary["html_route_count"] = len(summary["html_routes"])
    summary["js_route_hint_count"] = len(summary["js_route_hints"])
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect saved HTML/JS navigation hints without running scripts")
    parser.add_argument("recording", help="Folder containing bundle.json and trace.har")
    args = parser.parse_args()
    folder = Path(args.recording)
    report = analyze_recording(folder)
    path = folder / "navigation-analysis.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved navigation clues: {path}")
    print(f"HTML targets: {report['html_route_count']}; JavaScript literal targets: {report['js_route_hint_count']}")
    c = report["har_coverage"]
    h = report["html_coverage"]
    g = report["graph"]
    print(f"HTML elements: {h['anchor_tags']} anchors, {h['form_tags']} forms, "
          f"{h['button_tags']} buttons, {h['role_button_tags']} role-buttons.")
    print(f"HAR scripts: {c['script_entries']} "
          f"(same-origin: {c['first_party_scripts']}, external: {c['external_scripts']}); "
          f"analyzed bodies: {c['script_bodies_analyzed']}.")
    print(f"Observed graph: {len(g['observed_edges'])} edges; "
          f"{len(g['reachable_states'])}/{report['recorded_states']} states reachable.")
    print("Zero literal route hints does not mean navigation was not recorded.")
    print("Unverified targets are not proof of a recorded user action.")
