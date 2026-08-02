# Codex Deck device firmware

Each subdirectory is an independent implementation of the standard Codex Deck
device protocol. Firmware projects own their board configuration, source,
assets, dependencies, and declared capabilities; they must not import private
code from another device directory.

Current implementation:

- `m5stack-cardputer-adv/` — M5Stack Cardputer ADV firmware.

Future devices, including Waveshare boards, get their own sibling directory.
