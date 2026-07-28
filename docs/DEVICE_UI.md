# Cardputer screens and Codex states

The Cardputer UI is a 240×135 pixel interface. The images below are
deterministic 4× previews rendered from the current firmware layout, shipped
background, pet frames, RGB565 palette, and safe example text. They are not
camera photographs and never contain a real Codex session, prompt, command, or
transcript.

| Home | Codex detail |
| --- | --- |
| ![Cardputer home screen with the Codex card selected](images/device-home.png) | ![Codex detail screen while a tool is running](images/codex-detail.png) |

Regenerate both images after changing the device layout or pet assets:

```sh
python3 tools/render_ui_screenshots.py
```

## Home and detail pages

The home page keeps the current Codex state visible beside four shortcuts:
Wi-Fi, paired Mac, brightness, and screen-off timeout. Select the Codex card and
press `Enter` to open the detail page.

The detail page shows one of up to eight sessions. Its title uses the session
title, then the project name, then `Codex` as fallbacks. The body contains only
a privacy-trimmed activity such as `Editing project files`; prompts,
transcripts, reasoning, raw commands, tool arguments, and command output are
never forwarded. Left/right changes sessions, the `1/8` badge shows the
position, and Escape returns home.

## Codex visual states and copy

The wire protocol has six agent states. Firmware splits `running` into
`THINKING` and `RUNNING`, so the screen has seven visual states in total.
Colour is never the only signal: the pet animation, workshop monitor, data
conduits, platform effect, and home status rail change too.

| Visual state | Incoming state | Home label | Typical detail copy | Appearance |
| --- | --- | --- | --- | --- |
| Offline | Mac link disconnected, or `offline` | `OFFLINE` | `Codex Deck is offline` when the Mac link is down | Failed pet with red X indicators; a disconnected pet also has a grey slash |
| Idle | `idle`, no selected session, or agent feed unavailable | `IDLE` | `Waiting for Codex sessions` when connected without a usable session; `Session ready` after acknowledgement | Grey idle pet, power glyph, quiet conduits and short home rail |
| Thinking | `running` + `thinking` (also the fallback when phase is missing) | `THINKING` | `Understanding the task`, `Understanding the task...`, or `Thinking...` | Waiting pet with slower cyan telemetry and a moving home segment |
| Running | `running` + `tool` | `RUNNING` | Safe summaries such as `Editing project files`, `Running a command`, `Searching references`, `Working with an image`, or `Running tests` | Running pet with faster cyan telemetry, packets, platform layers, and a wider moving home segment |
| Needs input | `needs_input` | `INPUT` | `Waiting for your approval` or `Waiting for your answer` | Waiting pet with an orange prompt cursor, breathing conduits, and pulsing home rail |
| Ready | `ready` | `READY` | Usually `Task completed`; a safe final public activity may remain visible | Review pet with a green check mark, filled conduits, completion platform effect, and solid home rail |
| Blocked | `blocked` | `BLOCK` | `Task encountered a problem` | Failed pet with red X indicators, broken conduits, and solid home rail |

On `READY` or `BLOCK`, pressing `Enter` acknowledges the Cardputer reminder.
The session becomes `IDLE`, the unread marker clears, and the detail copy becomes
`Session ready`. This acknowledgement is local to the Cardputer view; it does
not modify or restart the Codex task. A newer user prompt automatically focuses
that session again.

## Empty and fallback copy

| Condition | Detail title | Detail body |
| --- | --- | --- |
| Mac link disconnected | `Codex` | `Codex Deck is offline` |
| Mac connected, but no live Codex session is available | `Codex` | `Waiting for Codex sessions` |
| Live session | Session title, project name, or `Codex` | The latest privacy-safe activity summary |

## Quota styles

The two detail rows are labelled `WEEKLY` and `5H`.

| Mode | Display |
| --- | --- |
| ChatGPT subscription | Remaining percentage as a bar: green at 30–100%, yellow below 30%, and red below 10%. Zero keeps a one-pixel red marker. A window not reported by the service shows `--`. |
| API key or custom provider | A full, static green rail. ChatGPT subscription windows do not apply, so the UI deliberately avoids a misleading percentage or infinity symbol. |
| Unknown, or agent feed offline | A grey outlined rail containing `--`. This is not presented as unlimited. |

## Keyboard-mode indicator

The keyboard icon appears at the far left of the home status bar and floats at
the top-left of the detail scene. A filled cyan keyboard means forwarding mode
is enabled; its audio path is active unless the microphone is muted. An
outlined grey keyboard with a red slash means local navigation is enabled and
forwarding is off. BtnA changes this mode without changing the current page.

## Battery and power behaviour

The battery icon includes a numeric percentage on both the status bar and the
Codex detail scene. While external USB power or a sustained charging trend is
detected, the icon and percentage turn orange and a lightning bolt appears in
the battery body. Cardputer ADV does not route the charger's dedicated status
pins to the MCU, so a computer USB connection is detected immediately while a
power-only charger may take several filtered samples to appear.

After 15 seconds without input the backlight dims automatically. The selected
screen-off timeout then places both the backlight and LCD controller into
sleep. Input wakes the screen at the configured brightness. Untouched static
screens also reduce their full-frame refresh rate, while active Codex states
retain smoother animation.
