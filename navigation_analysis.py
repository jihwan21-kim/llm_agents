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

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
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
    }
    for idx, state in enumerate(pages):
        filename = state.get("html") or f"step-{idx:03d}.html"
        item = (folder / filename).resolve(strict=True)
        if not item.is_relative_to(folder.resolve()):
            raise ValueError("Snapshot path escapes recording")
        text = item.read_text(encoding="utf-8", errors="replace")
        for hint in extract_html_navigation(text, state.get("url") or start_url):
            summary["html_routes"].append({"from": idx, **hint})

    har_path = folder / "trace.har"
    if har_path.exists():
        har = json.loads(har_path.read_text(encoding="utf-8"))
        seen = set()
        for item in har.get("log", {}).get("entries", []):
            request = item.get("request") or {}
            response = item.get("response") or {}
            mime = str((response.get("content") or {}).get("mimeType") or "").lower()
            raw_url = request.get("url") or ""
            pathname = (urlsplit(raw_url).path or "").lower()
            if request.get("method") not in {"GET", "HEAD"}:
                continue
            if not ("javascript" in mime or pathname.endswith((".js", ".mjs"))):
                continue
            # Third-party vendor bundles cannot establish a route on the
            # recorded application's origin.
            if urlsplit(raw_url).netloc.lower() != urlsplit(start_url).netloc.lower():
                continue
            payload = response.get("content") or {}
            data = payload.get("text")
            if not isinstance(data, str) or len(data) > 3_000_000:
                continue
            try:
                if payload.get("encoding") == "base64":
                    source = base64.b64decode(data, validate=True).decode("utf-8", "replace")
                else:
                    source = data
            except (ValueError, UnicodeError):
                continue
            for route in extract_js_route_literals(source, start_url):
                if route in seen:
                    continue
                seen.add(route)
                summary["js_route_hints"].append({
                    "source": "javascript_literal", "target_path": route,
                    "verified": False, "trigger_unknown": True,
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
    print("Unverified targets are not proof of a recorded user action.")
