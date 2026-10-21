"""Validate inert metadata-only receipt events from the approved JS demo.

Only a fixed, non-sensitive event name and an integer sequence are accepted.
This module has no network dependencies and never retains request bodies.
"""
import json


class FixtureReceiptError(ValueError):
    """Malformed or out-of-scope local test event."""


def parse_fixture_receipt(body):
    if not isinstance(body, bytes) or len(body) > 128 or len(body) < 2:
        raise FixtureReceiptError("Invalid payload length")
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise FixtureReceiptError("Invalid JSON") from exc
    if not isinstance(data, dict) or set(data) != {"event", "sequence"}:
        raise FixtureReceiptError("Only allowlisted synthetic metadata is accepted")
    if data["event"] != "basket_add":
        raise FixtureReceiptError("Unknown fixture event")
    if type(data["sequence"]) is not int or not 1 <= data["sequence"] <= 1000:
        raise FixtureReceiptError("Invalid fixture counter")
    return {"event": "basket_add", "sequence": data["sequence"]}
