"""Rendering of annotation objects with QPainter + shared tool base class."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from .annotations import PenStroke, RectangleAnnotation, TextAnnotation, LineAnnotation

LINE_HEIGHT_FACTOR = 1.15


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


def get_text_max_width(ann: TextAnnotation, pad=20.0):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint
    if not QApplication.instance():
        return 10000.0
    screen = QApplication.screenAt(QPoint(int(ann.x), int(ann.y)))
    if screen:
        geo = screen.geometry()
        return max(50.0, float(geo.right() - ann.x - pad))
    return 10000.0


def wrap_text_lines(ann: TextAnnotation):
    """Returns a list of strings representing the visually wrapped lines."""
    fm = QFontMetricsF(text_font(ann))
    max_w = get_text_max_width(ann)
    
    wrapped = []
    for paragraph in ann.text.split("\n"):
        words = paragraph.split(" ")
        current_line = []
        current_w = 0.0
        
        for i, word in enumerate(words):
            word_w = fm.horizontalAdvance(word + (" " if i < len(words) - 1 else ""))
            if current_w + word_w > max_w and current_line:
                wrapped.append(" ".join(current_line))
                current_line = [word]
                current_w = fm.horizontalAdvance(word + " ")
            else:
                current_line.append(word)
                current_w += word_w
                
        if current_line:
            wrapped.append(" ".join(current_line))
        elif not words or words == [""]:
            wrapped.append("")
            
    if not wrapped:
        wrapped = [""]
    return wrapped


def get_caret_info(ann: TextAnnotation, cursor_pos: int):
    """Returns (cx_offset, line_idx) for the given character index."""
    fm = QFontMetricsF(text_font(ann))
    max_w = get_text_max_width(ann)
    
    line_idx = 0
    current_line = []
    current_w = 0.0
    char_count = 0
    
    for paragraph in ann.text.split("\n"):
        words = paragraph.split(" ")
        for i, word in enumerate(words):
            word_str = word + (" " if i < len(words) - 1 else "")
            word_w = fm.horizontalAdvance(word_str)
            
            if current_w + word_w > max_w and current_line:
                # Wrap occurred. Did our cursor fall in the previous line?
                if cursor_pos <= char_count:
                    # It's somewhere in the current_line.
                    # We just need to figure out its exact X position.
                    pass # We will handle this below by re-evaluating current_line
                else:
                    line_idx += 1
                    current_line = [word_str]
                    current_w = fm.horizontalAdvance(word_str)
            else:
                current_line.append(word_str)
                current_w += word_w
                
            char_count += len(word_str)
            
            if cursor_pos <= char_count:
                # The cursor is inside this word (or at its end).
                # The text before the cursor on this visually wrapped line is:
                # Everything in current_line EXCEPT the current word, PLUS the portion of the word before cursor.
                word_start_idx = char_count - len(word_str)
                chars_in_word = cursor_pos - word_start_idx
                
                text_before = "".join(current_line[:-1]) + word_str[:chars_in_word]
                cx = fm.horizontalAdvance(text_before)
                return cx, line_idx
                
        # End of paragraph newline
        char_count += 1
        if cursor_pos < char_count:
            return fm.horizontalAdvance("".join(current_line)), line_idx
        line_idx += 1
        current_line = []
        current_w = 0.0

    # If cursor is at the very end
    return fm.horizontalAdvance("".join(current_line)), line_idx


def text_metrics(ann: TextAnnotation):
    """Return (width, height, line_height, ascent) for the text block."""
    fm = QFontMetricsF(text_font(ann))
    lines = wrap_text_lines(ann)
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
    elif isinstance(ann, LineAnnotation):
        _render_line(painter, ann)

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
    for line in wrap_text_lines(ann):
        painter.drawText(QPointF(ann.x, y + ascent), line)
        y += line_h


def _render_line(painter, line: LineAnnotation):
    import math
    from PySide6.QtGui import QPolygonF
    from PySide6.QtGui import QPainterPath

    painter.setOpacity(line.opacity)
    p1 = QPointF(line.x1, line.y1)
    p2 = QPointF(line.x2, line.y2)
    
    dx = line.x2 - line.x1
    dy = line.y2 - line.y1
    angle = math.atan2(dy, dx)
    length = math.hypot(dx, dy)
    
    if line.arrow:
        if length < 5:
            return
            
        painter.save()
        painter.translate(p1)
        painter.rotate(math.degrees(angle))
        
        # The exact tapered arrow design from the image
        shaft_wid = line.width * 2.0
        head_wid = max(15.0, line.width * 4.5)
        head_len = max(15.0, line.width * 4.0)
        
        # Prevent head from being longer than the line itself
        if head_len > length:
            head_len = length
            shaft_len = 0
            shaft_wid = 0 # No shaft if it's too short
        else:
            shaft_len = length - head_len
            
        # Define the 6 points of the solid tapered arrow
        points = [
            QPointF(0, 0),                           # Tail sharp point
            QPointF(shaft_len, shaft_wid / 2),       # Top of shaft before head
            QPointF(shaft_len, head_wid / 2),        # Top corner of arrowhead
            QPointF(length, 0),                      # Tip of the arrow
            QPointF(shaft_len, -head_wid / 2),       # Bottom corner of arrowhead
            QPointF(shaft_len, -shaft_wid / 2),      # Bottom of shaft before head
        ]
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(line.color, line.opacity))
        painter.drawPolygon(QPolygonF(points))
        painter.restore()
        return

    # Normal line rendering for non-arrows
    pen = QPen(qcolor(line.color), line.width)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawLine(p1, p2)



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
