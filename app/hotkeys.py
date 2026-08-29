"""Global hotkey management via RegisterHotKey + Qt native event filter.

Two groups of hotkeys are maintained:

* GLOBAL  - activate / deactivate / toolbar toggle: always registered so the
            application can be controlled from anywhere in Windows.
* MODE    - single-key shortcuts (P, B, T, E, ...) that only exist while
            annotation mode is active.  They are registered on activation and
            unregistered when annotation mode ends (and while text is being
            typed) so normal Windows usage is never affected.
"""

import ctypes
import ctypes.wintypes as wt
import logging

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from . import windows_api as api

log = logging.getLogger(__name__)

# Virtual-key codes for the mode shortcuts.
_VK = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "[": api.VK_OEM_4, "]": api.VK_OEM_6,
}

_VK_NAMED = {
    "delete": 0x2E, "del": 0x2E, "backspace": 0x08, "tab": 0x09,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pgdn": 0x22, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28,
}

_MOD_NAMES = {
    "ctrl": api.MOD_CONTROL,
    "control": api.MOD_CONTROL,
    "shift": api.MOD_SHIFT,
    "alt": api.MOD_ALT,
    "win": api.MOD_WIN,
    "windows": api.MOD_WIN,
}


def parse_combo(text):
    """Parse 'ctrl+shift+a' into (modifiers, virtual_key). None if invalid."""
    parts = [p.strip().lower() for p in str(text).split("+") if p.strip()]
    mods = 0
    vk = None
    for part in parts:
        if part in _MOD_NAMES:
            mods |= _MOD_NAMES[part]
        elif part in _VK:
            vk = _VK[part]
        elif part in _VK_NAMED:
            vk = _VK_NAMED[part]
        elif len(part) == 2 and part[0] == "f" and part[1:].isdigit():
            fnum = int(part[1:])
            if 1 <= fnum <= 24:
                vk = 0x70 + (fnum - 1)   # VK_F1 .. VK_F24
        else:
            log.warning("Unknown key '%s' in combo '%s'", part, text)
            return None
    if vk is None:
        log.warning("Combo '%s' has no main key", text)
        return None
    return mods, vk


# Mode shortcut name -> (default combo, description).  Registered only while
# the overlay is active and no text session is running.
MODE_KEYS = {
    "tool_pen": ("p", "Pen tool"),
    "tool_box": ("b", "Box tool"),
    "tool_text": ("t", "Text tool"),
    "tool_speech": ("s", "Speech-to-text tool"),
    "tool_line": ("l", "Line tool"),
    "tool_arrow": ("a", "Arrow tool"),
    "tool_eraser": ("e", "Eraser tool"),
    "tool_move": ("v", "Select / move"),
    "clear_all": ("c", "Clear all annotations"),
    "cycle_color": ("x", "Cycle colour for active tool"),
    "size_up": ("]", "Increase size"),
    "size_down": ("[", "Decrease size"),
    "undo": ("ctrl+z", "Undo"),
    "redo": ("ctrl+y", "Redo"),
    "delete_selected": ("delete", "Delete selected object"),
}


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """Forwards WM_HOTKEY messages posted to the GUI thread."""

    def __init__(self, dispatch):
        super().__init__()
        self._dispatch = dispatch

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            try:
                msg = wt.MSG.from_address(int(message))
                if msg.message == api.WM_HOTKEY:
                    self._dispatch(int(msg.wParam))
                    return True, 0   # Consumed - never reaches other apps.
            except Exception as exc:
                log.error("Hotkey filter error: %s", exc)
        return False, 0


class HotkeyManager(QObject):
    triggered = Signal(str)  # action name

    _next_id = 0xF001  # arbitrary private range unlikely to clash

    def __init__(self):
        super().__init__()
        self._registered = {}   # id -> (group, name)
        self._by_name = {}      # name -> id
        self._filter = _HotkeyEventFilter(self._dispatch)
        self._installed = False

    # ------------------------------------------------------------- plumbing
    def install_filter(self, app):
        if not self._installed:
            app.installNativeEventFilter(self._filter)
            self._installed = True
            log.info("Native hotkey event filter installed")

    def _dispatch(self, hotkey_id):
        entry = self._registered.get(hotkey_id)
        if entry:
            self.triggered.emit(entry[1])

    # ------------------------------------------------------------ registers
    def register_combo(self, group, name, combo_text):
        """Register one hotkey. Returns True on success."""
        self.unregister_name(name)
        parsed = parse_combo(combo_text)
        if parsed is None:
            return False
        mods, vk = parsed
        hotkey_id = HotkeyManager._next_id
        HotkeyManager._next_id += 1
        if api.register_hotkey(hotkey_id, mods, vk):
            self._registered[hotkey_id] = (group, name)
            self._by_name[name] = hotkey_id
            return True
        return False

    def unregister_name(self, name):
        hotkey_id = self._by_name.pop(name, None)
        if hotkey_id is not None:
            api.unregister_hotkey(hotkey_id)
            self._registered.pop(hotkey_id, None)

    def clear_group(self, group):
        dead_ids = [
            hid for hid, (grp, _) in self._registered.items() if grp == group
        ]
        for hid in dead_ids:
            _, name = self._registered.pop(hid)
            api.unregister_hotkey(hid)
            self._by_name.pop(name, None)

    # --------------------------------------------------------------- groups
    def register_global_group(self, combos):
        """combos: {'activate': 'ctrl+shift+a', ...}"""
        failures = []
        for name, combo in combos.items():
            if not self.register_combo("global", name, combo):
                failures.append(f"{name} ({combo})")
        if failures:
            log.error("Global hotkey registration failed for: %s", ", ".join(failures))
        else:
            log.info("Global hotkeys registered: %s", list(combos.values()))
        return failures

    def register_mode_keys(self):
        log.info("Annotation mode hotkeys enabled")
        for name, (combo, _desc) in MODE_KEYS.items():
            if name == "delete_selected":
                self.register_combo("mode", name, "delete")
            else:
                self.register_combo("mode", name, combo)

    def unregister_mode_keys(self):
        self.clear_group("mode")
        log.info("Annotation mode hotkeys released")

    def shutdown(self):
        self.clear_group("global")
        self.clear_group("mode")
