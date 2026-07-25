# Troubleshooting

## Start with diagnostics

```sh
./scripts/doctor.sh
./scripts/healthcheck.sh --json
```

Redact tokens, Wi-Fi passwords, Codex content, and personal paths before
sharing output.

## App does not start

- Confirm `/Applications/CardBridge.app` exists and its version matches
  `version.json`.
- Run `codesign --verify --deep --strict /Applications/CardBridge.app`.
- Re-run `./scripts/install.sh` after quitting the old menu bar process.

## Keyboard forwarding does not work

Open **System Settings → Privacy & Security → Accessibility** and allow
CardBridge. Restart the App after changing the grant. Audio and discovery can
continue to work without this permission, but Quartz key injection cannot.

## Microphone is missing

Open CardBridge Settings → Audio and approve the administrator installation.
Then check Audio MIDI Setup for both `CardBridge Microphone` and
`CardBridge Microphone Feed`. Restarting `coreaudiod` may be required after a
manual driver change. BlackHole 2ch is a supported fallback.

## Microphone stops while keyboard forwarding still works

Current firmware and Agent builds recover this path automatically: the device
restarts I2S and its UDP socket when authenticated heartbeat counters stop
advancing, while the Agent recreates an inactive Core Audio stream. Install the
matching current firmware and App before diagnosing an older build.

If audio still does not recover, open the App menu and check that the M5 packet
count continues to increase while Remote mode is on. A fixed count points to
the device/Wi-Fi path; an increasing count with an unhealthy audio indicator
points to the local Core Audio feed or driver.

BtnA mode changes intentionally stop capture and discard buffered samples. The
firmware keeps the unused Cardputer speaker/DAC powered down so this transition
does not produce a hiss or buzz.

## Cardputer is not discovered

- Allow Local Network access for CardBridge.
- Confirm the Mac and Cardputer are on the same 2.4 GHz network.
- Check that ports 7788/TCP and 7789/UDP are not blocked on the local network.
- Start the App before opening the Cardputer pairing screen.

## Pairing fails

Start a fresh **Add new computer** flow and use the current six-digit code.
Do not copy a token from a config file. If a previous pairing is stale, remove
that device from the App Settings and pair it again.

## Source build fails

Run `./scripts/doctor.sh --json` and fix the first item reported as `error`.
Most failures are an old Python, a missing Xcode selection, or a missing
PlatformIO executable. The project does not require Homebrew.
