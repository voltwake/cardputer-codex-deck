from __future__ import annotations

import logging
from typing import Any

LOG = logging.getLogger("cardbridge.keyboard")

# macOS ANSI virtual key codes. Printable input intentionally follows the US
# layout because phase one explicitly targets English/code/shortcut workflows.
KEY_CODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5,
    "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
    "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
    "enter": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41,
    "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "tab": 48, " ": 49, "`": 50, "backspace": 51, "escape": 53,
    "cmd": 55, "shift": 56, "alt": 58, "ctrl": 59,
    "f13": 105, "f14": 107, "f15": 113, "f16": 106,
    "home": 115, "delete_forward": 117, "end": 119,
    "left": 123, "right": 124, "down": 125, "up": 126,
}


class KeyInjector:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.events: list[dict[str, Any]] = []
        self.quartz: Any = None
        self.accessibility: Any = None
        if not dry_run:
            try:
                import Quartz
                self.quartz = Quartz
                try:
                    import ApplicationServices
                    self.accessibility = ApplicationServices
                except ImportError:
                    # Compatibility with PyObjC releases that re-exported AX
                    # trust functions from Quartz.
                    self.accessibility = Quartz
            except ImportError:
                LOG.error("PyObjC is unavailable; install the bridge requirements")

    def check_accessibility(self, prompt: bool = True) -> bool:
        if self.dry_run:
            return True
        if self.accessibility is None:
            return False
        accessibility = self.accessibility
        try:
            options = {accessibility.kAXTrustedCheckOptionPrompt: prompt}
            trusted = bool(accessibility.AXIsProcessTrustedWithOptions(options))
        except (AttributeError, TypeError):
            try:
                trusted = bool(accessibility.AXIsProcessTrusted())
            except AttributeError:
                LOG.error("Accessibility trust API is unavailable in this PyObjC installation")
                return False
        if not trusted and prompt:
            LOG.error(
                "Accessibility permission is required: System Settings > Privacy & Security > Accessibility"
            )
        return trusted

    def inject(self, key: str, action: str, modifiers: list[str]) -> bool:
        key = key.lower() if len(key) == 1 and key.isalpha() else key
        if action not in {"down", "up"} or key not in KEY_CODES:
            LOG.warning("ignored invalid key event: key=%r action=%r", key, action)
            return False
        event_record = {"k": key, "a": action, "m": list(modifiers)}
        self.events.append(event_record)
        if self.dry_run:
            LOG.info("key %s %s modifiers=%s", key, action, modifiers)
            return True
        if self.quartz is None:
            return False

        q = self.quartz
        event = q.CGEventCreateKeyboardEvent(None, KEY_CODES[key], action == "down")
        flags = 0
        flag_names = {
            "cmd": q.kCGEventFlagMaskCommand,
            "shift": q.kCGEventFlagMaskShift,
            "alt": q.kCGEventFlagMaskAlternate,
            "ctrl": q.kCGEventFlagMaskControl,
        }
        for modifier in modifiers:
            flags |= flag_names.get(modifier, 0)
        q.CGEventSetFlags(event, flags)
        q.CGEventPost(q.kCGHIDEventTap, event)
        return True
