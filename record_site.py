"""Record browser workflow data for offline mock testing.

Run only with synthetic values. HAR and DOM snapshots can contain sensitive data.
Raw HAR is sanitized before retention; recordings are gitignored.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parent
MARKER = "__MOCK_RECORD_EVENT__"
INIT_SCRIPT = r"""
(() => {
  const send = (kind, extra = {}) => console.log(
    "__MOCK_RECORD_EVENT__" + JSON.stringify({kind, ...extra})
  );
  document.addEventListener("submit", e => send("submit", {
    field_types: [...e.target.querySelectorAll("input")].map(x => x.type).slice(0, 20)
  }), true);
  document.addEventListener("click", e => {
    const el = e.target.closest("button, input[type=submit], a");
    if (el) send("click", {tag: el.tagName.toLowerCase()});
  }, true);
})();
"""

def sanitize_har(raw_file, clean_file):
    data = json.loads(raw_file.read_text(encoding="utf-8"))
    # Only retrievals are needed for static resource replay. Never retain
    # submitted bodies, cookies, authorization or request/response headers.
    entries = []
    for entry in data.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        response = entry.get("response", {})
        if request.get("method", "").upper() not in {"GET", "HEAD"}:
            continue
        request["headers"] = []
        request["cookies"] = []
        request.pop("postData", None)
        request["queryString"] = []
        response["headers"] = []
        response["cookies"] = []
        entry.pop("_initiator", None)
        entries.append(entry)
    data["log"]["entries"] = entries
    data["log"]["pages"] = []  # Page titles can contain personal data.
    clean_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return len(entries)

def main():
    parser = argparse.ArgumentParser(description="Capture HAR + DOM snapshots for offline replay")
    parser.add_argument("--url", required=True)
    parser.add_argument("--app", required=True, help="Short local ID, e.g. demo-shop")
    parser.add_argument("--name", default="workflow")
    parser.add_argument("--browser-channel", choices=["chrome", "chromium"], default="chrome")
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        parser.error("--url must be an http(s) URL")
    for value in [args.app, args.name]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
            parser.error("--app/--name may contain only letters, numbers, underscores and hyphens")

    run_id = args.name + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "recordings" / args.app / run_id
    out.mkdir(parents=True, exist_ok=False)
    steps, actions = [], []
    raw_har = out / "trace.raw.har"
    print("Recording to:", out)
    print("USE ONLY SYNTHETIC TEST DATA. Do not enter real credentials.")
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
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()

        def on_console(msg):
            text = msg.text
            if not text.startswith(MARKER):
                return
            try:
                event = json.loads(text[len(MARKER):])
                if event.get("kind") in {"submit", "click"}:
                    actions.append({"time": datetime.now(timezone.utc).isoformat(),
                                    "kind": event["kind"],
                                    "tag": event.get("tag"),
                                    "field_types": event.get("field_types", [])})
            except (ValueError, TypeError):
                pass
        page.on("console", on_console)
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            print("Navigation timed out; continuing with the current page.")

        def snapshot():
            index = len(steps)
            base = "step-" + str(index).zfill(3)
            page.screenshot(path=str(out / (base + ".png")), full_page=True)
            (out / (base + ".html")).write_text(page.content(), encoding="utf-8")
            steps.append({"index": index, "url": page.url,
                          "html": base + ".html", "screenshot": base + ".png"})
            print("Saved snapshot", index, page.url)

        print("Browse in Chrome. In THIS terminal: s + Enter = snapshot; q + Enter = finish.")
        try:
            while True:
                key = input("capture> ").strip().lower()
                if key == "s":
                    snapshot()
                elif key == "q":
                    snapshot()  # Always save final state.
                    break
                else:
                    print("Use s or q.")
        finally:
            context.close()  # HAR is flushed here.
            browser.close()

    if not steps:
        raise RuntimeError("No snapshots recorded.")
    try:
        count = sanitize_har(raw_har, out / "trace.har")
    finally:
        raw_har.unlink(missing_ok=True)
    bundle = {"app": args.app, "id": run_id, "name": args.name,
              "startUrl": args.url, "steps": steps,
              "harFile": "trace.har", "harGetEntries": count}
    (out / "bundle.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    (out / "actions.json").write_text(json.dumps(actions, indent=2), encoding="utf-8")
    print(f"Saved {len(steps)} DOM snapshots and {count} GET/HEAD HAR entries to {out}")
    print("Preview: start-har-mock-windows.bat", str(out))

if __name__ == "__main__":
    main()
