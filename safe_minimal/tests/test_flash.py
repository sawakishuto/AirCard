import io
import unittest
import zipfile
from pathlib import Path

import flash


class SafeMinimalTests(unittest.TestCase):
    def test_rejects_unapproved_executable(self) -> None:
        with self.assertRaises(ValueError):
            flash.run_json(["/usr/bin/curl", "https://example.invalid"])

    def test_archive_contains_only_expected_payload_shape(self) -> None:
        data = flash.build_archive(
            "/var/mobile/Library/Passes/Cards/example.pkpass",
            (("one.png", b"one"), ("two.png", b"two")),
        )
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            self.assertIn("p0/p1/p2/link", names)
            self.assertIn("payload_0", names)
            self.assertIn("payload_1", names)
            self.assertEqual(archive.read("payload_0"), b"one")
            self.assertEqual(archive.read("payload_1"), b"two")

    def test_invalid_identifiers_stop_before_device_access(self) -> None:
        self.assertEqual(flash.main(["bad", "valid-card-id-1234", "x"]), 2)
        self.assertEqual(
            flash.main(["00008120-001A1D0A1EE9A01E", "../unsafe", "x"]),
            2,
        )

    def test_minimal_python_has_no_internet_client_imports(self) -> None:
        source = Path(flash.__file__).read_text("utf-8").lower()
        for forbidden in (
            "import socket",
            "import urllib",
            "import requests",
            "urlsession",
            "http://",
            "https://",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
