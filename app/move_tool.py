"""Select / move tool ('V'): click an object to select, drag to move,
Delete key removes the selection."""

import logging

from .drawing import ToolBase

log = logging.getLogger(__name__)


class MoveTool(ToolBase):
    def __init__(self, controller):
        super().__init__(controller)
        self._dragging_ann = None
        self._last = None
        self._total = None

    def on_press(self, gx, gy):
        controller = self.controller
        ann = controller.store.hit_topmost(gx, gy, tol=6)
        if ann is None:
            controller.clear_selection()
            return
        controller.store.selected_id = ann.id
        self._dragging_ann = ann
        self._last = (gx, gy)
        self._total = [0.0, 0.0]
        controller.refresh(ann.bbox())

    def on_move(self, gx, gy):
        if self._dragging_ann is None or self._last is None:
            return
        dx, dy = gx - self._last[0], gy - self._last[1]
        self._last = (gx, gy)
        self._total[0] += dx
        self._total[1] += dy
        self._dragging_ann.translate(dx, dy)
        self.controller.refresh()

    def on_release(self, gx, gy):
        ann = self._dragging_ann
        self._dragging_ann = None
        self._last = None
        if ann is None or self._total is None:
            return
        dx, dy = self._total
        self._total = None
        if abs(dx) > 0.5 or abs(dy) > 0.5:
            self.controller.history.push_move(ann, dx, dy)
            log.debug("Moved %s by (%.0f, %.0f)", ann.kind, dx, dy)
        self.controller.refresh(ann.bbox())

    def on_deactivate(self):
        self._dragging_ann = None
        self._last = None
        super().on_deactivate()
