"""Logging setup and small geometry helpers."""

import logging
import logging.handlers
import math
import os

# Project root (parent of the app/ package directory).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")


def setup_logging(level=logging.INFO):
    """Configure a rotating file logger plus console output."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError:
        pass

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:  # Unwritable disk etc. - keep running without file log.
        pass

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    return logging.getLogger("annotator")


def clamp(value, low, high):
    """Clamp *value* into [low, high]."""
    return max(low, min(high, value))


def dist_to_segment(px, py, x1, y1, x2, y2):
    """Distance in pixels from point (px, py) to the segment (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - x1, py - y1)
    # Project point onto segment, clamped to [0, 1].
    t = ((px - x1) * dx + (py - y1) * dy) / length_sq
    t = clamp(t, 0.0, 1.0)
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)


def inflate(rect, amount):
    """Inflate an (l, t, r, b) tuple by *amount* on every side."""
    l, t, r, b = rect
    return (l - amount, t - amount, r + amount, b + amount)


def rects_intersect(a, b):
    """Intersection test for two (l, t, r, b) tuples."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def union_rect(a, b):
    """Bounding box of two (l, t, r, b) tuples."""
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
