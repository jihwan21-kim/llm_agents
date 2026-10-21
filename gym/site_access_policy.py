"""Fail-closed capabilities for local site recordings and reviewed JS fixtures.

JSON registration is not owner consent and does not grant permission to run
arbitrary third-party JS. Only checked-in synthetic .test fixtures can enter
native_js mode, regardless of claims in an edited policy file.
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

POLICY = Path(__file__).with_name("site_access_policy.json")
MODES = frozenset(("capture", "static_replay", "source_inspection", "native_js"))
HOST_PATTERN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+$")


class SitePolicyError(ValueError):
    """Site or requested replay mode is not allowed by the local policy."""


def load_policy():
    data = json.loads(POLICY.read_text(encoding="utf-8"))
    if data.get("schema") != "site-access-policy-v1":
        raise SitePolicyError("Unsupported site-policy schema")
    entries = data.get("sites")
    if not isinstance(entries, list):
        raise SitePolicyError("Site-policy entries missing")
    by_host = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SitePolicyError("Invalid site-policy entry")
        host = entry.get("host")
        modes = entry.get("allowed_modes")
        if (not isinstance(host, str) or host != host.lower()
                or not HOST_PATTERN.fullmatch(host) or host in by_host):
            raise SitePolicyError("Invalid or duplicate exact host in policy")
        if (not isinstance(modes, list) or not modes or
                any(mode not in MODES for mode in modes) or
                len(modes) != len(set(modes))):
            raise SitePolicyError("Invalid allowed modes")
        if type(entry.get("owner_permission_verified")) is not bool:
            raise SitePolicyError("Missing explicit verified-permission indicator")
        if entry.get("source_kind") not in {
            "external_third_party", "reviewed_synthetic_fixture"
        }:
            raise SitePolicyError("Invalid source kind")
        by_host[host] = entry
    return by_host


def normalize_host(url_or_host):
    """Require an exact host; no substring, suffix or wildcard matching."""
    if not isinstance(url_or_host, str):
        raise SitePolicyError("Invalid site")
    if "://" not in url_or_host:
        if not HOST_PATTERN.fullmatch(url_or_host):
            raise SitePolicyError("Enter an exact hostname or valid URL")
        return url_or_host
    parts = urlsplit(url_or_host)
    if (parts.scheme not in {"http", "https"} or not parts.hostname or
            parts.username is not None or parts.password is not None):
        raise SitePolicyError("Unsupported or credential-bearing URL")
    try:
        port = parts.port
    except ValueError as exc:
        raise SitePolicyError("Invalid port") from exc
    if port not in {None, 80, 443}:
        raise SitePolicyError("Only standard web ports are supported")
    host = parts.hostname.lower()
    if not HOST_PATTERN.fullmatch(host):
        raise SitePolicyError("Invalid hostname")
    return host


def require_site_mode(url_or_host, mode, *, fixture_id=None):
    """Return approved entry or raise; original third-party JS always denied."""
    if mode not in MODES:
        raise SitePolicyError("Unknown mode")
    host = normalize_host(url_or_host)
    entry = load_policy().get(host)
    if entry is None:
        raise SitePolicyError("Hostname not registered: " + host)
    if mode not in entry["allowed_modes"]:
        raise SitePolicyError("Mode " + mode + " not permitted for " + host)

    if mode == "native_js":
        # Critically, editing JSON cannot turn Google (or another public
        # website) into a functional JS origin: only built-in first-party
        # synthetic fixtures may execute, backed by the reviewed SITES map.
        from gym.functional_sites import SITES
        if (not host.endswith(".test") or host == "mock.test"
                or entry["source_kind"] != "reviewed_synthetic_fixture"
                or entry["owner_permission_verified"] is not True
                or fixture_id not in SITES
                or entry.get("fixture_id") != fixture_id
                or SITES[fixture_id]["host"] != host):
            raise SitePolicyError("Native JS limited to reviewed in-repo .test fixtures")
    return entry


def main():
    parser = argparse.ArgumentParser(description="Check exact-host site capabilities")
    parser.add_argument("--url", required=True, help="URL or exact hostname")
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--fixture-id", help="Required for native_js")
    parser.add_argument("--recording", help="Optional recording bundle to check its startUrl")
    args = parser.parse_args()
    try:
        url = args.url
        if args.recording:
            saved = Path(args.recording).expanduser().resolve(strict=True)
            bundle = json.loads((saved / "bundle.json").read_text(encoding="utf-8"))
            start = bundle["startUrl"]
            if normalize_host(start) != normalize_host(args.url):
                raise SitePolicyError("Recording host differs from selected host")
            url = start
        entry = require_site_mode(url, args.mode, fixture_id=args.fixture_id)
    except (SitePolicyError, OSError, KeyError, ValueError) as exc:
        parser.exit(2, "DENIED: " + str(exc) + "\n")
    print("ALLOWED:", normalize_host(url), "for", args.mode)
    print("Owner permission verified:", entry["owner_permission_verified"])
    print("Source kind:", entry["source_kind"])
    if args.mode != "native_js":
        print("No captured original JavaScript will be executed.")


if __name__ == "__main__":
    main()
