# Safe Minimal Wallet Writer

This repository contains a self-contained minimal tool to apply one local image
to one known Apple Wallet card on a USB-connected iPhone. All runtime source
lives under `safe_minimal/`.

There is no GUI, telemetry, update checker, HTTP client, or prebuilt
executable. Card ID discovery is read-only via `scan.py`.

## Build

```sh
cd safe_minimal
make
```

The build:

1. scans the source for internet clients and dynamic execution,
2. compiles the native bridges locally,
3. ad-hoc signs the resulting binaries.

## Run

```sh
cd safe_minimal
./scan.py <UDID>
./flash.py <UDID> <CARD_ID> /absolute/path/to/image.png
```

After a successful flash, force-close Wallet on the iPhone and reopen it.

## Communication

The program invokes only:

- locally built `device_bridge` and `airtraffic_bridge` (flash only),
- locally built `log_bridge` (scan only),
- macOS `/usr/bin/sips` (flash only).

The native bridges communicate with the selected iPhone through Apple's
MobileDevice and AirTrafficHost frameworks. The device bridge accepts direct
USB connections only. No application code sends data to an internet service.

See `safe_minimal/README.md` for the security boundary,
[`docs/safe-minimal-spec.md`](docs/safe-minimal-spec.md) for the specification, and
[`docs/safe-minimal-runbook.md`](docs/safe-minimal-runbook.md) for step-by-step execution.

## Test

```sh
cd safe_minimal
make test
```
