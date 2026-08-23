"""Eraser tool - deletes whole annotation objects it touches."""

import logging

from .drawing import ToolBase

log = logging.getLogger(__name__)


class EraserTool(ToolBase):
    """Hit-testing eraser: any stroke / rectangle / text under the cursor is
    removed entirely (object-level erase, not pixel erase)."""

    def __init__(self, controller):
        super().__init__(controller)
        self.cursor_pos = None  # rendered as a ring by the overlays

    @property
    def radius(self):
        return float(self.controller.settings.section("eraser").get("radius", 14))

    # ------------------------------------------------------------- handlers
    def _erase_at(self, gx, gy):
        ann = self.controller.store.hit_topmost(gx, gy, tol=self.radius)
        if ann is None:
            return
        region = ann.bbox()
        self.controller.delete_annotation(ann)
        self.controller.refresh(region)

    def on_press(self, gx, gy):
        self.controller.clear_selection()
        self._erase_at(gx, gy)

    def on_move(self, gx, gy):
        previous = self.cursor_pos
        self.cursor_pos = (gx, gy)
        self.controller.refresh(self.segment_dirty(previous, (gx, gy), pad=self.radius + 6))
        if self.controller.mouse_down:
            self._erase_at(gx, gy)

    def ring_dirty(self):
        """Region to repaint when the cursor ring moves/changes."""
        if self.cursor_pos is None:
            return None
        r = self.radius + 4
        cx, cy = self.cursor_pos
        return (cx - r, cy - r, cx + r, cy + r)

    def on_activate(self):
        super().on_activate()

    def on_deactivate(self):
        region = self.ring_dirty()
        self.cursor_pos = None
        if region:
            self.controller.refresh(region)
        super().on_deactivate()
