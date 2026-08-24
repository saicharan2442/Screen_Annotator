"""Annotation object model: pen strokes, rectangles and text.

All coordinates are *global logical* (device-independent) pixels across the
whole virtual desktop, so a single AnnotationStore can be rendered by one
overlay widget per monitor.
"""

import time
import uuid

from .utils import dist_to_segment, inflate, rects_intersect


class BaseAnnotation:
    """Common behaviour shared by every annotation type."""

    kind = "base"

    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.created_at = time.time()
        self._bbox = None  # lazily computed cache

    # -- interface ---------------------------------------------------------
    def invalidate(self):
        self._bbox = None

    def bbox(self):
        """Return (l, t, r, b) in global logical coordinates."""
        if self._bbox is None:
            self._bbox = self.compute_bbox()
        return self._bbox

    def compute_bbox(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def translate(self, dx, dy):
        raise NotImplementedError

    def hit_test(self, x, y, tol=6.0):
        raise NotImplementedError

    def intersects(self, rect):
        return rects_intersect(self.bbox(), rect)

    def contains_point(self, x, y, pad=0.0):
        l, t, r, b = inflate(self.bbox(), pad)
        return l <= x <= r and t <= y <= b


class PenStroke(BaseAnnotation):
    kind = "pen"

    def __init__(self, color, width, opacity, points=None):
        super().__init__()
        self.points = list(points or [])  # [(x, y), ...] logical coords
        self.color = color
        self.width = float(width)
        self.opacity = float(opacity)

    # -- geometry ----------------------------------------------------------
    def add_point(self, x, y):
        self.points.append((x, y))
        self.invalidate()

    def compute_bbox(self):
        if not self.points:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return inflate(
            (min(xs), min(ys), max(xs), max(ys)), self.width / 2.0 + 1
        )

    def translate(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]
        self.invalidate()

    def hit_test(self, x, y, tol=6.0):
        limit = self.width / 2.0 + tol
        pts = self.points
        if len(pts) == 1:
            px, py = pts[0]
            return (px - x) ** 2 + (py - y) ** 2 <= limit * limit
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            if dist_to_segment(x, y, x1, y1, x2, y2) <= limit:
                return True
        return False


class RectangleAnnotation(BaseAnnotation):
    kind = "rect"

    def __init__(self, x, y, w, h, color, border_width, opacity, filled=False,
                 fill_opacity=0.18):
        super().__init__()
        self.x, self.y, self.w, self.h = float(x), float(y), float(w), float(h)
        self.color = color
        self.border_width = float(border_width)
        self.opacity = float(opacity)
        self.filled = bool(filled)
        self.fill_opacity = float(fill_opacity)

    def normalized(self):
        """Return (l, t, w, h) with positive extents."""
        left = self.x if self.w >= 0 else self.x + self.w
        top = self.y if self.h >= 0 else self.y + self.h
        return left, top, abs(self.w), abs(self.h)

    def compute_bbox(self):
        l, t, w, h = self.normalized()
        return inflate((l, t, l + w, t + h), self.border_width / 2.0 + 1)

    def translate(self, dx, dy):
        self.x += dx
        self.y += dy
        self.invalidate()

    def hit_test(self, x, y, tol=6.0):
        l, t, w, h = self.normalized()
        bw = max(self.border_width / 2.0, 2.0) + tol
        near_left = abs(x - l) <= bw and t - tol <= y <= t + h + tol
        near_right = abs(x - (l + w)) <= bw and t - tol <= y <= t + h + tol
        near_top = abs(y - t) <= bw and l - tol <= x <= l + w + tol
        near_bottom = abs(y - (t + h)) <= bw and l - tol <= x <= l + w + tol
        inside = l <= x <= l + w and t <= y <= t + h
        if self.filled:
            return inside or near_left or near_right or near_top or near_bottom
        return near_left or near_right or near_top or near_bottom


class TextAnnotation(BaseAnnotation):
    kind = "text"

    def __init__(self, x, y, text="", font_family="Segoe UI", size=28,
                 bold=True, color="#FFFFFF", opacity=1.0):
        super().__init__()
        self.x, self.y = float(x), float(y)   # top-left of the text block
        self.text = str(text)                  # may contain '\n'
        self.font_family = font_family
        self.size = int(size)
        self.bold = bool(bold)
        self.color = color
        self.opacity = float(opacity)

    # Metrics are provided by drawing.text_metrics(); bbox is injected there.
    def set_bbox_cache(self, rect):
        self._bbox = rect

    def compute_bbox(self):
        # Fallback used before Qt metrics are available; drawing.py refreshes it.
        lines = self.text.split("\n") or [""]
        est_w = max(len(line) for line in lines) * self.size * 0.55
        est_h = len(lines) * self.size * 1.35
        return (self.x, self.y, self.x + est_w, self.y + est_h)

    def translate(self, dx, dy):
        self.x += dx
        self.y += dy
        self.invalidate()

    def hit_test(self, x, y, tol=6.0):
        return self.contains_point(x, y, pad=tol)


class LineAnnotation(BaseAnnotation):
    kind = "line"

    def __init__(self, x1, y1, x2, y2, color, width, opacity, arrow=False):
        super().__init__()
        self.x1, self.y1 = float(x1), float(y1)
        self.x2, self.y2 = float(x2), float(y2)
        self.color = color
        self.width = float(width)
        self.opacity = float(opacity)
        self.arrow = bool(arrow)
        if self.arrow:
            self.kind = "arrow"

    def compute_bbox(self):
        l = min(self.x1, self.x2)
        t = min(self.y1, self.y2)
        r = max(self.x1, self.x2)
        b = max(self.y1, self.y2)
        pad = self.width / 2.0 + (self.width * 3 if self.arrow else 1)
        return inflate((l, t, r, b), pad)

    def translate(self, dx, dy):
        self.x1 += dx
        self.y1 += dy
        self.x2 += dx
        self.y2 += dy
        self.invalidate()

    def hit_test(self, x, y, tol=6.0):
        limit = self.width / 2.0 + tol
        return dist_to_segment(x, y, self.x1, self.y1, self.x2, self.y2) <= limit


class AnnotationStore:
    """Ordered collection of annotations (bottom -> top z-order)."""

    def __init__(self):
        self.items = []
        self.selected_id = None

    def add(self, ann):
        self.items.append(ann)
        return ann

    def remove(self, ann):
        try:
            index = self.items.index(ann)
            self.items.pop(index)
            if self.selected_id == ann.id:
                self.selected_id = None
            return index
        except ValueError:
            return None

    def insert(self, index, ann):
        self.items.insert(max(0, min(index, len(self.items))), ann)

    def clear(self):
        self.items.clear()
        self.selected_id = None

    def find(self, ann_id):
        for ann in self.items:
            if ann.id == ann_id:
                return ann
        return None

    def hit_topmost(self, x, y, tol=6.0):
        """Return the top-most annotation under the point, or None."""
        for ann in reversed(self.items):
            if ann.hit_test(x, y, tol):
                return ann
        return None

    def selected(self):
        return self.find(self.selected_id) if self.selected_id else None
