"""Line and arrow drawing tools."""

import logging

from .annotations import LineAnnotation
from .drawing import ToolBase

log = logging.getLogger(__name__)

MIN_SIZE = 4.0


class LineTool(ToolBase):
    _arrow = False
    _config_key = "line"

    def __init__(self, controller):
        super().__init__(controller)
        self._anchor = None

    def _new_line(self, gx, gy):
        cfg = self.controller.settings.section(self._config_key)
        return LineAnnotation(
            x1=gx, y1=gy, x2=gx, y2=gy,
            color=cfg.get("color", "#32ADE6"),
            width=cfg.get("width", 4),
            opacity=cfg.get("opacity", 1.0),
            arrow=self._arrow,
        )

    # ------------------------------------------------------------- handlers
    def on_press(self, gx, gy):
        self.controller.clear_selection()
        self._anchor = (gx, gy)
        self.preview = self._new_line(gx, gy)
        self.controller.refresh((gx - 8, gy - 8, gx + 8, gy + 8))

    def on_move(self, gx, gy):
        if self.preview is None:
            return
        before = self.preview.bbox()
        self.preview.x2, self.preview.y2 = gx, gy
        self.preview.invalidate()
        dirty = (
            min(before[0], self.preview.x1, self.preview.x2) - 30,
            min(before[1], self.preview.y1, self.preview.y2) - 30,
            max(before[2], self.preview.x1, self.preview.x2) + 30,
            max(before[3], self.preview.y1, self.preview.y2) + 30,
        )
        self.controller.refresh(dirty)

    def on_release(self, gx, gy):
        if self.preview is None:
            return
        line = self.preview
        self.preview = None
        self._anchor = None
        
        dx = line.x2 - line.x1
        dy = line.y2 - line.y1
        length_sq = dx*dx + dy*dy
        
        if length_sq < MIN_SIZE * MIN_SIZE:
            # Treat as a click: no accidental tiny lines.
            self.controller.refresh()
            return
            
        self.controller.store.add(line)
        self.controller.history.push_add(line)
        self.controller.refresh(line.bbox())
        log.debug("%s committed", "Arrow" if self._arrow else "Line")

    def on_deactivate(self):
        self.preview = None
        self._anchor = None
        super().on_deactivate()


class ArrowTool(LineTool):
    _arrow = True
    _config_key = "arrow"
