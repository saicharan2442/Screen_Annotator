"""Rendering of annotation objects with QPainter + shared tool base class."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from .annotations import PenStroke, RectangleAnnotation, TextAnnotation

LINE_HEIGHT_FACTOR = 1.35


def qcolor(hex_color, opacity=1.0):
    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#FF3B30")
    if opacity < 1.0:
        color.setAlphaF(max(0.05, min(1.0, color.alphaF() * opacity)))
    return color


def text_font(ann: TextAnnotation):
    font = QFont(ann.font_family, ann.size)
    font.setBold(ann.bold)
    return font


def text_metrics(ann: TextAnnotation):
    """Return (width, height, line_height, ascent) for the text block."""
    fm = QFontMetricsF(text_font(ann))
    lines = ann.text.split("\n") or [""]
    width = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
    line_h = fm.height() * LINE_HEIGHT_FACTOR
    return width, len(lines) * line_h, line_h, fm.ascent()


def refresh_text_bbox(ann: TextAnnotation):
    w, h, _, _ = text_metrics(ann)
    ann.set_bbox_cache((ann.x - 2, ann.y - 2, ann.x + w + 4, ann.y + h + 4))


def render_annotation(painter: QPainter, ann, selected=False):
    """Draw one annotation. Painter is already translated to global coords."""
    painter.save()
    if isinstance(ann, PenStroke):
        _render_pen(painter, ann)
    elif isinstance(ann, RectangleAnnotation):
        _render_rect(painter, ann)
    elif isinstance(ann, TextAnnotation):
        refresh_text_bbox(ann)
        _render_text(painter, ann)

    if selected:
        l, t, r, b = ann.bbox()
        pen = QPen(QColor("#00E5FF"), 1.5, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(l - 4, t - 4, (r - l) + 8, (b - t) + 8))
    painter.restore()


def _smooth_path(points):
    """Build a quadratic-smoothed path through *points*."""
    path = QPainterPath()
    pts = [QPointF(x, y) for x, y in points]
    path.moveTo(pts[0])
    if len(pts) == 2:
        path.lineTo(pts[1])
        return path
    for i in range(1, len(pts) - 1):
        mid = (pts[i] + pts[i + 1]) / 2.0
        path.quadTo(pts[i], mid)
    path.lineTo(pts[-1])
    return path


def _render_pen(painter, stroke: PenStroke):
    if not stroke.points:
        return
    painter.setOpacity(stroke.opacity)
    pen = QPen(qcolor(stroke.color), stroke.width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    if len(stroke.points) == 1:
        x, y = stroke.points[0]
        painter.drawPoint(QPointF(x, y))
    else:
        painter.drawPath(_smooth_path(stroke.points))


def _render_rect(painter, rect: RectangleAnnotation):
    left, top, w, h = rect.normalized()
    box = QRectF(left, top, w, h)
    if rect.filled and rect.fill_opacity > 0:
        fill = qcolor(rect.color, rect.opacity * rect.fill_opacity)
        painter.fillRect(box, fill)
    painter.setOpacity(rect.opacity)
    pen = QPen(qcolor(rect.color), rect.border_width)
    pen.setJoinStyle(Qt.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(box)


def _render_text(painter, ann: TextAnnotation):
    painter.setOpacity(ann.opacity)
    painter.setFont(text_font(ann))
    painter.setPen(QPen(qcolor(ann.color)))
    _, _, line_h, ascent = text_metrics(ann)
    y = ann.y
    for line in ann.text.split("\n"):
        painter.drawText(QPointF(ann.x, y + ascent), line)
        y += line_h


def draw_caret(painter, x, y, height, on, color="#FFFFFF"):
    """Draw the blinking text caret."""
    if not on:
        return
    painter.setOpacity(0.9)
    painter.setPen(QPen(qcolor(color), 2))
    painter.drawLine(QPointF(x, y), QPointF(x, y + height))


def draw_eraser_cursor(painter, cx, cy, radius):
    ring = QPen(QColor("#FFFFFF"), 1.5)
    painter.setOpacity(0.9)
    painter.setPen(ring)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), radius, radius)


class ToolBase:
    """Shared mouse-event interface implemented by every tool.

    Tools receive global logical coordinates from the overlay widgets.
    """

    def __init__(self, controller):
        self.controller = controller
        self.preview = None  # optional live preview object rendered by overlays

    def on_press(self, gx, gy):   # noqa: D401 - simple hook API
        pass

    def on_move(self, gx, gy):
        pass

    def on_release(self, gx, gy):
        pass

    def on_activate(self):
        self.preview = None

    def on_deactivate(self):
        self.preview = None

    @staticmethod
    def segment_dirty(a, b, pad=20.0):
        """Dirty region covering a moving cursor/segment."""
        if a is None:
            a = b
        return (
            min(a[0], b[0]) - pad, min(a[1], b[1]) - pad,
            max(a[0], b[0]) + pad, max(a[1], b[1]) + pad,
        )
