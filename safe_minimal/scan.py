#!/usr/bin/env python3
"""Read-only Wallet card ID scanner.

Streams the attached iPhone log over USB and extracts card identifiers from
Passes/Cards paths. No files are written on the device.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOG_BRIDGE = ROOT / "bin" / "log_bridge"
UDID_PATTERN = re.compile(r"^[A-Fa-f0-9-]{8,64}$")
CARD_REGEXES = (
    re.compile(
        r"/(?:Cards|Passes/Cards)/([-A-Za-z0-9_+=]{20,44})"
        r"(?:\.pkpass|\.cache|\.pkcache|/|\s|\"|\'|\)|,|$)"
    ),
    re.compile(r"/([-A-Za-z0-9_+=]{20,44})\.(?:pkpass|cache|pkcache)"),
    re.compile(r"(?<![A-Za-z0-9+/_-])([A-Za-z0-9+/_-]{27}=)(?![A-Za-z0-9+/_-])"),
)
WALLET_HINTS = (
    "passd",
    "passbook",
    "passkit",
    "stockholm",
    "nanopassd",
    "wallet",
    "/cards/",
)
CONTEXT_HINTS = (
    "card",
    "pass",
    "payment",
    "pkpass",
    "uniqueid",
    "identifier",
    "face",
    "cache",
    "stockholm",
    "/cards/",
)


def normalize_card_id(value: str) -> str | None:
    candidate = value.strip().strip("'\"").rstrip(".").rstrip(",")
    if not candidate:
        return None
    if len(candidate) == 36 and "-" in candidate:
        return None
    return candidate


def extract_card_ids(line: str) -> list[str]:
    lower = line.lower()
    if not any(hint in lower for hint in WALLET_HINTS):
        return []
    if not any(hint in lower for hint in CONTEXT_HINTS):
        return []

    found: list[str] = []
    for pattern in CARD_REGEXES:
        for match in pattern.finditer(line):
            card_id = normalize_card_id(match.group(1))
            if card_id and card_id not in found:
                found.append(card_id)
    return found


def run_log_bridge(udid: str) -> subprocess.Popen[str]:
    if not LOG_BRIDGE.is_file():
        raise FileNotFoundError(f"log bridge not built: {LOG_BRIDGE}")
    return subprocess.Popen(
        [os.fspath(LOG_BRIDGE), udid],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        stdin=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
    )


def scan_cards(
    udid: str,
    *,
    timeout: float | None = None,
    interactive: bool = True,
) -> tuple[list[str], list[str]]:
    process = run_log_bridge(udid)
    found: list[str] = []
    messages: list[str] = []
    deadline = None if timeout is None else time.monotonic() + timeout

    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break

            wait = 0.2
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.monotonic()))

            readers: list = [process.stdout, process.stderr]
            if interactive:
                readers.append(sys.stdin)
            ready, _, _ = select.select(readers, [], [], wait)

            if interactive and sys.stdin in ready:
                sys.stdin.readline()
                break

            if process.stderr in ready:
                line = process.stderr.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                messages.append(line.rstrip())
                print(line, file=sys.stderr, end="")

            if process.stdout in ready:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                for card_id in extract_card_ids(line):
                    if card_id not in found:
                        found.append(card_id)
                        print(f"Detected card [{len(found)}]: {card_id}")

            if process.poll() is not None:
                break
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    return found, messages


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Wallet card IDs from the attached iPhone log stream."
    )
    parser.add_argument("udid", help="Target iPhone UDID")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Stop after this many seconds (default: wait for Enter)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print detected card IDs as JSON on stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not UDID_PATTERN.fullmatch(args.udid):
        print("Invalid UDID.", file=sys.stderr)
        return 2

    if not args.json:
        print()
        print("=" * 60)
        print("CARD ID SCAN (read-only)")
        print("=" * 60)
        print("1) Double-click the side button to open Wallet.")
        print("2) Authenticate with Face ID.")
        print("3) Tap each card you want to detect.")
        if args.timeout is None:
            print("Press Enter when finished.")
        else:
            print(f"Scanning for up to {args.timeout:.0f} seconds.")
        print("=" * 60)
        print()

    try:
        cards, _messages = scan_cards(
            args.udid,
            timeout=args.timeout,
            interactive=args.timeout is None,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        print("Run `make` in safe_minimal first.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(cards, indent=2))
    elif not cards:
        print("No card IDs detected.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
