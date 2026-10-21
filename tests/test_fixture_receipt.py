"""Unit tests for strict synthetic-only local receipt payloads."""
import json
import unittest

from gym.fixture_receipt import parse_fixture_receipt, FixtureReceiptError


class FixtureReceiptTests(unittest.TestCase):
    def test_valid_synthetic_metadata_only(self):
        result = parse_fixture_receipt(b'{"event":"basket_add","sequence":7}')
        self.assertEqual(result, {"event": "basket_add", "sequence": 7})

    def test_rejects_unexpected_fields_and_payloads(self):
        invalid = [
            {"event": "basket_add", "sequence": 1, "extra": "unapproved"},
            {"event": "basket_add", "sequence": True},
            {"event": "basket_add", "sequence": 0},
            {"event": "basket_add", "sequence": 1001},
            {"event": "basket_add", "sequence": "1"},
            {"event": "login", "sequence": 1},
            {"sequence": 1},
            {"event": "basket_add"},
            [],
            "not a JSON object",
        ]
        for item in invalid:
            with self.subTest(item=item):
                with self.assertRaises(FixtureReceiptError):
                    parse_fixture_receipt(json.dumps(item).encode())

    def test_rejects_large_invalid_or_non_utf8(self):
        with self.assertRaises(FixtureReceiptError):
            parse_fixture_receipt(b"x" * 129)
        with self.assertRaises(FixtureReceiptError):
            parse_fixture_receipt(b"{not-json")
        with self.assertRaises(FixtureReceiptError):
            parse_fixture_receipt(b"\xff")
        with self.assertRaises(FixtureReceiptError):
            parse_fixture_receipt("not-bytes")


if __name__ == "__main__":
    unittest.main()
