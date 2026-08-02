# M5Stack Cardputer ADV firmware

This is the M5Stack Cardputer ADV implementation of the Codex Deck device
protocol.

From the repository root:

```sh
tools/.venv/bin/pio run -d firmware/m5stack-cardputer-adv
tools/.venv/bin/pio run -d firmware/m5stack-cardputer-adv -t upload
```

Let PlatformIO auto-detect `/dev/cu.usbmodem*` unless a specific verified port
is required. Flashing hardware remains a separate explicit operation.

The capability profile is generated from root `version.json`. Do not hand-edit
`src/generated_version.h`.
