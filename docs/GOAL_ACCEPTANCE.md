# Current Goal acceptance record

This is the machine-checkable handoff record for the active multi-device
desktop Agent Goal in [`GOAL.md`](GOAL.md). It intentionally contains no
thread IDs, pairing material, prompt text, response text, reasoning, or tool
output.

## Desktop and automated evidence — 2026-08-02

- `./scripts/test.sh`: passed. The suite covers Python protocol/legacy
  compatibility, multi-device pairing and replacement, per-device keyboard and
  acknowledgement state, independent audio leases/jitter, Token accounting,
  privacy, Swift decoding, and the available firmware build.
- `./scripts/build.sh`: passed. Firmware, Agent packaging, Swift App, driver,
  signing, and App artifact validation completed successfully.
- `git diff --check`: passed.
- `bridge/.venv/bin/python tools/generate_versions.py --check`: passed.
- Independent follow-up acceptance added regression coverage for acknowledging
  an actively running session and for serializing audio-boundary resets with
  the live PortAudio callback. The final Python suite contains 82 passing tests.
- A real local Codex App Server read-only turn completed with approval policy
  `never` and no tools. The acceptance collector observed 20 notifications,
  including one `thread/tokenUsage/updated`; its final cumulative breakdown was
  `total=20218`, `input=20213`, `cached_input=0`, `output=5`,
  `reasoning_output=0`, received at `1785690928677` ms since Unix epoch. Only
  counts and receipt timing were retained.

The actual upstream notification is paired with the automated
`CodexMonitor`/`TokenUsageStore` ingestion test and the device-size, delta,
rate, duplicate, reset, out-of-order, unavailable, and Swift UI fixtures.

## Explicitly deferred physical action

The existing installed M5 firmware was not updated, flashed, or replaced.
SR must perform the one physical regression pass required by `GOAL.md` §12.2:
reconnect the existing pairing, verify keyboard down/up and microphone
bridging, confirm Codex state/quota, and keep it online beside a second
simulated or real device. This handoff does not install the App, replace a
running Agent, or trigger macOS permission prompts.

The next independent Waveshare firmware Goal must send a stable `dev_id`,
vendor/model/name metadata, protocol `2.1`, and only the capabilities it
implements; it must use the documented TCP `7788`, UDP `7789`, HMAC audio
format, and capability-gated `sync_*` topics in `PROTOCOL.md`.
