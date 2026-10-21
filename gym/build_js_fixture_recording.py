"""Create a fully offline HAR/DOM fixture from first-party reviewed demo assets.

This builder cannot fetch remote URLs or ingest third-party JavaScript.
Its only source files are the packaged synthetic gym/fixtures/js-demo files.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gym" / "fixtures" / "js-demo"
URL = "https://fixture.test/"


def build_fixture_recording(output):
    target = Path(output).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    assets = [
        ("index.html", "text/html; charset=utf-8"),
        ("style.css", "text/css; charset=utf-8"),
        ("app.js", "text/javascript; charset=utf-8"),
    ]
    for name, _ in assets:
        if not (SOURCE / name).is_file():
            raise FileNotFoundError("Missing packaged fixture source: " + name)

    html_data = (SOURCE / "index.html").read_bytes()
    (target / "step-000.html").write_bytes(html_data)
    entries = []
    digests = {}
    for name, mime in assets:
        body = (SOURCE / name).read_bytes()
        digests[name] = hashlib.sha256(body).hexdigest()
        href = URL if name == "index.html" else URL + name
        entries.append({
            "request": {"method": "GET", "url": href},
            "response": {"status": 200, "content": {
                "mimeType": mime,
                "text": base64.b64encode(body).decode("ascii"),
                "encoding": "base64",
            }},
        })
    (target / "trace.har").write_text(
        json.dumps({"log": {"version": "1.2", "entries": entries}},
                   indent=2), encoding="utf-8"
    )
    (target / "bundle.json").write_text(
        json.dumps({
            "startUrl": URL,
            "steps": [{"url": URL, "html": "step-000.html", "reason": "initial"}],
            "transitions": [],
            "synthetic_fixture": True,
            "fixture_id": "js-demo-v1",
            "reviewed_script_sha256": digests["app.js"],
        }, indent=2), encoding="utf-8"
    )
    return target


def main():
    parser = argparse.ArgumentParser(
        description="Build trusted synthetic JS recording, without any network access")
    parser.add_argument("--output", default="recordings/js-demo-trusted",
                        help="Recording output directory")
    args = parser.parse_args()
    result = build_fixture_recording(args.output)
    print(f"Created synthetic original-JS recording: {result}")
    print("Run: start-har-mock-windows.bat \"" + str(result)
          + "\" --trusted-fixture-js")
    print("This mode is only for packaged fixture.test; external captures remain inert.")


if __name__ == "__main__":
    main()
