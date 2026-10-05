"""Opt-in focused HID capture. Enter/Tab terminators, debounce, bounded payload."""

from time import monotonic


class HID:
    def __init__(self, debounce=0.35, timeout=1.0, clock=monotonic):
        self.debounce, self.timeout, self.clock = debounce, timeout, clock
        self.poisoned = False
        self.buffer = ""
        self.last_key = 0.0
        self.last_scan = (None, float("-inf"))

    def reset(self):
        self.poisoned = False
        self.buffer = ""
        self.last_key = 0.0

    def key(self, char="", keysym="", focused=True):
        now = self.clock()
        if not focused:
            self.reset()
            return None
        if keysym in {"Return", "KP_Enter", "Tab"}:
            value = "" if self.poisoned else self.buffer
            self.reset()
            if not value or (value == self.last_scan[0] and now - self.last_scan[1] < self.debounce):
                return None
            self.last_scan = (value, now)
            return value
        if keysym == "Escape":
            self.reset()
            return None
        if keysym == "BackSpace":
            self.buffer = self.buffer[:-1]
            return None
        if not char or self.poisoned:
            return None
        if now - self.last_key > self.timeout:
            self.buffer = ""
        self.last_key = now
        if len(self.buffer) + len(char) > 160 or any(ord(c) < 32 or ord(c) == 127 for c in char):
            self.reset()
            self.poisoned = True
            raise ValueError("Mã HID quá dài hoặc chứa ký tự điều khiển.")
        self.buffer += char
        return None
