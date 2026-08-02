# Install Codex Deck

Codex Deck has two supported installation paths. Use the prebuilt release for
normal use; build from source only when developing or when no release artifact
supports your Mac.

## A. Prebuilt release (recommended)

From a checkout of this repository, an automation-friendly installer can
download the latest published release, verify its checksum, mount the DMG,
and install the App:

```sh
./scripts/install-release.sh
```

Use `--version 1.1.0` to select a specific tag. This requires the release to
have been published; draft releases are intentionally not selected by the
GitHub API.

1. Open the GitHub Release matching the required version.
2. Download the signed/notarized `CardBridge-<version>.dmg` (or `.pkg`) and
   `SHA256SUMS`.
3. Verify the checksum before opening the App:

   ```sh
   shasum -a 256 -c SHA256SUMS --ignore-missing
   ```

4. Drag `CardBridge.app` to `/Applications` and launch it.
5. Approve the one-time administrator prompt if the App offers to install
   `CardBridge Microphone`.
6. In **System Settings → Privacy & Security → Accessibility**, allow
   CardBridge for keyboard forwarding.
7. If macOS asks for Local Network access, allow it so Bonjour can discover the
   Cardputer.
8. On the Cardputer, open **Computers → Add new computer** and enter the
   six-digit code shown by Codex Deck.
9. In Typeless, select `CardBridge Microphone` as the microphone and use F13
   (or the configured F14–F16 key) for hold-to-record.

The Codex Deck App (currently shipped as `CardBridge.app`) stores pairing secrets in the macOS Keychain and starts its supervised
Bridge Agent automatically. It does not require Python, a virtual environment,
or a terminal.

## B. Build and install from source

From a clean checkout:

```sh
cd /path/to/codex-deck
./scripts/doctor.sh
./scripts/bootstrap.sh
./scripts/test.sh
./scripts/build.sh
./scripts/install.sh
./scripts/healthcheck.sh
```

The source path requires macOS 13+, Apple Silicon, Xcode/Command Line Tools,
Python 3.10+, PlatformIO, network access for pinned dependencies, and a
working Apple development or ad-hoc signing setup. `bootstrap.sh` creates the
private `bridge/agent/.venv`; it does not modify a system Python installation.

## Firmware

The release includes a prebuilt firmware `.bin`. For a source build, connect a
Cardputer ADV and run:

```sh
pio run -d firmware/m5stack-cardputer-adv
pio run -d firmware/m5stack-cardputer-adv -t upload
```

Let PlatformIO auto-detect `/dev/cu.usbmodem*`. The port can change after a
reset. Firmware flashing is separate from installing the Mac App.

## Verify

```sh
./scripts/healthcheck.sh --json
```

A healthy installation reports the App and Agent versions from `version.json`,
an owner-only control socket, the audio driver state, and the Agent service
state. A missing Accessibility grant is a user action, not a build failure.

## Uninstall

```sh
./scripts/uninstall.sh
```

This removes the App and stops its child Agent. Use the App's Audio settings or
the explicit driver uninstall script if you also want to remove the HAL driver.
Uninstalling does not delete `~/.cardbridge` or Keychain pairing data unless
you explicitly remove those records.

## What an automation agent must not bypass

Administrator, Accessibility, Local Network, Microphone, Keychain, and Codex
Hook trust prompts require an explicit user decision. An AI agent can detect
and report the pending action, but must not scrape credentials, disable
Gatekeeper, or bypass the prompt.
