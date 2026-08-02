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

If two devices are pairing at once, use the code shown beside the matching
device name/model. Each connection has its own expiry and three-attempt limit;
a failed code on one device does not invalidate the other request. The menu bar
App lists all pending requests and all online devices.

## One device has no keyboard effect

Check that the device declares `control.keys.v1` and that Accessibility is
granted to Codex Deck. A device without that capability is still allowed to
connect and use only the capabilities it negotiated. Disconnecting or replacing
one device releases only its held keys; it does not disable another online
device.

## Audio says busy or changes devices

The Agent exposes one `CardBridge Microphone`, so multiple microphones are not
mixed. The first valid authenticated UDP stream automatically owns the lease,
including an unmodified M5. A standard device with `audio.lease.v1` can send an
explicit claim/release; a claim while another device owns the lease returns
`busy`. The non-owner's packets are authenticated and counted but never enter
the HAL feed. A release, disconnect, or 3-second valid-audio silence resets the
stream boundary before another device takes over.

## Standard sync or Token data is missing

Inspect the device's negotiated capability list. `sync_req` needs the topic's
read capability; subscriptions additionally need `sync.subscribe.v1`, and
`codex.usage` streaming needs `usage.tokens.stream.v1`. Legacy v1 and the
shipped M5 capability profile intentionally receive no `sync_*`, Token, or
audio-lease messages. Token status is shown as **不可用/未知** until the Codex
App Server emits `thread/tokenUsage/updated`; API/custom providers may not
provide it. The device usage topic is bounded to the newest four sessions to
stay within the 4096-byte control line.

## Same-ID reconnection

Only one session for a device ID appears online. A new authenticated connection
atomically replaces the old one, releases its held keys and audio lease, clears
subscriptions, and starts with a fresh per-session jitter buffer. This is
expected during a reconnect or when two instances use the same configured ID.

## Source build fails

Run `./scripts/doctor.sh --json` and fix the first item reported as `error`.
Most failures are an old Python, a missing Xcode selection, or a missing
PlatformIO executable. The project does not require Homebrew.
