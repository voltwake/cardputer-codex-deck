# Codex Deck protocol

This document is the compatibility contract for the desktop Agent and device
clients. The active implementation target is protocol `2.1`; the major remains
`2` so existing Cardputer firmware continues to use its legacy-compatible
messages and capability profile.

## Version and capability profiles

[`version.json`](../version.json) is the source of truth. The generated Python
Agent constants advertise the server profile; generated C++ constants advertise
only the capabilities already implemented by the shipped Cardputer firmware.
They are intentionally different:

- Agent profile: keyboard, PCM audio, Codex snapshots/phases, quota, topic
  subscriptions, bridge/network status, Token usage, and audio leases.
- Cardputer firmware profile: `control.keys.v1`, `audio.pcm16-16k.v1`,
  `agents.snapshot.v1`, `agents.phase.v1`, and `quota.v1`.

Protocol minor negotiation is `min(device_minor, agent_minor)`. A device only
receives capabilities it declares in its own hello. Device model, vendor, and
capability are never authentication or authorization boundaries.

## Device TCP: port 7788

- Newline-delimited UTF-8 JSON, with a maximum encoded line of 4096 bytes.
- Pairing uses a six-digit short code and a random long-lived token.
- After pairing, every authenticated message carries the token.
- Existing `key`, `ping`, `pong`, `agent_status`, `agent_list_req`, `agent_list`,
  `agent_ack`, `hello_ok`, `pair_required`, `paired`, and `upgrade_required`
  semantics remain valid.
- Unknown message types are ignored after authentication; they do not tear down
  the connection.
- Missing `protocol` and `capabilities` fields are accepted as legacy protocol
  v1. Legacy clients do not receive any `sync_*`, Token, or audio-lease message.

A current hello may include vendor-neutral metadata:

```json
{
  "t":"hello",
  "dev_id":"stable-device-id",
  "token":null,
  "device":{
    "vendor":"waveshare",
    "model":"esp32-s3-touch-amoled-1.75c",
    "name":"Desk Orb",
    "firmware":"0.1.0",
    "build":1
  },
  "protocol":{"major":2,"minor":1},
  "capabilities":["sync.subscribe.v1","bridge.status.v1"]
}
```

## Standard topics

Topic responses use this bounded envelope:

```json
{
  "t":"sync_snapshot",
  "id":7,
  "topic":"bridge.status",
  "schema":1,
  "seq":42,
  "generated_at_ms":1785690000000,
  "data":{},
  "token":"…"
}
```

The token is present on the authenticated device channel but is never included
in local App snapshots, diagnostics, or logs. Every topic has its own monotonic
sequence and its own payload. A topic without the negotiated read capability
returns a structured `capability_required` error.

| Topic | Read capability | Subscription capabilities |
|---|---|---|
| `bridge.status` | `bridge.status.v1` | `sync.subscribe.v1` |
| `network.status` | `network.status.v1` | `sync.subscribe.v1` |
| `codex.sessions` | `agents.snapshot.v1` | `sync.subscribe.v1` |
| `codex.usage` | `usage.tokens.v1` | `sync.subscribe.v1` + `usage.tokens.stream.v1` |

One-time reads use `sync_req`:

```json
{"t":"sync_req","id":7,"topics":["bridge.status","network.status"],"token":"…"}
```

An unknown topic returns a bounded structured `error` with
`code: "unsupported_topic"` and leaves the connection usable; a known topic
whose capability was not negotiated returns `capability_required`.

Subscriptions use `sync_subscribe`. The Agent clamps `min_interval_ms` to
250–60000 ms; Token stream downlink is therefore limited to 4 Hz even when the
upstream App Server reports more events. Updates use `sync_update`, and
`sync_unsubscribe` returns the remaining topic set. The request `id`, when
present, is echoed by confirmations and errors.

`bridge.status` contains Agent state/version/build, negotiated protocol,
uptime, Accessibility/audio readiness, active microphone device ID, and public
issue codes. `network.status` contains LAN reachability, address, TCP/UDP
ports, and `_cardbridge._tcp`; it never contains a Wi-Fi password or requires
an SSID. `codex.sessions` contains at most eight privacy-trimmed sessions.

## Keyboard ownership

Only a session with `control.keys.v1` can inject keys. Held keys are tracked per
connection. A key-down is injected once when the first device holds it, and the
final key-up is injected only after the last holder releases it. Disconnect,
unpair, and same-ID replacement release only that session's keys.

## Device UDP audio: port 7789

Each packet contains network-order sequence and timestamp fields, an 8-byte
HMAC, and exactly 640 bytes of little-endian PCM16 mono audio (16 kHz, 20 ms).
The HMAC is checked against the authenticated device token. Same-IP devices are
distinguished by their token; an invalid packet is not routed to another
session.

Every authenticated session owns its own sequence counters and jitter buffer.
There is one public `CardBridge Microphone` output, so the Agent uses a single
explicit activity lease rather than mixing microphones:

- The first valid authenticated audio packet automatically claims the lease,
  including for old M5 firmware that knows no lease command.
- A device with `audio.lease.v1` may send `audio_claim` or `audio_release`.
  Claiming a busy lease returns `audio_lease` with `state: "busy"`; it never
  silently preempts the owner.
- Non-owners are authenticated and counted but their samples never enter the
  HAL feed. They receive `busy`/owner state when they negotiated the lease
  capability.
- Disconnect, unpair, explicit release, or 3000 ms without a valid owner audio
  packet releases the lease and resets the output boundary before another
  session can take it.

The Agent starts playback at a configurable jitter depth, conceals missing
frames with silence, and never retransmits audio.

## Token usage

The monitor consumes only the public App Server notification
`thread/tokenUsage/updated` and stores no prompt, response, reasoning, tool
arguments, command output, or auth data. It records per-thread `total`, `last`,
`delta`, `model_context_window`, `window_ms`, and `tokens_per_second`.

`codex.usage` is explicit when data is not available:

```json
{"available":false,"source":"unavailable","reason":"provider_unsupported","sessions":[]}
```

Repeated notifications are ignored, stale out-of-order notifications are
discarded without moving the high-water mark, and a newer decreasing/reset
value establishes a new baseline with zero delta/rate. None can create negative
or invented usage. Process restart does not reconstruct history when the
upstream does not provide it. Device envelopes include the newest four usage
sessions so the full `total`/`last`/`delta` breakdown remains within 4096 bytes;
the owner-only local snapshot retains the store's eight-session bound.

## Local Agent API

The owner-only Unix socket remains:

```text
~/Library/Application Support/CardBridge/run/agent.sock
```

API `1.1` is minor-compatible. Older App clients can still decode the required
snapshot fields. New snapshots expose all online devices, all pending pairing
requests, per-device capabilities/subscriptions/audio lease, global health,
and explicit Token availability. Snapshots, diagnostics, and logs contain no
pairing token, Wi-Fi password, API key, transcript, reasoning, command output,
or audio.
