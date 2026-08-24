"""Application controller: state machine, overlays, toolbar, hotkeys, tray.

States:
    INACTIVE         background only, no overlay, no mode hotkeys
    ACTIVE           transparent overlay visible, tools available
    TEXT_INPUT       a text session is capturing keystrokes
    TOOLBAR_DRAGGING (informational; tracked by the toolbar widget)
"""

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap, QPen
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu, QSystemTrayIcon

from . import __version__, windows_api
from .box_tool import BoxTool
from .eraser import EraserTool
from .hotkeys import HotkeyManager
from .line_tool import LineTool, ArrowTool
from .move_tool import MoveTool
from .overlay import OverlayWidget
from .pen_tool import PenTool
from .settings import Settings
from .text_tool import TextTool
from .toolbar import ToolbarWidget
from .undo_redo import History

log = logging.getLogger(__name__)

INACTIVE = "INACTIVE"
ACTIVE = "ACTIVE"
TEXT_INPUT = "TEXT_INPUT"
TOOLBAR_DRAGGING = "TOOLBAR_DRAGGING"

TOOL_ORDER = ("pen", "box", "text", "eraser", "move")

# size ranges per tool for the wheel / menu adjustments
SIZE_LIMITS = {
    "pen": (1, 48),
    "box": (1, 24),
    "text": (8, 144),
    "line": (1, 48),
    "arrow": (1, 48),
    "eraser": (4, 80),
}


class ApplicationController(QObject):
    state_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.state = INACTIVE
        self.tool_name = "pen"
        self.mouse_down = False

        from .annotations import AnnotationStore
        self.store = AnnotationStore()
        self.history = History(self.store, on_change=self.refresh)

        # Tools ------------------------------------------------------------
        self.pen_tool = PenTool(self)
        self.box_tool = BoxTool(self)
        self.text_tool = TextTool(self)
        self.line_tool = LineTool(self)
        self.arrow_tool = ArrowTool(self)
        self.eraser_tool = EraserTool(self)
        self.move_tool = MoveTool(self)
        self.tools = {
            "pen": self.pen_tool,
            "box": self.box_tool,
            "text": self.text_tool,
            "line": self.line_tool,
            "arrow": self.arrow_tool,
            "eraser": self.eraser_tool,
            "move": self.move_tool,
        }

        # Windows / widgets -------------------------------------------------
        self.hotkeys = HotkeyManager()
        self.overlays = []
        self.toolbar = ToolbarWidget(self)

        self._build_overlays()
        self._connect_screen_signals()

        app = QApplication.instance()
        self.hotkeys.install_filter(app)
        failures = self.hotkeys.register_global_group(
            self.settings.section("hotkeys")
        )
        self.hotkeys.triggered.connect(self._on_hotkey)

        self.tray = self._build_tray(failures)

        log.info("Screen Annotator v%s started (%d screen(s))", __version__,
                 len(QApplication.screens()))
        if failures:
            self._notify("Hotkey conflict",
                         "Some shortcuts are already used:\n" + "\n".join(failures))

    # ================================================================ screens
    def _build_overlays(self):
        for overlay in self.overlays:
            overlay.deleteLater()
        self.overlays = [
            OverlayWidget(screen, self) for screen in QApplication.screens()
        ]
        log.debug("Overlays built for %d screen(s)", len(self.overlays))

    def _connect_screen_signals(self):
        gui = QApplication.instance()
        gui.screenAdded.connect(lambda _s: self._on_screens_changed())
        try:
            gui.primaryScreenChanged.connect(lambda _s: self._on_screens_changed())
        except AttributeError:
            pass

    def _on_screens_changed(self):
        was_active = self.state != INACTIVE
        if was_active:
            self._hide_overlays()
        self._build_overlays()
        if was_active:
            self._show_overlays()
        log.info("Monitor configuration changed; overlays rebuilt")

    def primary_screen_geometry(self):
        return QApplication.primaryScreen().geometry()

    def screen_at(self, point):
        for screen in QApplication.screens():
            if screen.geometry().contains(point):
                return screen
        return QApplication.primaryScreen()

    # ================================================================== tray
    def _make_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#1E1E20"))
        painter.setPen(QPen(QColor("#32ADE6"), 3))
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QPen(QColor("#FF3B30"), 6))
        painter.drawPath(_pen_glyph_path())
        painter.end()
        return QIcon(pixmap)



    def _build_tray(self, hotkey_failures=None):
        tray = QSystemTrayIcon(self._make_icon())
        tray.setToolTip("Screen Annotator - Ctrl+Shift+A to annotate")
        menu = QMenu()

        act_toggle = QAction("Annotate now  (Ctrl+Shift+A)", menu)
        act_toggle.triggered.connect(self.toggle_annotate)

        act_toolbar = QAction("Show / hide toolbar  (Ctrl+Shift+T)", menu)
        act_toolbar.triggered.connect(self.toggle_toolbar_pref)

        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.request_quit)

        menu.addAction(act_toggle)
        menu.addAction(act_toolbar)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)

        message = None
        if hotkey_failures:
            message = ("Shortcut conflict: " + ", ".join(hotkey_failures))
        tray.show()
        if message:
            tray.showMessage("Screen Annotator", message,
                             QSystemTrayIcon.Warning, 6000)
        else:
            tray.showMessage(
                "Screen Annotator",
                "Running in the background.\nCtrl+Shift+A to start annotating.",
                QSystemTrayIcon.Information, 4000,
            )
        return tray

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:      # left click
            self.toggle_annotate()

    def request_quit(self):
        log.info("Quit requested")
        try:
            self.deactivate()
            self.hotkeys.shutdown()
        except Exception as exc:
            log.error("Error during shutdown: %s", exc)
        self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _notify(self, title, text):
        self.tray.showMessage(title, text, QSystemTrayIcon.Warning, 5000)

    # ============================================================ state flow
    def toggle_annotate(self):
        if self.state == INACTIVE:
            self.activate()
        else:
            self.deactivate()

    def activate(self):
        if self.state != INACTIVE:
            return
        log.info("Annotation mode ACTIVATED")
        self.store.clear()
        self.history.clear()
        self._show_overlays()
        self.hotkeys.register_mode_keys()
        self.set_tool("pen", force=True)   # always start with a fresh pen
        if bool(self.settings.section("toolbar").get("visible", True)):
            self.toolbar.restore_position()
            self.toolbar.show()
        self.state = ACTIVE
        self.state_changed.emit(self.state)

    def deactivate(self):
        if self.state == INACTIVE:
            return
        log.info("Annotation mode DEACTIVATED - clearing everything")
        # Discard any in-progress text entry and release the keyboard hook.
        try:
            self.text_tool.end_session(commit=False)
        except Exception as exc:
            log.error("Text teardown failed: %s", exc)
        self.hotkeys.unregister_mode_keys()
        for tool in self.tools.values():   # reset live tool state
            try:
                tool.on_deactivate()
            except Exception as exc:
                log.error("Tool teardown failed: %s", exc)
        self.store.clear()          # remove all pen/box/text objects (#4)
        self.history.clear()
        self.toolbar.hide()
        self._hide_overlays()
        self.mouse_down = False
        self.state = INACTIVE
        self.state_changed.emit(self.state)
        self.settings.save()

    # -------------------------------------------------------------- overlays
    def _show_overlays(self):
        for overlay in self.overlays:
            overlay.sync_screen()
            overlay.show()
            overlay.raise_and_topmost()

    def _hide_overlays(self):
        for overlay in self.overlays:
            overlay.hide()

    def refresh(self, region=None):
        """Repaint the dirty *region* (global logical rect) on every monitor."""
        for overlay in self.overlays:
            overlay.refresh_region(region)

    # ================================================================= tools
    def active_tool(self):
        return self.tools[self.tool_name]

    def text_session(self):
        return self.text_tool.session

    def set_tool(self, name, force=False):
        """Switch the active tool (committing any open text session first)."""
        if name not in self.tools:
            log.warning("Unknown tool '%s'", name)
            return
        if name == self.tool_name and not force:
            return
        if self.text_session() is not None:
            self.end_text_input(commit=True)
        old = self.tools[self.tool_name]
        old.on_deactivate()
        self.tool_name = name
        self.tools[name].on_activate()
        self.refresh()
        log.debug("Tool selected: %s", name)

    def clear_selection(self):
        if self.store.selected_id is not None:
            ann = self.store.selected()
            region = ann.bbox() if ann else None
            self.store.selected_id = None
            self.refresh(region)

    def delete_annotation(self, ann):
        self.history.push_remove(ann)
        self.store.remove(ann)
        log.debug("Deleted %s annotation %s", ann.kind, ann.id)

    def delete_selected(self):
        ann = self.store.selected()
        if ann is None:
            return
        region = ann.bbox()
        self.delete_annotation(ann)
        self.refresh(region)

    def clear_all(self, push_history=True):
        if push_history:
            self.history.push_clear()
        self.store.clear()
        self.refresh()
        log.info("Cleared all annotations")

    def undo(self):
        if self.history.undo():
            self._sync_toolbar()

    def redo(self):
        if self.history.redo():
            self._sync_toolbar()

    def _sync_toolbar(self):
        if self.toolbar.isVisible():
            self.toolbar.update()
            if hasattr(self.toolbar, 'raise_and_topmost'):
                self.toolbar.raise_and_topmost()

    # ------------------------------------------------------------ text input
    def begin_text_input(self, gx, gy):
        if self.state not in (ACTIVE, TEXT_INPUT):
            return
        if self.tool_name != "text":
            self.set_tool("text", force=True)
        # Any open session is committed inside begin_session -> end_text_input.
        self.text_tool.begin_session(gx, gy)
        if self.text_session() is not None:
            self.state = TEXT_INPUT
            self.hotkeys.unregister_mode_keys()   # letters must type freely here
            self.state_changed.emit(self.state)
            self._sync_toolbar()

    def end_text_input(self, commit=True):
        session = self.text_session()
        if session is None:
            return
        self.text_tool.end_session(commit)
        if self.state == TEXT_INPUT:
            self.state = ACTIVE
            self.hotkeys.register_mode_keys()
            self.state_changed.emit(self.state)
            self._sync_toolbar()

    # ============================================================== styling
    def _style_section_for_tool(self, tool=None):
        tool = tool or self.tool_name
        mapping = {"pen": "pen", "box": "box", "text": "text",
                   "line": "line", "arrow": "arrow",
                   "eraser": "eraser"}
        section = mapping.get(tool, "pen")
        if tool == "eraser":
            return "eraser"
        return section

    def active_color(self):
        key = {"pen": "pen", "box": "box", "text": "text", "line": "line", "arrow": "arrow"}.get(self.tool_name)
        if key is None:
            key = "pen"
        return self.settings.section(key).get("color", "#FF3B30")

    def set_active_color(self, hex_color=None):
        key = {"pen": "pen", "box": "box", "text": "text", "line": "line", "arrow": "arrow"}.get(self.tool_name)
        if key is None:
            return
        if hex_color is None:
            parent = self.overlays[0] if self.overlays else None
            chosen = QColorDialog.getColor(
                QColor(self.active_color()), parent,
                "Pick annotation colour",
                QColorDialog.DontUseNativeDialog,
            )
            if not chosen.isValid():
                return
            hex_color = chosen.name()
        self.settings.set_and_save(key, "color", hex_color)
        self.refresh()

    def cycle_color(self):
        palette = self.settings.data.get("colors_palette", [])
        if not palette:
            return
        current = self.active_color().lower()
        try:
            index = [c.lower() for c in palette].index(current)
        except ValueError:
            index = -1
        self.set_active_color(palette[(index + 1) % len(palette)])
        self._notify_color()

    def _notify_color(self):
        self.tray.setToolTip(
            f"Colour: {self.active_color()}   Size: {self.active_size_value()}"
        )

    def active_size_key(self):
        return {"pen": "width", "box": "border_width", "text": "size",
                "line": "width", "arrow": "width",
                "eraser": "radius"}.get(self.tool_name, "width")

    def active_size_section(self):
        return self._style_section_for_tool()

    def active_size_value(self):
        section = self.active_size_section()
        return int(self.settings.section(section).get(self.active_size_key(), 4))

    def set_active_size(self, value):
        limits = SIZE_LIMITS.get(self.tool_name, (1, 48))
        value = max(limits[0], min(limits[1], int(value)))
        section = self.active_size_section()
        self.settings.set_and_save(section, self.active_size_key(), value)
        self._notify_color()

    def adjust_size(self, delta):
        self.set_active_size(self.active_size_value() + delta)

    def set_active_opacity(self, value):
        section = self.active_size_section()
        self.settings.set_and_save(section, "opacity", value)
        self.refresh()

    # ============================================================== hotkeys
    def _on_hotkey(self, name):
        handler = {
            "activate": self.activate,
            "deactivate": self.deactivate,
            "toggle_toolbar": self.toggle_toolbar_pref,
            "tool_pen": lambda: self.set_tool("pen"),
            "tool_box": lambda: self.set_tool("box"),
            "tool_text": lambda: self.set_tool("text"),
            "tool_line": lambda: self.set_tool("line"),
            "tool_arrow": lambda: self.set_tool("arrow"),
            "tool_eraser": lambda: self.set_tool("eraser"),
            "tool_move": lambda: self.set_tool("move"),
            "clear_all": lambda: self.clear_all(True),
            "cycle_color": self.cycle_color,
            "size_up": lambda: self.adjust_size(1),
            "size_down": lambda: self.adjust_size(-1),
            "undo": self.undo,
            "redo": self.redo,
            "delete_selected": self.delete_selected,
        }
        func = handler.get(name)
        if func is None:
            return
        try:
            func()
        except Exception as exc:
            log.exception("Hotkey '%s' handler failed: %s", name, exc)

    def handle_toolbar_action(self, action):
        if action.startswith("tool_"):
            self.set_tool(action[len("tool_"):])
            self._sync_toolbar()
        elif action == "undo":
            self.undo()
            self._sync_toolbar()
        elif action == "redo":
            self.redo()
            self._sync_toolbar()
        elif action == "clear_all":
            self.clear_all(True)
        elif action == "close":
            self.deactivate()

    def toggle_toolbar_pref(self):
        """Ctrl+Shift+T: toggle toolbar now (or remember choice when inactive)."""
        section = self.settings.section("toolbar")
        visible = not bool(section.get("visible", True))
        section["visible"] = visible
        self.settings.save()
        if self.state != INACTIVE:
            if visible:
                self.toolbar.restore_position()
                self.toolbar.show()
            else:
                if self.toolbar.isVisible():
                    self.toolbar.save_position()
                self.toolbar.hide()
        log.info("Toolbar visibility -> %s", visible)

    # ------------------------------------------------------- overlay events
    def overlay_pressed(self, gx, gy):
        self.mouse_down = True
        self.active_tool().on_press(gx, gy)

    def overlay_moved(self, gx, gy):
        self.active_tool().on_move(gx, gy)

    def overlay_released(self, gx, gy):
        self.mouse_down = False
        self.active_tool().on_release(gx, gy)
        self._sync_toolbar()


def _pen_glyph_path():
    path = QPainterPath()
    path.moveTo(18, 46)
    path.lineTo(22, 34)
    path.lineTo(42, 14)
    path.lineTo(50, 22)
    path.lineTo(30, 42)
    path.lineTo(18, 46)
    return path
def _pen_glyph_path():
    path = QPainterPath()
    path.moveTo(18, 46)
    path.lineTo(22, 34)
    path.lineTo(42, 14)
    path.lineTo(50, 22)
    path.lineTo(30, 42)
    path.lineTo(18, 46)
    return path
