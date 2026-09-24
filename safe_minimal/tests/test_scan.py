import unittest

import scan


class ScanTests(unittest.TestCase):
    def test_extracts_card_id_from_pkpass_path(self) -> None:
        line = (
            "CoreFoundation(CoreFoundation): resource lookup "
            "/var/mobile/Library/Passes/Cards/M6nDwZrkYbFlsodLgCbvyFZQ1cc=.pkpass"
        )
        self.assertEqual(
            scan.extract_card_ids(line),
            ["M6nDwZrkYbFlsodLgCbvyFZQ1cc="],
        )

    def test_ignores_uuid_identifiers(self) -> None:
        line = (
            "passd(PassKit): app<com.apple.PassbookUIService("
            "CB51386F-34C9-4FAC-871D-5F12E69A2141)>, running-active-Visible"
        )
        self.assertEqual(scan.extract_card_ids(line), [])

    def test_extracts_cache_suffix(self) -> None:
        line = (
            "passd(PassKit): opened /Passes/Cards/AbCdEfGhIjKlMnOpQrStUvWxYz1=.cache"
        )
        self.assertEqual(
            scan.extract_card_ids(line),
            ["AbCdEfGhIjKlMnOpQrStUvWxYz1="],
        )

    def test_invalid_udid_exits_before_device_access(self) -> None:
        self.assertEqual(scan.main(["../bad-udid"]), 2)


if __name__ == "__main__":
    unittest.main()
