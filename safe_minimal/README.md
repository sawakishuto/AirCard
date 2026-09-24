# Safe minimal Wallet writer

This directory is self-contained. It provides a source-built, command-line-only
version for one known card ID and one local image.

## Security boundary

- `flash.py` uses only Python's standard library.
- `flash.py` child processes are restricted to the two write bridges and
  `/usr/bin/sips`. `scan.py` invokes only the read-only `log_bridge`.
- There are no HTTP clients, URLs, telemetry, update checks, shell execution,
  dynamic library loading, or arbitrary subprocess paths.
- The native bridges communicate with the iPhone through Apple's local
  MobileDevice and AirTrafficHost frameworks. This device traffic is required
  for the operation; it is not internet traffic.
- The safe build asks MobileDevice for direct USB connections only; Wi-Fi
  paired-device discovery is disabled.
- The build runs a source scan and then compiles the bridges locally. No
  downloaded or prebuilt executable is used.

`device_bridge` compiles from `Sources/device_bridge.m`. It accepts only
`probe`, `snapshot-books`,
`stage`, `finish-write`, and `finish-moved-removal`. Its Books snapshot and
restoration logic remains because an abbreviated cleanup path could leave the
iPhone's sync state damaged.

`log_bridge` compiles from `Sources/log_bridge.m`. It streams the unified
device log over USB through `com.apple.os_trace_relay` and performs no writes.

## Build and run

```sh
cd safe_minimal
make
./scan.py <UDID>
./flash.py <UDID> <CARD_ID> /absolute/path/to/image.png
```

After a successful flash, force-close Wallet on the iPhone and reopen it.

## What leaves the Mac

Only the following data is sent, and only to the attached iPhone selected by
UDID:

1. The converted card artwork.
2. Temporary Books sync metadata containing generated random staging names.
3. AirTraffic messages containing those same staging names.

The program does not send the image, card ID, UDID, logs, or usage information
to an internet service.

- Specification: [`../docs/safe-minimal-spec.md`](../docs/safe-minimal-spec.md)
- Runbook: [`../docs/safe-minimal-runbook.md`](../docs/safe-minimal-runbook.md)
