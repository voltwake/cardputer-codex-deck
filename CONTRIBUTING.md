# Contributing to Codex Deck

Codex Deck combines ESP32-S3 firmware, a Python bridge, a Swift macOS menu bar
app, and a GPLv3-derived audio driver. Read the current guides in
[`docs/README.md`](docs/README.md) before changing code.

## Before opening a pull request

```sh
./scripts/doctor.sh
./scripts/test.sh
git diff --check
```

If you change `version.json`, regenerate and verify all generated constants:

```sh
python3 tools/generate_versions.py
python3 tools/generate_versions.py --check
```

Keep M5 firmware dependencies pinned in
`firmware/m5stack-cardputer-adv/platformio.ini`. Do not add PSRAM
configuration: Cardputer ADV uses an ESP32-S3 without PSRAM.

## Change boundaries

- Do not hand-edit generated files.
- Do not commit pairing tokens, Wi-Fi passwords, Keychain exports, API keys,
  Core Audio recordings, or local Codex transcripts.
- Keep protocol changes backward compatible or update `version.json`,
  `docs/PROTOCOL.md`, compatibility tests, and release notes together.
- Preserve the owner-only local control socket and token redaction behavior.
- Driver changes must retain the GPLv3 notices and document the upstream base
  and CardBridge-specific modifications.

Pull requests should explain user-visible behavior, permissions affected,
upgrade/migration behavior, and how the change was tested. Hardware-only
validation should include the board revision, firmware build, and a concise
serial or health-check result.
