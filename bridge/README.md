# Codex Deck desktop bridge

This directory contains the device-neutral desktop side of Codex Deck:

- `agent/` — the Python bridge service and its tests;
- `macos/` — the SwiftUI menu bar App and packaging scripts;
- `driver/` — the Core Audio microphone driver.

The public product name is Codex Deck. The `CardBridge` application, package,
socket, audio-device, and bundle identifiers remain compatibility names for
the 1.x line.

Use the stable commands at the repository root for setup, tests, builds,
installation, and health checks.
