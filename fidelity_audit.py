"""Read-only fidelity preflight for offline HAR/DOM recordings.

No network requests, original JavaScript execution, captured code output,
or credential-body inspection. Counts are diagnostics, NOT a fidelity score.
"""
from argparse import ArgumentParser
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from capture_replay import is_javascript_response


class HtmlFeatures(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.script_urls = set()
        self.inline_scripts = 0
        self.inline_handlers = 0
        self.iframe_count = 0
        self.form_count = 0
        self._script_stack = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        fields = {k.lower(): v for k, v in attrs if k}
        self.inline_handlers += sum(1 for k in fields if k.startswith("on"))
        if tag == "script":
            src = fields.get("src")
            if src:
                self.script_urls.add(urljoin(self.base_url, src))
            else:
                self.inline_scripts += 1
        elif tag in {"iframe", "frame"}:
            self.iframe_count += 1
        elif tag == "form":
            self.form_count += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def audit_recording(directory):
    """Return a non-sensitive, categorical account of original/replay gaps."""
    root = Path(directory).expanduser().resolve(strict=True)
    bundle = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    har = json.loads((root / "trace.har").read_text(encoding="utf-8"))
    steps = bundle.get("steps", [])
    transitions = bundle.get("transitions", [])
    if not steps or not isinstance(steps, list):
        raise ValueError("No recorded steps")
    start_url = bundle.get("startUrl", "")
    parts = urlsplit(start_url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Invalid recording startUrl")
    host = parts.hostname.lower()

    declared_scripts = set()
    inline_scripts = inline_handlers = iframes = forms = 0
    snapshot_paths = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("Invalid recorded step")
        raw_file = step.get("html") or f"step-{index:03d}.html"
        source_path = (root / raw_file).resolve(strict=True)
        if not source_path.is_relative_to(root):
            raise ValueError("Snapshot path outside recording")
        page_url = step.get("url") or start_url
        snapshot_paths.add(urlsplit(page_url).path or "/")
        features = HtmlFeatures(page_url)
        features.feed(source_path.read_text(encoding="utf-8", errors="replace"))
        declared_scripts |= features.script_urls
        inline_scripts += features.inline_scripts
        inline_handlers += features.inline_handlers
        iframes += features.iframe_count
        forms += features.form_count

    seen_js_urls = set()
    stored_js_urls = set()
    js_external = set()
    total_har_requests = 0
    non_get_requests = 0
    response_payloads_missing = 0
    for entry in har.get("log", {}).get("entries", []):
        request, response = entry.get("request") or {}, entry.get("response") or {}
        method = request.get("method", "")
        url = request.get("url", "")
        total_har_requests += 1
        if method not in {"GET", "HEAD", "OPTIONS"}:
            non_get_requests += 1
        mime = str((response.get("content") or {}).get("mimeType", ""))
        if not is_javascript_response(url, mime):
            continue
        seen_js_urls.add(url)
        if urlsplit(url).hostname != host:
            js_external.add(url)
        data = (response.get("content") or {}).get("text")
        if isinstance(data, str):
            stored_js_urls.add(url)
        else:
            response_payloads_missing += 1

    declared_found = len(declared_scripts & stored_js_urls)
    declared_missing = len(declared_scripts - stored_js_urls)
    known = [e for e in transitions if isinstance(e, dict)]
    observed_actions = sum(
        1 for e in known if e.get("observed")
        and e.get("kind") in {"click", "submit", "change"}
    )
    unverified_dom = sum(
        1 for e in known if e.get("kind") == "dom_settle"
        or e.get("temporal_observation")
    )
    blocked_write_edges = sum(1 for e in known if e.get("blocked_write"))
    report = {
        "recording": root.name,
        "claimed_full_original_equivalence": False,
        "mode": "sanitized_static_snapshot_replay",
        "observations": {
            "snapshots": len(steps),
            "unique_paths": len(snapshot_paths),
            "recorded_transitions": len(known),
            "observed_action_edges": observed_actions,
            "unverified_dom_edges": unverified_dom,
            "blocked_write_edges": blocked_write_edges,
            "snapshots_containing_original_script_tags": bool(inline_scripts or declared_scripts),
            "inline_script_elements": inline_scripts,
            "inline_event_handler_attributes": inline_handlers,
            "frame_elements": iframes,
            "form_elements": forms,
            "distinct_external_script_urls_in_snapshots": len(declared_scripts),
            "script_urls_with_har_response_body": declared_found,
            "script_urls_without_har_response_body": declared_missing,
            "har_requests": total_har_requests,
            "har_non_read_requests": non_get_requests,
            "javascript_har_entries": len(seen_js_urls),
            "javascript_har_entries_with_body": len(stored_js_urls),
            "javascript_har_entries_missing_body": response_payloads_missing,
            "cross_origin_javascript_urls_in_har": len(js_external),
        },
        "replay_behavior": {
            "original_inline_javascript_executes": False,
            "original_external_javascript_executes": False,
            "original_event_handlers_preserved": False,
            "iframes_preserved": False,
            "original_network_behavior_preserved": False,
            "original_backend_available": False,
            "javascript_source_read_only_archive": True,
            "unverified_dom_settling_can_be_previewed": True,
            "upstream_network_allowed": False,
        },
        "validity_warning": (
            "Visual similarity, a matching path, source-archive availability and "
            "recorded click transitions do NOT establish original JavaScript "
            "execution or end-to-end task success. Never count snapshot "
            "navigation or blocked writes as backend completion."
        ),
        "next_validation": [
            "Use an authorized, isolated synthetic fixture with reviewed JavaScript and locally simulated API responses.",
            "Compare rendered screenshots, DOM/ARIA, event traces, network metadata and resulting task states independently.",
            "Keep original-code inspection and original-code execution as distinct study conditions.",
            "Verify VM-level egress isolation and distinguish agent refusal from broken fixture behavior.",
        ],
    }
    return report


def main():
    parser = ArgumentParser(description="Audit offline replay fidelity limits without running original scripts")
    parser.add_argument("--recording", required=True, help="Folder containing bundle.json and trace.har")
    parser.add_argument("--output", help="Optional JSON report filename (otherwise stdout)")
    args = parser.parse_args()
    report = audit_recording(args.recording)
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
        print(f"Wrote fidelity preflight to {output}")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
