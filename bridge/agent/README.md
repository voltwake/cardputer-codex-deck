# CardBridge Agent development and diagnostics

The bridge advertises `_cardbridge._tcp` over mDNS, pairs multiple vendor-neutral
devices with isolated six-digit challenges, injects authenticated TCP key events
with Quartz, writes the single active authenticated UDP microphone stream into
**CardBridge Microphone Feed** (with **BlackHole 2ch** as a compatibility
fallback), and publishes privacy-trimmed local Codex sessions and Token usage.
Normal users run the bundled Agent through `CardBridge.app`; the Python commands
below are for development and diagnostics.

## 1. Install CardBridge Microphone and configure Typeless

1. Launch `CardBridge.app` and approve its one-time `CardBridge Microphone` driver installation. The same action is available later in the menu and Settings → Audio.
2. Open **Audio MIDI Setup** and confirm that input-only `CardBridge Microphone` and output-only `CardBridge Microphone Feed` exist at 48,000 Hz.
3. In Typeless, select `CardBridge Microphone` as the microphone and configure its hold-to-record shortcut as **F13** (the device default). The device setting can instead use F14–F16.
4. For an independent check, open QuickTime Player → New Audio Recording and select `CardBridge Microphone` as the microphone.

The bridge writes to the Feed device; Typeless and QuickTime read the paired input device. The driver reports the input as USB for compatibility with applications that filter `Virtual` transports, but it remains a software HAL plug-in rather than real UAC hardware. Do not create an Aggregate Device for this path. If the bundled driver is absent, the Agent automatically falls back to BlackHole 2ch.

## 2. Create the Python 3.10 environment

```sh
cd /path/to/codex-deck/bridge/agent
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

If `/usr/bin/python3` is not Python 3.10 or newer, invoke the installed Python 3.10 executable explicitly. No Homebrew package is required.

## 3. First run and pairing

```sh
cd /path/to/codex-deck/bridge/agent
source .venv/bin/activate
cardbridge
```

At first launch, macOS asks for Accessibility access. If necessary, open **System Settings → Privacy & Security → Accessibility** and enable the Python executable used by this virtual environment, then restart CardBridge. Without this permission audio still works, but CGEvent keyboard injection is blocked.

Select **Settings → Computers → Add new computer** on the Cardputer. The bridge prints a six-digit code and also posts a macOS notification. Enter that code on the device. In the packaged App, the generated 32-byte random token is stored in the macOS Keychain and `~/.cardbridge/config.json` retains only non-secret identity/device metadata. Explicit development configs keep their token in the mode-`0600` test file so isolated simulator runs remain portable.

Useful diagnostic run (no key injection and no sound-device requirement):

```sh
cardbridge --dry-run --no-audio -v
```

## 4. Legacy LaunchAgent (development only)

`CardBridge.app` uses `SMAppService` and automatically migrates/removes the old item. Only use this legacy installer when deliberately testing the source Agent without the App:

```sh
cd /path/to/codex-deck/bridge/agent
source .venv/bin/activate
python install_launch_agent.py install
```

Logs are written to `~/.cardbridge/bridge.log` and `~/.cardbridge/bridge-error.log`. Remove the service with:

```sh
python install_launch_agent.py uninstall
```

## 5. Enable Codex live status

Session names/projects and public streamed agent/tool events come from a separate read-only official Codex App Server in every local authentication mode. Token totals are recovered and tailed from `~/.codex/sessions/**/*.jsonl`, including turns run by Codex Desktop through another App Server process. The Token reader JSON-decodes only `token_count` event lines; session/turn IDs are extracted from bounded byte prefixes, while response items, summaries, prompts, reasoning, tool arguments, and command output are never decoded or retained. Official lifecycle Hooks remain the cross-process status fallback and report over UDP `127.0.0.1:7790`. CardBridge derives only a short safe action such as `Editing ui.cpp` or `Building firmware`; it never forwards raw commands, tool arguments, prompt text, transcripts, reasoning events, command output, or `auth.json`. ChatGPT OAuth exposes real weekly/5-hour windows; API/custom-provider mode is explicitly marked unlimited for those ChatGPT windows, while lookup failure remains unknown rather than being mislabeled unlimited.

The packaged App manages Hooks from Settings and points them at the bundled stable Agent path. For source-only development, preview the merged user-level hook configuration first:

```sh
python install_codex_hooks.py show
```

Install it when the paths look correct:

```sh
python install_codex_hooks.py install
```

Restart or reload Codex and review its hook-trust prompt. Do not bypass that trust check. To remove only CardBridge's hook commands while preserving unrelated hooks:

```sh
python install_codex_hooks.py uninstall
```

Use `cardbridge --no-codex` to disable both the App Server monitor and local hook receiver, or `--hook-port` to choose another loopback port (set the same `CARDBRIDGE_HOOK_PORT` for the reporter).

## 6. Local menu bar status/control API

By default CardBridge creates an owner-only Unix socket at:

```text
~/Library/Application Support/CardBridge/run/agent.sock
```

The socket directory uses mode `0700`, the socket uses `0600`, and the server also verifies the connecting process UID. A client must first send one newline-delimited JSON hello:

```json
{"t":"hello","api":{"major":1,"minor":0}}
```

It may then request `snapshot_req`, send `subscribe` for live snapshots, or use a `command` named `set_gain`, `unpair`, `install_hooks`, `uninstall_hooks`, `restart`, or `shutdown`. Snapshots expose service, all online devices, all pending pairings, per-device capabilities/subscriptions/audio lease, audio/Codex health, and explicit Token availability, but never expose pairing tokens. Use `--no-control-socket` to disable this endpoint or `--control-socket PATH` to override it.

## 7. End-to-end simulator

Terminal 1:

```sh
cd /path/to/codex-deck/bridge/agent
source .venv/bin/activate
cardbridge --dry-run --no-audio -v
```

Terminal 2:

```sh
cd /path/to/codex-deck/bridge/agent
source .venv/bin/activate
python fake_device.py
```

Enter the pairing code printed in terminal 1. The simulator authenticates, sends English/shift/punctuation key down+up events, holds/releases F13, sends the reserved phase-two request, and streams a real-time 440 Hz sine wave as authenticated 20 ms UDP frames. Its local token cache is `.fake_device.json` and is git-ignored.

Run all dependency-free tests with:

```sh
cd /path/to/codex-deck/bridge/agent
PYTHONPATH=. python -m unittest discover -s tests -v
```

From the repository root, also verify that every generated version constant matches `version.json`:

```sh
python3 tools/generate_versions.py --check
```

## Multi-device protocol behavior

`DeviceRegistry` owns one `DeviceSession` per authenticated connection. Device
ID, vendor, and model are descriptive rather than an allowlist. A second
authenticated connection with the same ID atomically replaces the first and
cleans its held keys, subscriptions, acknowledgement cursor, jitter buffer,
and audio lease. Pairing requests are keyed by connection, so concurrent codes
and failure counters remain independent.

The Agent negotiates protocol `2.1` and only enables a capability declared by
the device. `sync_req`/`sync_subscribe` use bounded per-topic snapshots for
`bridge.status`, `network.status`, `codex.sessions`, and `codex.usage`; the
requested interval is clamped to 250–60000 ms. Device Token updates contain the
newest four sessions so the authenticated JSON line remains at most 4096 bytes.
Legacy v1 and the shipped M5 capability profile receive no new `sync_*`, Token,
or lease messages.

Audio is not mixed. Every session has a separate jitter buffer. The first
valid packet automatically owns the one public microphone lease, so the old M5
continues to work without a new command. Devices with `audio.lease.v1` can
explicitly claim or release; non-owners are authenticated and counted but do
not reach the HAL feed. Lease handoff resets the output boundary, and 3 seconds
without valid owner audio releases it.

## Protocol and recovery behavior

- TCP `7788`: newline-delimited UTF-8 JSON capped at 4096 bytes, five-second ping/pong, disconnect after three misses. Agent snapshots budget titles to 32 characters, project names to 20 characters, and public activity to 72 UTF-8 bytes so all eight worst-case CJK sessions still fit. The hello negotiates device protocol major/minor and the capability intersection. Missing fields are accepted as legacy v1; an unsupported major receives `upgrade_required`. Every post-handshake message carries the session token; unknown authenticated message types are ignored for forward compatibility.
- UDP `7789`: network-order `seq(u32) + timestamp_ms(u32) + HMAC8`, followed by exactly 640 bytes of little-endian PCM16 mono audio.
- Local Unix socket: Agent API v1 newline-delimited JSON for status subscriptions and menu bar commands, limited to the logged-in user.
- Playback starts at a configurable 100 ms jitter depth. Missing sequences become silence; packets are not retransmitted.
- Firmware stops microphone capture and UDP sending whenever muted or disconnected. Reconnect uses exponential backoff capped at 30 seconds.
- Each device maintains its own selected Mac control connection. The Agent
  routes authenticated key/audio traffic by session, so devices are not
  broadcast to one another and an old M5 can continue using the original wire
  messages.
