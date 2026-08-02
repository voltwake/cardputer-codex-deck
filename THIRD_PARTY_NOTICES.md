# Third-party notices

This file summarizes the third-party components used by CardBridge. The
corresponding source, license text, and build metadata must ship with any
redistribution that includes the component.

| Component | Where used | License / notice |
| --- | --- | --- |
| BlackHole-derived audio engine | `bridge/driver/` | GPLv3; see [`bridge/driver/LICENSE-GPL-3.0.txt`](bridge/driver/LICENSE-GPL-3.0.txt) and [`bridge/driver/NOTICE.md`](bridge/driver/NOTICE.md). |
| Source Han Sans CN Medium | `firmware/m5stack-cardputer-adv/assets/fonts/cardbridge-ui-13.bff` and font generator | SIL Open Font License 1.1; see [`firmware/m5stack-cardputer-adv/assets/fonts/LICENSE-SourceHanSans.txt`](firmware/m5stack-cardputer-adv/assets/fonts/LICENSE-SourceHanSans.txt). |
| Sparkle 2.9.4 | macOS updater framework | Sparkle project license and notices are downloaded and checksum-verified by `bridge/macos/scripts/bootstrap_sparkle.sh`. |
| M5Cardputer / M5Unified / M5GFX | firmware dependency | Follow the licenses shipped by the corresponding PlatformIO packages. Versions are pinned in `firmware/m5stack-cardputer-adv/platformio.ini`. |
| ArduinoJson 6.21.5 | firmware dependency | MIT; version is pinned in `firmware/m5stack-cardputer-adv/platformio.ini`. |
| NumPy, sounddevice, zeroconf, PyObjC | Python Bridge dependencies | Follow the licenses shipped by the installed Python distributions. Build inputs are listed in `bridge/requirements-build.txt`. |

## Generated and commissioned assets

The repository also contains icons, UI backgrounds, pet animation resources,
and generated binary font data. Their source and permission status are tracked
in [`firmware/m5stack-cardputer-adv/assets/ASSET_SOURCES.md`](firmware/m5stack-cardputer-adv/assets/ASSET_SOURCES.md). Do not copy an asset
into another project until its source license is confirmed.

This summary is not a substitute for the full license texts. A release job
must include the exact notices for every bundled binary dependency.
