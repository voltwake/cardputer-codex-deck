# Current repository standardization Goal acceptance record

> **Status: complete**

The active acceptance criteria are defined in [`GOAL.md`](GOAL.md). The code
and directory migration was validated on 2026-08-02 from multi-device baseline
`5f2a9b9`; the planning commit is `56990b6`. Both sit on the latest upstream
default branch at `408fda0`, including the separately merged battery/status UI
optimization.

## Structure

- M5 firmware is self-contained under `firmware/m5stack-cardputer-adv/`, with
  its own `platformio.ini`, source, assets, build instructions, and generated
  version header.
- The device-neutral desktop product is split into `bridge/agent/`,
  `bridge/macos/`, and `bridge/driver/`.
- Root user commands remain in `scripts/`; shared generators, release metadata,
  protocol documentation, and version governance remain at repository level.
- Root `src/`, `assets/`, `platformio.ini`, `macos/`, and `driver/` no longer
  exist. `tools/check_project.py` rejects their reintroduction.
- No component has a second active copy at its old path.

## Automated verification

- `./scripts/bootstrap.sh`: passed and rebuilt the Agent editable installation
  at `bridge/agent/.venv`.
- `./scripts/doctor.sh --json`: passed with zero errors and zero warnings.
- `./scripts/test.sh`: passed with 82 Python tests, 5 Swift tests, the project
  contract check, generated-file check, and M5 firmware build.
- M5 firmware used 65,220 bytes static RAM (19.9%) and 2,346,170 bytes Flash
  (70.2%). The directory migration did not change firmware behavior; it
  preserved the upstream battery/status UI optimization. Protocol version,
  build number, and capability profile were not changed by the migration.
- `./scripts/build.sh`: passed; it built the firmware, Python Agent, Swift App,
  Core Audio driver, and an Apple Development-signed
  `bridge/macos/dist/CardBridge.app`.
- Artifact validation passed for Codex Deck/CardBridge App and Agent version
  `1.1.0` build `9`, architecture `arm64`, nested signatures, bundled driver,
  resources, and generated compatibility data.
- `bridge/agent/.venv/bin/python tools/generate_versions.py --check`: passed.
- `git diff --check`: passed.

The first post-move Swift test correctly exposed an absolute path embedded in
the old ignored module cache; cleaning the regenerable cache fixed it. The
first package build also exposed the moved virtual environment's stale
`pyinstaller` shebang. `build_app.sh` now invokes PyInstaller through the new
environment's Python module path, and the complete package build then passed.

## Compatibility and safety boundaries

- Device protocol remains `2.1`, Agent API remains `1.1`, configuration schema
  remains `2`, and legacy protocol v1 support remains enabled.
- `CardBridge.app`, `CardBridgeAgent.app`, Python package, bundle IDs, mDNS,
  ports, socket, Keychain/config locations, audio-device names, and release
  artifact names remain unchanged for 1.x compatibility.
- The installed App and running Agent were not replaced, no macOS permission
  was changed, and the connected M5 was not flashed.
- The four user-owned PNG files under `docs/` remain untracked and excluded
  from the migration commit.

## Remote repository rename

- Migration commit `07e27e2` was pushed to the old repository's `main` before
  the rename. GitHub CI run `30762134513` then passed every project-contract,
  generated-version, syntax, secret, Python, Swift, firmware, packaging, and
  artifact-validation step.
- The same public GitHub repository (`R_kgDOTZPG5A`) was renamed in place from
  `voltwake/cardputer-codex-deck` to `voltwake/codex-deck`; it was not copied or
  recreated. Its default branch remains `main` and the product-neutral
  description was updated.
- Local `origin` now explicitly uses
  `https://github.com/voltwake/codex-deck.git` for fetch and push. A post-rename
  fetch succeeded and `main` matched `origin/main` at `07e27e2`.
- `git ls-remote` through both new and old clone URLs returned the same `main`
  commit. The old web URL redirected to the canonical new URL, while all current
  product metadata uses the new URL directly.
- The raw `release/appcast.xml` is reachable through the new slug and links to
  `https://github.com/voltwake/codex-deck`. The App's generated `SUFeedURL`,
  installer default, project metadata, release script, and repository contract
  all use the new slug.
- The repository currently has no published Releases and no tags. Therefore an
  actual release artifact download and Sparkle installation cannot be exercised;
  URL/feed wiring is verified, and end-to-end download remains a first-release
  gate rather than a hidden success claim. No App was installed while checking
  this.
- GitHub Pages is not enabled. Public code search found no external workflow
  using `voltwake/cardputer-codex-deck` as an Action. Existing PR numbers and
  history, including PRs 1–7, remained available under the new repository URL.

The completed multi-device Goal evidence is preserved separately in
[`MULTI_DEVICE_GOAL_ACCEPTANCE.md`](MULTI_DEVICE_GOAL_ACCEPTANCE.md).
