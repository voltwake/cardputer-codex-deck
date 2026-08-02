# Codex Deck branding

## Public product name

**Codex Deck** is the public product and project name. We use the standard
spelling `Codex`, not `CodeX`.

The GitHub repository slug is `codex-deck`; the supported hardware
target is currently the M5Stack Cardputer ADV.

Suggested description:

> Codex Deck is an independent pocket hardware companion for OpenAI Codex,
> turning the M5Stack Cardputer ADV into a wireless keyboard, microphone, and
> live agent-status display for macOS.

## Compatibility names kept intentionally

The following names remain technical compatibility identifiers for the current
1.x line and must not be renamed casually:

- `CardBridge.app` and `CardBridgeAgent.app` bundle paths;
- the `cardbridge` Python package and CLI;
- `_cardbridge._tcp`, ports, local socket paths, and bundle identifiers;
- `CardBridge Microphone` and `CardBridge Microphone Feed` Core Audio devices;
- existing `~/.cardbridge` configuration and Keychain records;
- release artifact names beginning with `CardBridge-`.

This lets the product present as Codex Deck without forcing existing users to
re-pair devices, re-authorize Accessibility, or recreate audio settings. A
future major release may migrate these identifiers with an explicit upgrade
plan.

Codex Deck is independent and is not an official OpenAI product or endorsed by
OpenAI.
