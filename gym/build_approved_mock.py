"""Build an offline, per-site JavaScript mock from *reviewed first-party* assets.

This tool intentionally does not accept URLs, HAR files, imported recordings,
or arbitrary source directories. It packages only pre-approved repository fixtures.
Source code is preserved byte-for-byte without any common sim.js injection.
"""
import argparse
import json
from pathlib import Path

from gym.functional_sites import FunctionalSite, ROOT, SITES

GENERATED = ROOT / "generated-functional"
MANIFEST = "mock-manifest.json"
SCHEMA = "approved-functional-mock-v1"


def output_path(site, destination=None):
    if site not in SITES:
        raise ValueError("Unknown reviewed site")
    target = Path(destination) if destination is not None else GENERATED / site
    target = target.expanduser().resolve()
    base = GENERATED.resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("Output must be inside generated-functional/<site>")
    if target != (base / site):
        raise ValueError("Use the dedicated output path for this approved site")
    return target


def build_approved_mock(site, destination=None):
    """Copy only allowlisted original bytes and emit an auditable manifest."""
    approved = FunctionalSite(site)
    target = output_path(site, destination)
    target.mkdir(parents=True, exist_ok=True)
    file_map = SITES[site]["files"]
    for url_path, filename in file_map.items():
        raw, _ = approved.assets[url_path]
        dest = target / filename
        if dest.is_symlink() or not dest.resolve().is_relative_to(target):
            raise ValueError("Generated output must not contain symlinks")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)

    manifest = {
        "schema": SCHEMA,
        "site": site,
        "origin": approved.url,
        "api": SITES[site]["api"],
        "static_routes": dict(file_map),
        "sha256": dict(approved.hashes),
        "original_js_executed": True,
        "external_upstream_allowed": False,
        "source_kind": "reviewed_first_party_fixture",
    }
    mf = target / MANIFEST
    if mf.is_symlink():
        raise ValueError("Generated manifest must not be a symlink")
    mf.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


def load_approved_mock(site, destination=None):
    """Load a generated mock only if every byte matches reviewed source files."""
    target = output_path(site, destination)
    base = FunctionalSite(site)
    manifest_file = target / MANIFEST
    if manifest_file.is_symlink() or manifest_file.stat().st_size > 16_384:
        raise ValueError("Generated manifest is untrusted")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    required = {
        "schema": SCHEMA, "site": site, "origin": base.url,
        "api": SITES[site]["api"], "static_routes": SITES[site]["files"],
        "sha256": base.hashes, "original_js_executed": True,
        "external_upstream_allowed": False,
        "source_kind": "reviewed_first_party_fixture",
    }
    if manifest != required:
        raise ValueError("Generated mock manifest does not match reviewed source")

    verified = {}
    for path, filename in SITES[site]["files"].items():
        f = target / filename
        if f.is_symlink() or not f.resolve(strict=True).is_relative_to(target):
            raise ValueError("Compiled asset escapes approved output")
        raw = f.read_bytes()
        if raw != base.assets[path][0]:
            raise ValueError("Generated asset differs from approved site: " + path)
        verified[path] = (raw, base.assets[path][1])
    base.assets = verified
    base.root = target
    return base


def main():
    parser = argparse.ArgumentParser(
        description="Build approved functional mock without generic sim.js")
    parser.add_argument("--site", required=True, choices=sorted(SITES))
    args = parser.parse_args()
    folder = build_approved_mock(args.site)
    print("Generated:", folder)
    print("Original reviewed JavaScript preserved; no generic sim.js")
    print("Run: start-functional-gym-windows.bat " + args.site +
          " --generated")
    print("No third-party scripts, HAR imports or original authentication.")


if __name__ == "__main__":
    main()
