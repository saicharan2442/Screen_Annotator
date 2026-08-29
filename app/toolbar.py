"""Compact floating icon toolbar.

* Small icon-only buttons (no text labels).
* Starts on the right edge, draggable anywhere.
* Automatically switches between vertical (near left/right edges) and
  horizontal (near top/bottom) layouts while dragging.
* Position and visibility are persisted in config.json.
"""

import logging

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QIcon, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

log = logging.getLogger(__name__)

BUTTON_SIZE = 34
GAP = 4
PADDING = 6

# action_key -> (unicode glyph, tooltip)
BUTTONS = [
    ("tool_pen", "✎", "Pen (P)"),
    ("tool_box", "□", "Box (B)"),
    ("tool_text", "T", "Text (T)"),
    ("tool_speech", "🎤", "Speech (S)"),
    ("tool_line", "╱", "Line (L)"),
    ("tool_arrow", "↗", "Arrow (A)"),
    ("tool_eraser", "⊕", "Eraser (E)"),
    ("undo", "↶", "Undo (Ctrl+Z)"),
    ("redo", "↷", "Redo (Ctrl+Y)"),
    ("clear_all", "🗑", "Clear all (C)"),
    ("close", "✕", "Close (Ctrl+Shift+Q)"),
]

BG_COLOR = QColor(30, 30, 32, 225)
BORDER_COLOR = QColor(255, 255, 255, 45)
TEXT_COLOR = QColor("#E8E8E8")
ACCENT = QColor("#32ADE6")


class ToolbarWidget(QWidget):
    """Frameless, non-activating tool palette rendered entirely by hand so
    dragging works from anywhere on the bar."""

    def __init__(self, controller):
        super().__init__(
            None,
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.controller = controller
        self.vertical = False
        self._hover_index = -1
        self._pressed_button = -1
        self._press_pos = None
        self._drag_offset = None
        self._dragging = False

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

        self._layout_buttons()

    # --------------------------------------------------------------- layout
    @property
    def orientation(self):
        return "vertical" if self.vertical else "horizontal"

    def _layout_buttons(self):
        n = len(BUTTONS)
        if self.vertical:
            w = PADDING * 2 + BUTTON_SIZE
            h = PADDING * 2 + n * BUTTON_SIZE + (n - 1) * GAP
            self._rects = [
                QRectF(PADDING, PADDING + i * (BUTTON_SIZE + GAP),
                       BUTTON_SIZE, BUTTON_SIZE)
                for i in range(n)
            ]
        else:
            w = PADDING * 2 + n * BUTTON_SIZE + (n - 1) * GAP
            h = PADDING * 2 + BUTTON_SIZE
            self._rects = [
                QRectF(PADDING + i * (BUTTON_SIZE + GAP), PADDING,
                       BUTTON_SIZE, BUTTON_SIZE)
                for i in range(n)
            ]
        self.resize(int(w), int(h))
        self.update()

    def update_orientation_for_position(self):
        """Vertical near the left/right screen edges, horizontal otherwise."""
        cfg = self.controller.settings.section("toolbar")
        threshold = int(cfg.get("edge_threshold", 140))
        center = self.geometry().center()
        screen = self.controller.screen_at(center)
        if screen is None:
            return
        geo = screen.geometry()
        near_left = center.x() - geo.left() <= threshold
        near_right = geo.right() - center.x() <= threshold
        want_vertical = near_left or near_right
        if want_vertical != self.vertical:
            # Keep the same point roughly under the cursor when re-flowing.
            anchor = center
            self.vertical = want_vertical
            self._layout_buttons()
            new_geo = self.geometry()
            self.move(int(anchor.x() - new_geo.width() / 2),
                      int(anchor.y() - new_geo.height() / 2))

    # ------------------------------------------------------------ placement
    def show_on_right_edge(self):
        """First-run position: vertically centred at the right edge."""
        screen = self.controller.primary_screen_geometry()
        self.vertical = True
        self._layout_buttons()
        x = screen.right() - self.width() - 8
        y = screen.top() + (screen.height() - self.height()) // 2
        self.move(x, y)
        self.update_orientation_for_position()

    def restore_position(self):
        cfg = self.controller.settings.section("toolbar")
        x, y = int(cfg.get("x", -1)), int(cfg.get("y", -1))
        if x < 0 or y < 0:
            self.show_on_right_edge()
            return
        self.move(x, y)
        self.update_orientation_for_position()

    def save_position(self):
        pos = self.pos()
        section = self.controller.settings.section("toolbar")
        section["x"], section["y"] = int(pos.x()), int(pos.y())
        section["orientation"] = self.orientation
        self.controller.settings.save()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from . import windows_api
            windows_api.make_noactivate(int(self.winId()))
            windows_api.ensure_topmost(int(self.winId()))
        except Exception as exc:
            log.error("Toolbar native styling failed: %s", exc)

    def raise_and_topmost(self):
        self.raise_()
        try:
            from . import windows_api
            windows_api.ensure_topmost(int(self.winId()))
        except Exception:
            pass

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        bar = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(BG_COLOR)
        painter.drawRoundedRect(bar, 9, 9)

        font = QFont("Segoe UI Symbol", 14)
        painter.setFont(font)

        active_tool = self.controller.tool_name
        for index, (action, glyph, _tip) in enumerate(BUTTONS):
            rect = self._rects[index]
            is_active_tool = action.startswith("tool_") and action == f"tool_{active_tool}"
            disabled = action == "undo" and not self.controller.history.can_undo
            disabled = disabled or (
                action == "redo" and not self.controller.history.can_redo)

            if index == self._hover_index:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 28))
                painter.drawRoundedRect(rect, 7, 7)

            if is_active_tool:
                painter.setPen(QPen(ACCENT, 1.6))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 8, 8)

            color = QColor(TEXT_COLOR)
            if disabled:
                color.setAlpha(90)
            elif is_active_tool:
                color = ACCENT.lighter(130)
            painter.setPen(QPen(color))
            painter.drawText(rect, Qt.AlignCenter, glyph)
        painter.end()

    # ---------------------------------------------------------------- mouse
    def _index_at(self, pos):
        for index, rect in enumerate(self._rects):
            if rect.contains(QPointF(pos)):
                return index
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        self._pressed_button = self._index_at(event.position())
        self._press_pos = event.position()
        self._drag_offset = event.globalPosition().toPoint() - self.pos()
        self._dragging = False

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            moved = (event.position() - self._press_pos).manhattanLength() \
                if self._press_pos else 0
            if not self._dragging and moved > 6:
                self._dragging = True
            if self._dragging:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                self.update_orientation_for_position()
        else:
            index = self._index_at(event.position())
            if index != self._hover_index:
                self._hover_index = index
                self.update()

    def mouseReleaseEvent(self, event):
        was_dragging, self._dragging = self._dragging, False
        pressed, self._pressed_button = self._pressed_button, -1

        if event.button() != Qt.LeftButton:
            return
        if was_dragging or pressed < 0:
            self.save_position()
            return
        index = self._index_at(event.position())
        if index == pressed and index >= 0:
            action = BUTTONS[index][0]
            self.controller.handle_toolbar_action(action)
        else:
            self.save_position()

    def leaveEvent(self, event):
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
        super().leaveEvent(event)

    # --------------------------------------------------------- context menu
    def _show_context_menu(self, global_pos):
        menu = QMenu(self)
        controller = self.controller
        settings = controller.settings

        colors = settings.data.get("colors_palette", [])
        color_menu = menu.addMenu("Colour")
        current = controller.active_color()
        for hex_color in colors:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(hex_color))
            icon = QIcon(pixmap)
            
            label_text = "   "
            if hex_color.lower() == current.lower():
                label_text += "✓"
                
            action = color_menu.addAction(icon, label_text)
            action.setData(f"color:{hex_color}")
        custom = color_menu.addAction("Custom...")
        custom.setData("color:__custom__")

        size_menu = menu.addMenu("Size")
        for label, value in [("Thin", 2), ("Normal", 4), ("Medium", 7),
                             ("Thick", 10), ("Very thick", 16)]:
            act = size_menu.addAction(label)
            act.setData(f"size:{value}")

        opacity_menu = menu.addMenu("Opacity")
        for label, value in [("100%", 1.0), ("75%", 0.75), ("50%", 0.5),
                             ("30%", 0.3)]:
            act = opacity_menu.addAction(label)
            act.setData(f"opacity:{value}")

        fill_action = menu.addAction(
            "Box fill ✓" if settings.section("box").get("filled")
            else "Box fill"
        )
        fill_action.setData("toggle_fill")

        hide_action = menu.addAction("Hide toolbar (Ctrl+Shift+T)")
        hide_action.setData("hide_toolbar")

        chosen = menu.exec(global_pos)
        if chosen is None or chosen.data() is None:
            return
        kind, _, value = chosen.data().partition(":")
        if kind == "color":
            controller.set_active_color(value if value != "__custom__" else None)
        elif kind == "size":
            controller.set_active_size(int(value))
        elif kind == "opacity":
            controller.set_active_opacity(float(value))
        elif kind == "toggle_fill":
            box = settings.section("box")
            box["filled"] = not box.get("filled", False)
            settings.save()
        elif kind == "hide_toolbar":
            controller.toggle_toolbar()
