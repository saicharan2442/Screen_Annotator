"""Persistent configuration (config.json) with defaults merging."""

import copy
import json
import logging
import os

from .utils import PROJECT_ROOT

log = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

DEFAULTS = {
    # Global hotkey combos (parsed by hotkeys.parse_combo).
    "hotkeys": {
        "activate": "ctrl+shift+a",
        "deactivate": "ctrl+shift+q",
        "toggle_toolbar": "ctrl+shift+t",
    },
    # Palette cycled with the X key / toolbar right-click.
    "colors_palette": [
        "#FF3B30",  # red
        "#FF9500",  # orange
        "#FFCC00",  # yellow
        "#34C759",  # green
        "#32ADE6",  # light blue
        "#007AFF",  # blue
        "#AF52DE",  # purple
        "#FFFFFF",  # white
    ],
    "pen": {"color": "#FF3B30", "width": 4, "opacity": 1.0},
    "box": {
        "color": "#FFCC00",
        "border_width": 4,
        "opacity": 1.0,
        "filled": False,
        "fill_opacity": 0.18,
    },
    "line": {"color": "#32ADE6", "width": 4, "opacity": 1.0},
    "arrow": {"color": "#32ADE6", "width": 4, "opacity": 1.0},
    "text": {
        "color": "#FFFFFF",
        "size": 28,
        "family": "Segoe UI",
        "bold": True,
        "opacity": 1.0,
    },
    "eraser": {"radius": 14},
    "toolbar": {
        "visible": True,       # shown when annotation mode activates
        "x": -1,               # logical global position (-1 = default right side)
        "y": -1,
        "edge_threshold": 140, # px from a left/right edge => vertical layout
    },
}


def _merge(base, extra):
    """Recursively merge *extra* on top of *base* (base is not mutated)."""
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    """JSON-backed settings dictionary that always contains every default key."""

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ load
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            self.data = _merge(DEFAULTS, stored)
            log.info("Configuration loaded from %s", self.path)
        except FileNotFoundError:
            log.info("No config file found; using defaults (%s)", self.path)
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Failed to read config %s: %s - defaults used", self.path, exc)
            self.data = copy.deepcopy(DEFAULTS)

    # ------------------------------------------------------------------ save
    def save(self):
        try:
            tmp = self.path + ".tmp"
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
            os.replace(tmp, self.path)
            log.debug("Configuration saved to %s", self.path)
        except OSError as exc:
            log.error("Failed to save config %s: %s", self.path, exc)

    # ------------------------------------------------------------- accessors
    def section(self, name):
        """Return the settings sub-dictionary for *name*."""
        return self.data.setdefault(name, {})

    def set_and_save(self, section, key, value):
        self.data.setdefault(section, {})[key] = value
        self.save()
