"""Rectangle / box tool with live drag preview."""

import logging

from .annotations import RectangleAnnotation
from .drawing import ToolBase

log = logging.getLogger(__name__)

MIN_SIZE = 4.0  # logical px - smaller drags are discarded


class BoxTool(ToolBase):
    def __init__(self, controller):
        super().__init__(controller)
        self._anchor = None

    def _new_rect(self):
        box_cfg = self.controller.settings.section("box")
        return RectangleAnnotation(
            x=0, y=0, w=0, h=0,
            color=box_cfg.get("color", "#FFCC00"),
            border_width=box_cfg.get("border_width", 4),
            opacity=box_cfg.get("opacity", 1.0),
            filled=box_cfg.get("filled", False),
            fill_opacity=box_cfg.get("fill_opacity", 0.18),
        )

    # ------------------------------------------------------------- handlers
    def on_press(self, gx, gy):
        self.controller.clear_selection()
        self._anchor = (gx, gy)
        self.preview = self._new_rect()
        self.preview.x, self.preview.y = gx, gy
        self.controller.refresh((gx - 8, gy - 8, gx + 8, gy + 8))

    def on_move(self, gx, gy):
        if self.preview is None:
            return
        before = self.preview.bbox()
        ax, ay = self._anchor
        self.preview.x, self.preview.y = ax, ay
        self.preview.w, self.preview.h = gx - ax, gy - ay
        self.preview.invalidate()
        dirty = (
            min(before[0], ax, gx) - 10, min(before[1], ay, gy) - 10,
            max(before[2], ax, gx) + 10, max(before[3], ay, gy) + 10,
        )
        self.controller.refresh(dirty)

    def on_release(self, gx, gy):
        if self.preview is None:
            return
        rect = self.preview
        self.preview = None
        self._anchor = None
        _, _, w, h = rect.normalized()
        if w < MIN_SIZE or h < MIN_SIZE:
            # Treat as a click: no accidental tiny boxes.
            self.controller.refresh()
            return
        self.controller.store.add(rect)
        self.controller.history.push_add(rect)
        self.controller.refresh(rect.bbox())
        log.debug("Box committed %sx%s", w, h)

    def on_deactivate(self):
        self.preview = None
        self._anchor = None
        super().on_deactivate()
