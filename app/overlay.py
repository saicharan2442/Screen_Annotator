"""Transparent, borderless, always-on-top overlay window (one per monitor).

The window is created with WS_EX_NOACTIVATE so it can never steal keyboard
focus from the application underneath.  Mouse input is received normally
while the overlay is visible; when hidden the underlying apps are untouched.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from . import windows_api
from .drawing import draw_caret, draw_eraser_cursor, render_annotation
from .utils import rects_intersect

log = logging.getLogger(__name__)


class OverlayWidget(QWidget):
    """Full-screen annotation surface bound to one QScreen."""

    def __init__(self, screen, controller):
        super().__init__(
            None,
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool,
        )
        self.controller = controller
        self.setScreen(screen)
        self._screen_offset = screen.geometry().topLeft()

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)   # eraser ring follows hover moves
        self.setCursor(Qt.CrossCursor)

        geometry = screen.geometry()
        self.setGeometry(geometry)

    # ------------------------------------------------------------ lifecycle
    def sync_screen(self):
        """Re-apply geometry after monitor changes."""
        screen = self.screen()
        if screen is None:
            return
        self._screen_offset = screen.geometry().topLeft()
        self.setGeometry(screen.geometry())

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            windows_api.make_noactivate(hwnd)
            windows_api.ensure_topmost(hwnd)
        except Exception as exc:
            log.error("Overlay native styling failed: %s", exc)

    def raise_and_topmost(self):
        try:
            hwnd = int(self.winId())
            windows_api.ensure_topmost(hwnd)
        except Exception:
            pass

    # -------------------------------------------------------------- painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Layered windows hit-test per-pixel: fully transparent pixels let
        # clicks fall through to apps underneath. Paint an invisible
        # 1-alpha base over the whole exposed area so the overlay itself
        # receives mouse input everywhere while staying see-through.
        painter.fillRect(event.rect(), QColor(0, 0, 0, 1))

        store = self.controller.store
        tool = self.controller.active_tool()

        # Global-coordinate dirty rect of this repaint.
        er = event.rect()
        ox, oy = self._screen_offset.x(), self._screen_offset.y()
        exposed = (er.x() + ox, er.y() + oy,
                   er.x() + er.width() + ox, er.y() + er.height() + oy)

        painter.translate(-self._screen_offset)

        selected_id = store.selected_id
        for ann in store.items:
            if ann.intersects(exposed):
                render_annotation(painter, ann, selected=(ann.id == selected_id))

        preview = getattr(tool, "preview", None)
        if preview is not None and preview.intersects(exposed):
            render_annotation(painter, preview)

        # Eraser cursor ring.
        if self.controller.tool_name == "eraser":
            eraser = tool
            if eraser.cursor_pos:
                cx, cy = eraser.cursor_pos
                pad = eraser.radius + 4
                if rects_intersect((cx - pad, cy - pad, cx + pad, cy + pad),
                                   exposed):
                    draw_eraser_cursor(painter, cx, cy, eraser.radius)

        # Text caret.
        session = self.controller.text_session()
        if session is not None and session.caret_visible:
            region = session.caret_region()
            if region and rects_intersect(region, exposed):
                x1, y1, x2, y2 = region
                draw_caret(painter, x1 + 1, y1, y2 - y1, True,
                           session.ann.color)

        painter.end()

    # ----------------------------------------------------------- mouse input
    def _to_global(self, event):
        pos = event.position()
        return (pos.x() + self._screen_offset.x(),
                pos.y() + self._screen_offset.y())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.accept()
            return
        gx, gy = self._to_global(event)
        self.controller.overlay_pressed(gx, gy)
        event.accept()

    def mouseMoveEvent(self, event):
        gx, gy = self._to_global(event)
        self.controller.overlay_moved(gx, gy)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.accept()
            return
        gx, gy = self._to_global(event)
        self.controller.overlay_released(gx, gy)
        event.accept()

    def wheelEvent(self, event):
        """Wheel adjusts the size of the active tool (documented shortcut)."""
        delta = 1 if event.angleDelta().y() > 0 else -1
        self.controller.adjust_size(delta)
        event.accept()

    # --------------------------------------------------------------- updates
    def refresh_region(self, region=None):
        """Schedule a repaint of a global logical rect (or everything)."""
        if region is None or self.isHidden():
            self.update()
            return
        l, t, r, b = region
        local_l = max(0, l - self._screen_offset.x())
        local_t = max(0, t - self._screen_offset.y())
        local_r = min(self.width(), r - self._screen_offset.x())
        local_b = min(self.height(), b - self._screen_offset.y())
        if local_r <= local_l or local_b <= local_t:
            return  # Dirty rect does not touch this monitor.
        self.update(int(local_l), int(local_t),
                    int(local_r - local_l) + 1, int(local_b - local_t) + 1)
