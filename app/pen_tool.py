"""Freehand pen tool."""

import logging

from .annotations import PenStroke
from .drawing import ToolBase

log = logging.getLogger(__name__)

MIN_POINT_DISTANCE = 2.0  # logical px between recorded points


class PenTool(ToolBase):
    """Draws smooth freehand strokes directly into the shared store so they
    appear live while dragging."""

    def __init__(self, controller):
        super().__init__(controller)
        self.current = None      # PenStroke being drawn, or None
        self._last = None        # last accepted point

    # ------------------------------------------------------------------ pen
    def _new_stroke(self):
        pen_cfg = self.controller.settings.section("pen")
        return PenStroke(
            color=pen_cfg.get("color", "#FF3B30"),
            width=pen_cfg.get("width", 4),
            opacity=pen_cfg.get("opacity", 1.0),
        )

    # ------------------------------------------------------------- handlers
    def on_press(self, gx, gy):
        self.controller.clear_selection()
        self.current = self._new_stroke()
        self.current.add_point(gx, gy)
        self.controller.store.add(self.current)   # live render while drawing
        self._last = (gx, gy)
        self.controller.refresh(self.current.bbox())

    def on_move(self, gx, gy):
        if self.current is None:
            return
        lx, ly = self._last
        dist = ((gx - lx) ** 2 + (gy - ly) ** 2) ** 0.5
        if dist < MIN_POINT_DISTANCE:
            return
        before = self.current.bbox()
        self.current.add_point(gx, gy)
        self._last = (gx, gy)
        dirty = (
            min(before[0], gx), min(before[1], gy),
            max(before[2], gx), max(before[3], gy),
        )
        self.controller.refresh(dirty)

    def on_release(self, gx, gy):
        if self.current is None:
            return
        stroke = self.current
        self.current = None
        if (gx, gy) != self._last:
            stroke.add_point(gx, gy)
        self.controller.history.push_add(stroke)
        self.controller.refresh(stroke.bbox())
        log.debug("Pen stroke committed (%d points)", len(stroke.points))

    # -------------------------------------------------------------- cleanup
    def cancel_live(self):
        """Drop an in-progress stroke without adding it to history."""
        if self.current is not None:
            self.controller.store.remove(self.current)
            region = self.current.bbox()
            self.current = None
            self.controller.refresh(region)

    def on_deactivate(self):
        self.cancel_live()
        super().on_deactivate()
