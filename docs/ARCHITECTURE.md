# Current architecture

```text
旧 M5 固件 / 标准 ESP32 设备（多个并行连接）
  ├─ mDNS discovery: _cardbridge._tcp
  ├─ TCP 7788: authenticated JSON key/control protocol
  └─ UDP 7789: authenticated 16 kHz PCM16 audio frames
                    │ local network
                    ▼
Codex Deck (`CardBridge.app`, SwiftUI menu bar process)
  └─ supervised CardBridgeAgent (bundled Python runtime)
       ├─ DeviceRegistry → one DeviceSession per authenticated connection
       │    ├─ pairing/auth, negotiated capabilities, subscriptions
       │    ├─ held keys and per-device acknowledgement cursor
       │    └─ independent audio jitter buffer and counters
       ├─ capability-gated sync topics → each subscribed device
       ├─ global key ownership → Quartz keyboard injection
       ├─ one AudioLease → selected session jitter buffer → Microphone Feed
       ├─ TokenUsageStore ← Codex App Server notifications
       └─ local owner-only Unix control socket → multi-device App UI
```

The App and bundled Agent require an exact generated version/build match on
their owner-only local handshake. App startup probes an existing Unix socket
instead of trusting a leftover filesystem path. If an old Agent is still in
its bounded shutdown window during an in-place update, the App requests its
shutdown and retries the bundled Agent until the exact build answers.

The user-facing `CardBridge Microphone` is an input-only Core Audio HAL device.
The Agent writes to its paired output-only Feed device. BlackHole 2ch remains a
compatibility fallback when the bundled driver is absent.

The App owns lifecycle, permission requests, login launch, updates, and
diagnostics. The Agent owns network/audio/device behavior. `version.json`
generates an Agent capability profile separately from the Cardputer firmware
profile, so adding a server feature cannot make an unmodified M5 claim support
for it. Pairing secrets are kept outside ordinary status snapshots and logs.

## Multi-device state boundaries

`DeviceRegistry` is the only online-device source of truth. A stable device ID
may have only one active session: a newly authenticated session atomically
replaces the previous one, releases its keys and audio lease, and clears its
subscriptions. Buffered messages from the superseded TCP task are discarded,
and each connection serializes direct responses with background status/topic
updates. Device writes and close waits are bounded so a stalled client cannot
indefinitely block later devices or Agent shutdown. Pairing challenges are
keyed by connection, so simultaneous six-digit codes and failure counters
cannot overwrite one another.

Keyboard state is global only at the final injection boundary. Each session
tracks its own held keys; a physical key-down is injected once and the final
holder's release injects the key-up. Disconnect, unpair, and replacement clean
only the affected session. Modifier key-up events clear their own Quartz flag
at this final shared boundary.

Audio is deliberately not mixed. Every session receives authenticated UDP
packets into its own jitter buffer and increments its own counters. The first
valid stream obtains the single `CardBridge Microphone` lease automatically,
which keeps old M5 firmware working. Devices advertising `audio.lease.v1` can
explicitly claim/release; non-owners are counted but never sent to the HAL
feed. Lease changes reset the output boundary.

The standard `sync_*` topics are separate bounded snapshots. A device receives
only topics whose read/subscription capabilities it declared during hello, and
updates are merged and rate-limited per session. Subscription requests are
additive until explicit unsubscribe. Legacy v1 and current M5 capability
profiles do not receive new sync, Token, or lease messages.

Token usage is sourced only from `thread/tokenUsage/updated`. The store keeps
per-thread cumulative/last/delta/rate values, rejects stale out-of-order
notifications, and establishes a zero-delta baseline after a reset or new
turn. Device usage topics send the newest four records to leave room under the
4096-byte device line limit; the owner-only App snapshot retains the store's
bounded eight-session view.

## Trust boundaries

- The Cardputer and Mac must share a trusted local network.
- Pairing creates a random long-lived token; later device messages require it.
- UDP audio is authenticated but not retransmitted or encrypted separately.
- The local Unix socket is owner-only and validates the connecting UID.
- Codex integration exposes only short, privacy-trimmed public status.
