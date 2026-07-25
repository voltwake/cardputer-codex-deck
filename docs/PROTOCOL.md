# Protocol summary

The full implementation is in `bridge/cardbridge/protocol.py` and the firmware
pairing/audio modules. This document is the compatibility contract for changes.

## Versioning

`version.json` owns the device protocol, Agent API, firmware, App, and config
schema versions. A protocol-major mismatch returns a structured
`upgrade_required` response. Missing protocol fields remain accepted as legacy
protocol v1 where the implementation documents that behavior.

## Device TCP: port 7788

- Newline-delimited UTF-8 JSON.
- Maximum encoded line: 4096 bytes.
- The initial hello negotiates protocol version and capabilities.
- Pairing uses a six-digit short code and then a random long-lived token.
- After pairing, every authenticated message carries the token.
- Key events preserve distinct `down` and `up` actions.
- Authenticated `pong` responses may include cumulative UDP receive progress
  and Core Audio output readiness. Firmware that understands these optional
  fields uses them to recover a stalled microphone path; older firmware safely
  ignores them.
- Unknown authenticated message types are ignored for forward compatibility.

## Device UDP audio: port 7789

Each packet contains a network-order sequence number and timestamp, an 8-byte
HMAC, and exactly 640 bytes of little-endian PCM16 mono audio (16 kHz, 20 ms).
The Agent starts with a jitter depth of about 100 ms, fills missing packets with
silence, resets stale buffered audio after a capture pause, and never
retransmits audio.

## Local Agent API

The default socket is:

```text
~/Library/Application Support/CardBridge/run/agent.sock
```

Clients first send:

```json
{"t":"hello","api":{"major":1,"minor":0}}
```

They may then request a snapshot, subscribe to updates, or issue the documented
status/settings commands. Snapshots never contain pairing tokens.
