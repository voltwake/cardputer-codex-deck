# Development guide

## Prerequisites

- macOS 13 or newer on Apple Silicon (the current packaged App target).
- Xcode and Command Line Tools; `swift --version` must work.
- Python 3.10 or newer.
- PlatformIO Core.
- Internet access for the pinned Sparkle archive and Python/PlatformIO inputs.

Check the machine without changing it:

```sh
./scripts/doctor.sh
```

## Bootstrap

```sh
./scripts/bootstrap.sh
```

This creates the isolated `bridge/agent/.venv` for the packaged Agent and
`tools/.venv` for PlatformIO. Keeping build tools out of the Agent environment
prevents unrelated packages from being bundled into the App. Generated version
files are checked but never silently rewritten during a build.

## Tests and builds

```sh
./scripts/test.sh
./scripts/build.sh
```

The test script runs generated-version validation, Python tests, Swift tests,
and a firmware build when PlatformIO is available. The build script packages
the signed App, embedded Agent, Sparkle framework, and microphone driver under
`bridge/macos/dist/CardBridge.app`.

The lower-level commands remain available:

```sh
PYTHONPATH=bridge/agent:. bridge/agent/.venv/bin/python -m unittest discover -s bridge/agent/tests -v
swift test --package-path bridge/macos
pio run -d firmware/m5stack-cardputer-adv
bridge/macos/scripts/build_app.sh
python3 tools/validate_release.py --app bridge/macos/dist/CardBridge.app
```

## Multi-device and protocol verification

The dependency-free Python suite covers legacy v1, the shipped M5 v2
capability profile, vendor-neutral devices, concurrent pairing, same-ID
replacement, per-device keys/acknowledgements, independent UDP jitter buffers,
the single audio lease, topic capability gates, Token deltas/rates, privacy,
and the 4096-byte device line limit:

```sh
PYTHONPATH=bridge/agent:. bridge/agent/.venv/bin/python -m unittest discover -s bridge/agent/tests -v
swift test --package-path bridge/macos
```

`fake_device.py` can represent a new device without changing the Agent. Its
default token cache is per device ID, so two instances can run concurrently:

```sh
PYTHONPATH=bridge/agent:. bridge/agent/.venv/bin/python bridge/agent/fake_device.py \
  --id waveshare-a --vendor waveshare \
  --model esp32-s3-touch-amoled-1.75c --name "Desk Orb A"
PYTHONPATH=bridge/agent:. bridge/agent/.venv/bin/python bridge/agent/fake_device.py \
  --id waveshare-b --vendor waveshare \
  --model esp32-s3-touch-amoled-1.75c --name "Desk Orb B"
```

To exercise the standard topic profile, pass capabilities explicitly (repeat
`--capability` for each one). Do not use real pairing tokens in shared logs or
test artifacts. The simulator and test fixtures keep any local cache in the
ignored development workspace only.

The unmodified M5 binary is represented by the generated
`FIRMWARE_CAPABILITIES` profile. It should continue using `agent_status`,
`agent_list`, keyboard, heartbeat, and automatic audio lease acquisition; it
does not need a firmware update or any new command for this Goal.

## Generated files

`version.json` is authoritative. After changing it:

```sh
python3 tools/generate_versions.py
python3 tools/generate_versions.py --check
```

Do not hand-edit `bridge/agent/cardbridge/_generated_version.py`,
`firmware/m5stack-cardputer-adv/src/generated_version.h`,
`bridge/macos/Shared/GeneratedVersion.swift`, or
`release/compatibility.json`.

## Release build

The release gate is:

```sh
CODE_SIGN_IDENTITY="Developer ID Application: …" \
  REQUIRE_NOTARIZATION=1 \
  NOTARY_PROFILE=cardbridge-notary \
  bridge/macos/scripts/release.sh
```

Public distribution requires a Developer ID certificate, notarization
credentials, a Sparkle signing key, a tag matching `version.json`, and a
review of `THIRD_PARTY_NOTICES.md` and
`firmware/m5stack-cardputer-adv/assets/ASSET_SOURCES.md`.
