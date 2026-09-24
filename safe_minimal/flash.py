#!/usr/bin/env python3
"""Local-only Wallet artwork writer.

This file is intentionally self-contained. It imports only Python's standard
library and invokes only locally built helpers plus macOS /usr/bin/sips.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import plistlib
import posixpath
import re
import secrets
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEVICE_BRIDGE = ROOT / "bin" / "device_bridge"
AIRTRAFFIC_BRIDGE = ROOT / "bin" / "airtraffic_bridge"
AIRLOCK_ROOT = "/var/mobile/Media/Airlock/Book"
SOURCE_PREFIX = "airlift-src-"
LINK_PREFIX = "airlift-link-"
RECOVERED_PREFIX = "airlift-recovered-"
ZIP_MODE_EXTRA_ID = 0x5A53
CARD_ID_PATTERN = re.compile(r"[-A-Za-z0-9_+=]{16,64}")
UDID_PATTERN = re.compile(r"[A-Fa-f0-9-]{8,64}")
CARD_ASSETS = (
    "cardBackgroundCombined@3x.png",
    "cardBackgroundCombined@2x.png",
)
CACHE_FILES = ("FrontFace", "PlaceHolder", "Preview")


def run_json(arguments: list[str], timeout: int = 120) -> dict:
    """Run one fixed local helper and return its last JSON object."""
    executable = Path(arguments[0])
    if executable not in (DEVICE_BRIDGE, AIRTRAFFIC_BRIDGE):
        raise ValueError("refusing to execute an unapproved program")
    completed = subprocess.run(
        arguments,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
    )
    result = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            result = candidate
            break
    if result is None:
        raise RuntimeError(
            f"{executable.name} returned no JSON (exit {completed.returncode})"
        )
    result["exitCode"] = completed.returncode
    return result


def operation_ok(result: dict) -> bool:
    return bool(
        result.get("exitCode") == 0
        and result.get("targetGatePassed")
        and result.get("operation", {}).get("ok")
    )


def device(command: str, udid: str, *arguments: str) -> dict:
    allowed = {
        "probe",
        "snapshot-books",
        "stage",
        "finish-write",
        "finish-moved-removal",
    }
    if command not in allowed:
        raise ValueError(f"unsupported device command: {command}")
    return run_json(
        [os.fspath(DEVICE_BRIDGE), command, udid, *arguments],
        timeout=120,
    )


def zip_entry(name: str, mode: int) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.compress_type = zipfile.ZIP_STORED
    entry.external_attr = (mode & 0xFFFF) << 16
    entry.extra = struct.pack("<HHH", ZIP_MODE_EXTRA_ID, 2, mode & 0xFFFF)
    return entry


def build_archive(target: str, payloads: tuple[tuple[str, bytes], ...]) -> bytes:
    """Create the fixed StreamingZip payload used for protected writes."""
    target_tail = target.lstrip("/")
    metadata = plistlib.dumps(
        {"Version": 2}, fmt=plistlib.FMT_BINARY, sort_keys=True
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        archive.writestr(zip_entry("META-INF/", stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            zip_entry(
                "META-INF/com.apple.ZipMetadata.plist",
                stat.S_IFREG | 0o600,
            ),
            metadata,
        )
        for directory in ("p0/", "p0/p1/", "p0/p1/p2/"):
            archive.writestr(zip_entry(directory, stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            zip_entry("p0/p1/p2/link", stat.S_IFLNK | 0o777),
            f"../../../{target_tail}".encode("utf-8"),
        )
        cursor = ""
        for component in target_tail.split("/"):
            if component:
                cursor += component + "/"
                archive.writestr(
                    zip_entry(cursor, stat.S_IFDIR | 0o755), b""
                )
        for index, (_leaf, payload) in enumerate(payloads):
            archive.writestr(
                zip_entry(f"payload_{index}", stat.S_IFREG | 0o600),
                payload,
            )
        # The bridge checks for payload or payload_0.
        archive.writestr(
            zip_entry("payload", stat.S_IFREG | 0o600),
            payloads[0][1],
        )
    return output.getvalue()


def build_books(identifiers: list[str]) -> bytes:
    rows = [
        {"Persistent ID": identifier, "Item ID": str(index), "DSID": "1"}
        for index, identifier in enumerate(identifiers, 1)
    ]
    return plistlib.dumps(
        {"Books": rows}, fmt=plistlib.FMT_BINARY, sort_keys=True
    )


def generated_names() -> tuple[str, str, str]:
    token = secrets.token_hex(10)
    return (
        SOURCE_PREFIX + token,
        LINK_PREFIX + token,
        RECOVERED_PREFIX + token,
    )


def write_assets(
    udid: str,
    target: str,
    payloads: tuple[tuple[str, bytes], ...],
    retries: int = 3,
) -> bool:
    """Write all pass assets atomically, restoring Books state afterward."""
    if not payloads or any("/" in leaf or not leaf for leaf, _ in payloads):
        raise ValueError("asset names must be non-empty leaf names")

    for attempt in range(retries):
        source, link, recovered = generated_names()
        link_identifier = f"../../{source}/p0/p1/p2/link"
        identifiers = [link_identifier]
        destinations = [link]
        for index, (leaf, _payload) in enumerate(payloads):
            identifiers.append(f"../../{source}/payload_{index}")
            destinations.append(posixpath.join(link, leaf))

        try:
            with tempfile.TemporaryDirectory(prefix="safe-wallet-write-") as tmp:
                work = Path(tmp)
                archive = work / "payload.zip"
                books = work / "Books.plist"
                snapshot = work / "snapshot"
                snapshot.mkdir()
                archive.write_bytes(build_archive(target, payloads))
                books.write_bytes(build_books(identifiers))

                if not operation_ok(
                    device("snapshot-books", udid, os.fspath(snapshot))
                ):
                    raise RuntimeError("could not snapshot Books state")

                staged = device(
                    "stage",
                    udid,
                    source,
                    link,
                    recovered,
                    os.fspath(archive),
                    os.fspath(books),
                    os.fspath(snapshot),
                )
                if not operation_ok(staged):
                    device(
                        "finish-write",
                        udid,
                        source,
                        link,
                        recovered,
                        os.fspath(snapshot),
                    )
                    raise RuntimeError("could not stage local assets")

                transfer_arguments = [os.fspath(AIRTRAFFIC_BRIDGE), udid]
                for identifier, destination in zip(identifiers, destinations):
                    transfer_arguments.extend((identifier, destination))
                transferred = run_json(transfer_arguments, timeout=180)
                finished = device(
                    "finish-write",
                    udid,
                    source,
                    link,
                    recovered,
                    os.fspath(snapshot),
                )
                if (
                    transferred.get("exitCode") == 0
                    and transferred.get("ok")
                    and operation_ok(finished)
                ):
                    return True
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        if attempt + 1 < retries:
            time.sleep(0.5 * (attempt + 1))
    return False


def remove_cache_files(
    udid: str,
    target: str,
    leaves: tuple[str, ...] = CACHE_FILES,
    retries: int = 3,
) -> bool:
    """Move rendered faces out of the protected cache and clean staging."""
    if not leaves or any(not leaf or "/" in leaf for leaf in leaves):
        raise ValueError("cache names must be non-empty leaf names")

    for attempt in range(retries):
        source, link, recovered = generated_names()
        link_identifier = f"../../{source}/p0/p1/p2/link"
        protected = [f"../../{link}/{leaf}" for leaf in leaves]
        removed = [
            f"{source}/removed-{index}" for index in range(len(leaves))
        ]
        try:
            with tempfile.TemporaryDirectory(prefix="safe-wallet-remove-") as tmp:
                work = Path(tmp)
                archive = work / "payload.zip"
                books = work / "Books.plist"
                snapshot = work / "snapshot"
                snapshot.mkdir()
                archive.write_bytes(
                    build_archive(target, (("placeholder", b"safe"),))
                )
                books.write_bytes(
                    build_books([link_identifier, *protected])
                )
                if not operation_ok(
                    device("snapshot-books", udid, os.fspath(snapshot))
                ):
                    raise RuntimeError("could not snapshot Books state")
                if not operation_ok(
                    device(
                        "stage",
                        udid,
                        source,
                        link,
                        recovered,
                        os.fspath(archive),
                        os.fspath(books),
                        os.fspath(snapshot),
                    )
                ):
                    device(
                        "finish-write",
                        udid,
                        source,
                        link,
                        recovered,
                        os.fspath(snapshot),
                    )
                    raise RuntimeError("could not stage cache removal")

                transfer = [os.fspath(AIRTRAFFIC_BRIDGE), udid]
                for identifier, destination in zip(
                    [link_identifier, *protected], [link, *removed]
                ):
                    transfer.extend((identifier, destination))
                moved = run_json(transfer, timeout=180)
                finished = device(
                    "finish-moved-removal",
                    udid,
                    source,
                    link,
                    recovered,
                    os.fspath(snapshot),
                    str(len(leaves)),
                )
                if (
                    moved.get("exitCode") == 0
                    and moved.get("ok")
                    and operation_ok(finished)
                ):
                    return True
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        if attempt + 1 < retries:
            time.sleep(0.5 * (attempt + 1))
    return False


def prepare_assets(image: Path) -> tuple[tuple[str, bytes], ...]:
    if not image.is_file():
        raise FileNotFoundError(f"image not found: {image}")
    with tempfile.TemporaryDirectory(prefix="safe-wallet-image-") as tmp:
        png = Path(tmp) / "card.png"
        pdf = Path(tmp) / "card.pdf"
        subprocess.run(
            [
                "/usr/bin/sips",
                "-s",
                "format",
                "png",
                "-z",
                "969",
                "1536",
                os.fspath(image),
                "--out",
                os.fspath(png),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
        )
        subprocess.run(
            [
                "/usr/bin/sips",
                "-s",
                "format",
                "pdf",
                os.fspath(png),
                "--out",
                os.fspath(pdf),
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
        )
        png_data = png.read_bytes()
        pdf_data = pdf.read_bytes()
    return (
        *((name, png_data) for name in CARD_ASSETS),
        ("cardBackgroundCombined.pdf", pdf_data),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locally write one image to one known Wallet card."
    )
    parser.add_argument("udid")
    parser.add_argument("card_id")
    parser.add_argument("image", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not UDID_PATTERN.fullmatch(args.udid):
        print("error: invalid UDID", file=sys.stderr)
        return 2
    if not CARD_ID_PATTERN.fullmatch(args.card_id):
        print("error: invalid card ID", file=sys.stderr)
        return 2
    for helper in (DEVICE_BRIDGE, AIRTRAFFIC_BRIDGE):
        if not helper.is_file() or not os.access(helper, os.X_OK):
            print(f"error: {helper} is missing; run `make`", file=sys.stderr)
            return 2

    try:
        if not operation_ok(device("probe", args.udid)):
            print("error: device compatibility check failed", file=sys.stderr)
            return 1
        assets = prepare_assets(args.image.expanduser().resolve())
        pass_directory = (
            f"/var/mobile/Library/Passes/Cards/{args.card_id}.pkpass"
        )
        if not write_assets(args.udid, pass_directory, assets):
            print("error: artwork write failed", file=sys.stderr)
            return 1
        for extension in (".cache", ".pkcache"):
            cache = (
                f"/var/mobile/Library/Passes/Cards/"
                f"{args.card_id}{extension}"
            )
            if not remove_cache_files(args.udid, cache):
                print(f"error: could not clear {extension}", file=sys.stderr)
                return 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print("Done. Force-close Wallet on the iPhone, then reopen it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
