"""ctypes wrappers around the Windows APIs used by the annotator.

Responsibilities:
  * RegisterHotKey / UnregisterHotKey      (global hotkeys)
  * SetWindowsHookEx(WH_KEYBOARD_LL)       (safe text input capture)
  * Window style helpers                   (NOACTIVATE, TOPMOST)
  * ToUnicode                              (virtual-key -> character)

Everything degrades gracefully: failures are logged and reported via
return values instead of raising, so a missing API never crashes the app.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import sys

log = logging.getLogger(__name__)

if sys.platform != "win32":
    raise ImportError("windows_api requires Windows")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------------------------------------------------------------- constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_HOTKEY = 0x0312

WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x10

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LSHIFT = 0xA0

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_DELETE = 0x2E
VK_OEM_4 = 0xDB  # [
VK_OEM_6 = 0xDD  # ]

ERROR_ALREADY_EXISTS = 183


# ------------------------------------------------------------- window styles
def _last_error_msg():
    return ctypes.FormatError(ctypes.get_last_error())


def make_noactivate(hwnd):
    """Add WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW so clicks never steal focus."""
    try:
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE,
            style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        )
        log.debug("Applied NOACTIVATE style to hwnd=%#x", hwnd)
    except Exception as exc:  # pragma: no cover - defensive
        log.error("make_noactivate failed for hwnd=%#x: %s", hwnd, exc)


def ensure_topmost(hwnd):
    """Re-assert topmost without activation."""
    try:
        _user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception as exc:
        log.error("ensure_topmost failed for hwnd=%#x: %s", hwnd, exc)


# ------------------------------------------------------------------ hotkeys
def register_hotkey(hotkey_id, modifiers, vk):
    """Register a global hotkey bound to the calling thread. Returns bool."""
    ok = bool(_user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, vk))
    if not ok:
        log.warning(
            "RegisterHotKey id=%d mods=0x%X vk=0x%X failed: %s",
            hotkey_id, modifiers, vk, _last_error_msg(),
        )
    return ok


def unregister_hotkey(hotkey_id):
    try:
        return bool(_user32.UnregisterHotKey(None, hotkey_id))
    except Exception as exc:
        log.debug("UnregisterHotKey id=%d error: %s", hotkey_id, exc)
        return False


# ------------------------------------------------------------ single instance
def acquire_single_instance(mutex_name="ScreenAnnotatorSingletonMutex"):
    """Return True if this is the only running instance."""
    handle = _kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        log.error("CreateMutexW failed: %s", _last_error_msg())
        return True  # Fail open: better two copies than none.
    if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    # Leak the handle intentionally: it must stay alive for process lifetime.
    return True


# ------------------------------------------------------- low-level keyboard hook
class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR
    ]


class KeyboardHook:
    """Low-level keyboard hook.

    ``handler(vk, scan, is_down)`` is invoked for every physical key event.
    Return ``True`` from the handler to swallow the key so no other
    application ever sees it.  The hook is intentionally installed on the
    calling (GUI) thread; Qt pumps Windows messages so events are delivered.
    """

    def __init__(self, handler):
        self._handler = handler
        self._handle = None
        # Keep an alive reference to the trampoline for the hook's lifetime.
        self._proc = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_int, wt.WPARAM, ctypes.POINTER(_KBDLLHOOKSTRUCT)
        )(self._proc_impl)

    # -- the actual callback executed by Windows ---------------------------
    def _proc_impl(self, n_code, w_param, l_param):
        try:
            if n_code >= 0 and l_param:
                info = l_param[0]
                injected = info.flags & LLKHF_INJECTED
                if not injected:
                    is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    swallow = bool(self._handler(info.vkCode, info.scanCode, is_down))
                    if swallow:
                        return 1
        except Exception as exc:  # Never propagate into Windows' callback.
            log.error("Keyboard hook handler error: %s", exc)
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def start(self):
        if self._handle:
            return True
        self._handle = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, None, 0
        )
        if not self._handle:
            log.error("SetWindowsHookExW failed: %s", _last_error_msg())
            return False
        log.info("Low-level keyboard hook installed")
        return True

    def stop(self):
        if self._handle:
            _user32.UnhookWindowsHookEx(self._handle)
            self._handle = None
            log.info("Low-level keyboard hook removed")


# ------------------------------------------------------------- vk -> char map
def vk_to_char(vk, scan, shift):
    """Translate a virtual key to its character for the active layout."""
    state = (ctypes.c_ubyte * 256)()
    if shift:
        state[VK_SHIFT] = 0x80
        state[VK_LSHIFT] = 0x80
    buf = ctypes.create_unicode_buffer(8)
    n = _user32.ToUnicode(vk, scan, state, buf, len(buf), 0)
    if n > 0:
        return buf[:n]
    return ""


# ------------------------------------------------------------------ helpers
def is_shift_down():
    return bool(_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)


def is_ctrl_down():
    return bool(_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
