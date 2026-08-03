# Codex Deck security policy

## Scope

Codex Deck runs on a trusted local Mac and exchanges authenticated control and
audio traffic with a paired Cardputer over the local network. The bridge does
not provide a public Internet service. Pairing tokens are stored in the Mac
Keychain by the packaged app and in mode-0600 development configuration when
the source agent is used.

The project intentionally requests macOS permissions for local-network
discovery, Accessibility keyboard injection, and administrator installation
of the audio driver. It must never bypass those user-consent boundaries.

## Reporting a vulnerability

Please do not open a public issue for an unpatched security problem. Use the
repository's **Security → Report a vulnerability** GitHub Security Advisory
form (or the private security contact configured there), including:

- affected version or commit;
- operating system and architecture;
- a minimal reproduction or proof of concept;
- whether pairing, token exposure, arbitrary key injection, or sensitive
  Codex data is involved.

Do not include real pairing tokens, Wi-Fi passwords, API keys, `auth.json`,
transcripts, or audio recordings in a report.

## Security invariants

- Never log or export pairing tokens.
- Never forward Codex prompts, transcripts, reasoning, raw commands, tool
  arguments, command output, or `auth.json`.
- When collecting local Codex Token usage, JSON-decode only `token_count`
  records. Extract session/turn IDs from bounded metadata prefixes and never
  decode response items, summaries, prompts, reasoning, tool arguments, or
  command output.
- Keep the local control socket owner-only and validate the connecting UID.
- Reject unauthenticated post-handshake device messages.
- Keep release artifacts signed, notarized where applicable, and accompanied
  by SHA-256 checksums and a release manifest.
