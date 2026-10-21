"""Export captured JavaScript *only as inert local files* for Chrome DevTools.

These files appear in DevTools Sources > Workspace after the user explicitly
adds the output folder. They are NEVER injected into page HTML, registered
as active scripts, or made available as executable replay assets.

No external network requests and no JS execution are performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from capture_replay import CaptureReplay

OUTPUT_FOLDER = "_devtools_js"
MANIFEST = "recorded-js-manifest.json"
README = "READ_ME_FIRST.txt"


def clean_filename(name, digest):
    """Turn an untrusted HAR path basename into one stable local filename."""
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid SHA-256 digest")
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(name).stem)[:55].strip("_")
    if not stem:
        stem = "source"
    suffix = ".mjs" if str(name).lower().endswith(".mjs") else ".js"
    return "archived_" + stem + "_" + digest + suffix


def export_for_devtools(recording):
    """Copy only captured HAR JS bytes to an inert DevTools Workspace folder."""
    replay = CaptureReplay(recording)
    target = replay.directory / OUTPUT_FOLDER
    if target.is_symlink():
        raise ValueError("Refusing symlinked DevTools export directory")
    target.mkdir(exist_ok=True)
    if not target.is_dir():
        raise ValueError("DevTools export path is not a directory")

    manifest = {
        "mode": "devtools_workspace_read_only_archive",
        "source": "recorded_har",
        "captured_js_executed_by_replay": False,
        "saved_count": 0,
        "skipped_due_to_limits": replay.script_sources_skipped,
        "scripts": [],
    }
    for item in replay.script_index:
        digest = item["id"]
        raw = replay.script_sources[digest]
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Captured source hash mismatch")
        filename = clean_filename(item["name"], digest)
        out = target / filename
        if out.is_symlink():
            raise ValueError("Refusing symlinked JavaScript export file")
        if out.exists() and not out.is_file():
            raise ValueError("Export target is not a regular file")
        # Never derive a filesystem path from an original URL.
        out.write_bytes(raw)
        manifest["scripts"].append({
            "file": filename,
            "original_path": item.get("path", ""),
            "origin": item["origin"],
            "sha256": digest,
            "bytes": len(raw),
            "executed": False,
        })
    manifest["saved_count"] = len(manifest["scripts"])
    index_path = target / MANIFEST
    readme_path = target / README
    if index_path.is_symlink() or readme_path.is_symlink():
        raise ValueError("Refusing symlinked export metadata file")
    index_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    readme_path.write_text(
        "RECORDED JAVASCRIPT: ARCHIVED SOURCE ONLY, NOT EXECUTED.\n\n"
        "Chrome DevTools: F12 -> Sources -> Workspace -> Add folder; "
        "select this directory and grant local-folder access.\n"
        "Open archived_*.js or archived_*.mjs in the Workspace tree.\n"
        "These are verbatim response bodies captured in HAR (subject to the "
        "recorder's source limits), not the scripts running on the Mock page.\n"
        "Do not use Run Snippet or paste archived code into Console.\n"
        "The normal Sources > Page tree still shows only actual loaded code "
        "(such as sim.js).\n"
        "See recorded-js-manifest.json for original source path (without URL "
        "query strings), exact SHA-256 and capture origin.\n"
        "Local source files may contain sensitive embedded material. Keep "
        "the output private and do not commit it to Git.\n",
        encoding="utf-8",
    )
    return target, manifest


def main():
    parser = argparse.ArgumentParser(
        description="Export recorded JS for DevTools Workspace without running it")
    parser.add_argument("--recording", required=True,
                        help="Directory containing trace.har and bundle.json")
    args = parser.parse_args()
    path, manifest = export_for_devtools(args.recording)
    print("Exported", manifest["saved_count"], "recorded JavaScript files.")
    print("Skipped due to capture limits:", manifest["skipped_due_to_limits"])
    print("Workspace folder:", path)
    print("Chrome: F12 > Sources > Workspace > Add folder > choose folder above.")
    print("This does not place archived JS in Sources > Page or execute it.")


if __name__ == "__main__":
    main()
