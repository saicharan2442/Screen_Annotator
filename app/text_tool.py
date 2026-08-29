"""Text tool: click-to-place text with fully captured keyboard input.

While a text session is active a low-level keyboard hook swallows every
keystroke, so typed characters can never reach the underlying application
(Terminal, VS Code, browser ...).  The overlay window itself never takes
focus (WS_EX_NOACTIVATE), which is why the hook is needed at all.

Keys during text entry:
    printable keys   insert character
    Enter            newline
    Ctrl+Enter       commit
    Backspace        delete previous character
    Ctrl+V           paste clipboard
    Esc              commit
"""

import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontMetricsF

from .annotations import TextAnnotation
from .drawing import refresh_text_bbox, text_font, text_metrics
from . import windows_api

log = logging.getLogger(__name__)


class TextInputSession:
    """Captures keystrokes into one TextAnnotation until committed."""

    def __init__(self, controller, gx, gy):
        self.controller = controller
        cfg = controller.settings.section("text")
        self.ann = TextAnnotation(
            x=gx, y=gy, text="",
            font_family=cfg.get("family", "Segoe UI"),
            size=int(cfg.get("size", 28)),
            bold=bool(cfg.get("bold", True)),
            color=cfg.get("color", "#FFFFFF"),
            opacity=float(cfg.get("opacity", 1.0)),
        )
        self._caret_on = True
        self._shift_down = False
        self._hook = windows_api.KeyboardHook(self._on_key)
        self._caret_timer = QTimer()
        self._caret_timer.timeout.connect(self._blink)

    # -------------------------------------------------------------- control
    def start(self):
        if not self._hook.start():
            log.error("Text input hook failed to start; aborting text entry")
            return False
        refresh_text_bbox(self.ann)
        self._caret_timer.start(500)
        log.info("Text input started at (%.0f, %.0f)", self.ann.x, self.ann.y)
        return True

    def stop_capture(self):
        """Idempotent teardown of hook + caret timer."""
        try:
            self._caret_timer.stop()
        except Exception:
            pass
        try:
            self._hook.stop()
        except Exception as exc:
            log.error("Error stopping text session: %s", exc)

    def commit(self):
        """Finish the session. Returns True if the text should be kept."""
        has_content = bool(self.ann.text.strip())
        self.stop_capture()
        log.info("Text input finished (committed=%s)", has_content)
        return has_content

    # ---------------------------------------------------------------- caret
    def _blink(self):
        self._caret_on = not self._caret_on
        region = self.caret_region()
        if region:
            self.controller.refresh(region)

    @property
    def caret_visible(self):
        return self._caret_on

    def caret_region(self):
        from .drawing import get_caret_info, text_metrics, text_font
        pos = getattr(self, '_cursor_pos', len(self.ann.text))
        cx_offset, line_idx = get_caret_info(self.ann, pos)
        
        _, _, line_h, _ = text_metrics(self.ann)
        fm = QFontMetricsF(text_font(self.ann))
        
        cx = self.ann.x + cx_offset
        y = self.ann.y + line_idx * line_h
        return (cx - 1, y, cx + 3, y + fm.height())

    # ----------------------------------------------------------- key capture
    def _on_key(self, vk, scan, is_down):
        """Low-level hook callback. Return True to swallow the key."""
        if vk == 0x14:  # VK_CAPITAL (Caps Lock)
            return False  # Let Windows handle Caps Lock so its state toggles
            
        if vk in (windows_api.VK_SHIFT, 0xA0, 0xA1):  # 0xA0 is LSHIFT, 0xA1 is RSHIFT
            self._shift_down = is_down
            return True
            
        if not is_down:
            return True  # Swallow all other key-ups while typing.

        ctrl = windows_api.is_ctrl_down()

        if vk == windows_api.VK_ESCAPE:
            self.controller.end_text_input(commit=True)
            return True
        if vk == windows_api.VK_RETURN:
            if ctrl:
                self.controller.end_text_input(commit=True)
            else:
                self._insert("\n")
            return True
        if vk == windows_api.VK_BACK:
            self._backspace()
            return True
            
        # Arrow keys
        if vk == 0x25:  # Left
            if getattr(self, '_cursor_pos', len(self.ann.text)) > 0:
                self._cursor_pos -= 1
                self._dirty()
            return True
        if vk == 0x27:  # Right
            if getattr(self, '_cursor_pos', len(self.ann.text)) < len(self.ann.text):
                self._cursor_pos += 1
                self._dirty()
            return True
        if vk == 0x26:  # Up
            self._move_up()
            return True
        if vk == 0x28:  # Down
            self._move_down()
            return True

        if ctrl and vk == ord("V"):
            self._paste()
            return True
        if vk in (windows_api.VK_SHIFT, windows_api.VK_CONTROL,
                  windows_api.VK_MENU, 0xA2, 0xA3, 0xA4, 0xA5):
            return True  # Bare modifier keys.
        if ctrl:
            return True  # Other Ctrl combos are ignored, never forwarded.

        char = windows_api.vk_to_char(vk, scan, getattr(self, '_shift_down', False))
        if char and all(ord(c) >= 32 for c in char):
            self._insert(char)
        return True  # Everything else is swallowed silently.

    # ------------------------------------------------------------ mutations
    def _dirty(self):
        old = self.ann.bbox()
        refresh_text_bbox(self.ann)
        new = self.ann.bbox()
        self.controller.refresh((
            min(old[0], new[0]) - 4, min(old[1], new[1]) - 4,
            max(old[2], new[2]) + 4, max(old[3], new[3]) + 4,
        ))

    def _insert(self, text):
        pos = getattr(self, '_cursor_pos', len(self.ann.text))
        self.ann.text = self.ann.text[:pos] + text + self.ann.text[pos:]
        self._cursor_pos = pos + len(text)
        self._dirty()

    def _backspace(self):
        pos = getattr(self, '_cursor_pos', len(self.ann.text))
        if pos > 0:
            self.ann.text = self.ann.text[:pos - 1] + self.ann.text[pos:]
            self._cursor_pos = pos - 1
            self._dirty()

    def _move_up(self):
        pos = getattr(self, '_cursor_pos', len(self.ann.text))
        if pos == 0: return
        text = self.ann.text
        line_start = text.rfind('\n', 0, pos) + 1
        col = pos - line_start
        if line_start == 0:
            self._cursor_pos = 0
        else:
            prev_line_start = text.rfind('\n', 0, line_start - 1) + 1
            prev_line_len = (line_start - 1) - prev_line_start
            self._cursor_pos = prev_line_start + min(col, prev_line_len)
        self._dirty()

    def _move_down(self):
        pos = getattr(self, '_cursor_pos', len(self.ann.text))
        text = self.ann.text
        if pos == len(text): return
        line_start = text.rfind('\n', 0, pos) + 1
        col = pos - line_start
        next_line_start = text.find('\n', pos)
        if next_line_start == -1:
            self._cursor_pos = len(text)
        else:
            next_line_start += 1
            next_line_end = text.find('\n', next_line_start)
            if next_line_end == -1: next_line_end = len(text)
            next_line_len = next_line_end - next_line_start
            self._cursor_pos = next_line_start + min(col, next_line_len)
        self._dirty()

    def _paste(self):
        try:
            from PySide6.QtWidgets import QApplication
            text = QApplication.clipboard().text()
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text:
                self._insert(text)
        except Exception as exc:
            log.error("Clipboard paste failed: %s", exc)


class TextTool:
    """Click anywhere on the overlay to place a text annotation."""

    def __init__(self, controller):
        self.controller = controller
        self.session = None

    # ------------------------------------------------------------- sessions
    def begin_session(self, gx, gy):
        if self.session is not None:   # commit the previous one first
            self.controller.end_text_input(commit=True)
        session = TextInputSession(self.controller, gx, gy)
        if not session.start():
            return
        self.session = session
        self.controller.store.add(session.ann)  # render live while typing
        refresh_text_bbox(session.ann)
        self.controller.refresh()

    def end_session(self, commit=True):
        if self.session is None:
            return
        session = self.session
        self.session = None
        keep = session.commit() if commit else False
        if keep:
            self.controller.history.push_add(session.ann)
        else:
            self.controller.store.remove(session.ann)
        self.controller.refresh(session.ann.bbox())

    # --------------------------------------------------------- mouse events
    def on_press(self, gx, gy):
        # A click while typing commits and starts a fresh placement.
        self.controller.begin_text_input(gx, gy)

    def on_move(self, gx, gy):
        pass

    def on_release(self, gx, gy):
        pass

    def on_deactivate(self):
        if self.session is not None:
            self.controller.end_text_input(commit=True)
