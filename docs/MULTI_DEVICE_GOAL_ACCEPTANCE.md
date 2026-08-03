# Completed multi-device Goal acceptance record

This is the machine-checkable handoff record for the completed multi-device
desktop Agent Goal, whose implementation baseline is commit `ba6c95f`. The
active Goal has moved on to repository and directory standardization in
[`GOAL.md`](GOAL.md). This record intentionally contains no thread IDs,
pairing material, prompt text, response text, reasoning, or tool output.

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

## Installed App and live multi-device acceptance — 2026-08-02

- The current source build of App and Agent `1.1.0` build `9` was installed over
  a stale same-version installation. No permission prompt appeared and the
  existing Accessibility grant, driver, pairing, and audio-device selection
  were retained.
- The unmodified M5 firmware `0.3.0` automatically reconnected through protocol
  `2.0` with compatibility `ok`. It held the audio lease while authenticated
  packet counts increased, with zero invalid packets.
- A second simulated standard device used the Waveshare
  ESP32-S3-Touch-AMOLED-1.75C identity, protocol `2.1`, and 11 declared
  capabilities. It paired while the M5 stayed online, exercised authenticated
  keyboard down/up and audio traffic, and correctly reported the audio lease as
  busy while the M5 remained owner.
- During the dual-device run the Agent reported Accessibility enabled, its Core
  Audio stream running, Codex App Server connected, Hooks listening, and
  subscription quota available. The simulator was then unpaired and its local
  token cache removed; the existing M5 pairing was left untouched.
- Live acceptance exposed an integrated Agent restart that could remain in
  `stopping`. mDNS teardown is now bounded, and every signal or App control
  shutdown request has an eight-second process-exit deadline. After installing
  the corrected build, an App control restart changed the Agent PID, the M5
  automatically reconnected, and audio, Accessibility, Codex, Hooks, and quota
  all returned healthy. Final `./scripts/healthcheck.sh --json` reported zero
  errors and zero warnings.
- The final verification passed 86 Python tests, 5 Swift tests, the M5 firmware
  build at 65,220 bytes RAM (19.9%) and 2,346,170 bytes Flash (70.2%), the full
  App/Agent/driver package build, generated-file checks, and `git diff --check`.

The existing M5 firmware was not updated, flashed, or replaced during this
acceptance pass.

The next independent Waveshare firmware Goal must send a stable `dev_id`,
vendor/model/name metadata, protocol `2.1`, and only the capabilities it
implements; it must use the documented TCP `7788`, UDP `7789`, HMAC audio
format, and capability-gated `sync_*` topics in `PROTOCOL.md`.

## Exhaustive compatibility follow-up — 2026-08-03

- A full firmware → TCP/UDP protocol → Agent registry/keyboard/audio/topic
  state → Swift App audit found and fixed five additional cross-device defects:
  modifier key-up reasserting its own Quartz flag, superseded same-ID sessions
  processing buffered input, later subscriptions replacing earlier topics,
  unbounded per-device acknowledgement history, and a stalled device writer
  blocking later broadcasts. ASCII key names are normalized before shared
  ownership. Explicit protocol-v1 clients that omit the capability array now
  receive the documented legacy defaults, and paired device metadata refreshes
  after authenticated firmware reconnects.
- An in-place App update exposed a separate client lifecycle race: build 10
  could see the old Agent inside its bounded shutdown window, reject the stale
  build, and then remain behind a dead Unix socket. App/Agent build 12 probes
  socket reachability, requests shutdown from an incompatible old Agent, and
  retries the exact bundled build. The original failure was reproduced during
  installation. The build 11 → 12 update then exposed a health-check false
  positive while the old Agent was still stopping; health checks now wait for
  the exact expected build in a settled state. The corrected install recovered
  automatically and `./scripts/healthcheck.sh --json` reported zero errors and
  zero warnings against App/Agent build 12.
- `./scripts/test.sh` passed 96 Python tests and 5 Swift tests. The firmware
  build passed at 65,220 bytes RAM (19.9%) and 2,346,170 bytes Flash (70.2%),
  generated-file checks passed, and the complete signed App/Agent/driver build
  validated successfully.
- The installed App and Agent both report `1.1.0` build `12`. The existing M5
  automatically reconnected as firmware `0.3.0` build `8`, protocol `2.0`,
  with all five implemented capabilities, Accessibility enabled, audio output
  running, no Agent issues, and zero invalid audio packets.
- A second simulated Waveshare device connected concurrently over protocol
  `2.1` with all 11 standard capabilities. It exercised authenticated keyboard
  down/up, additive `bridge.status` then `network.status` subscriptions, and
  authenticated UDP audio while the M5 remained microphone owner. The second
  device correctly stayed `busy`; both devices recorded zero invalid packets.
  It was then disconnected and unpaired, leaving one online/paired M5 and no
  pending pairing request.

Firmware source metadata is now `0.3.0` build `9` so the already-generated
protocol `2.1` identity is no longer indistinguishable from the physical build
8/protocol `2.0` image. No firmware behavior was changed for the Ctrl fix, and
the physical M5 was not flashed during this follow-up.
