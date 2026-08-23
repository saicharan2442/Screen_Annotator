# Screen Annotator — Digital Teacher Pen for Windows

A transparent, always-on-top annotation layer for Windows. Run it in the
background, press **Ctrl+Shift+A** anywhere (Terminal, VS Code, Chrome,
PowerPoint, Word, PDF readers, video players, the desktop…) and draw over
whatever is on screen. The underlying application is **never modified,
moved or focused**.

```
python main.py          → runs in background (tray icon only)
Ctrl+Shift+A            → transparent fullscreen overlay appears
draw / box / text / erase
Ctrl+Shift+Q            → everything cleared, overlay hidden, app keeps running
Ctrl+Shift+A            → ready again
```

## Install & run

```bash
pip install -r requirements.txt
python main.py
```

Requirements: Windows 10/11, Python 3.9+, PySide6. No admin rights needed.

A tray icon appears with a notification once the hotkeys are registered.
Quit from the tray menu; left-clicking the tray icon toggles annotation mode.

## Global shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+A` | Activate annotation overlay |
| `Ctrl+Shift+Q` | Clear all annotations + hide overlay |
| `Ctrl+Shift+T` | Show / hide the floating toolbar |

## Shortcuts while annotating

| Key | Action |
|---|---|
| `P` | Pen |
| `B` | Box / rectangle |
| `T` | Text (click where to type) |
| `E` | Eraser (removes whole objects it touches) |
| `V` | Select / move an object (`Delete` removes selection) |
| `C` | Clear all |
| `X` | Cycle colour of the active tool |
| `[` / `]` | Decrease / increase size (mouse wheel also works) |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |

### Text tool

1. Press `T`, click anywhere — a caret appears on the overlay.
2. Type. Keystrokes are captured by the app and can never reach Terminal /
   PowerShell / your editor.
3. `Enter` = newline · `Backspace` = delete · `Ctrl+V` = paste ·
   `Esc` or `Ctrl+Enter` = finish · click elsewhere = commit and start a new text.

The toolbar is fully optional: right-click it for colour / size / opacity /
box-fill menus, drag it anywhere — it becomes vertical near the left/right
edges and horizontal near the top/bottom automatically. Its position and
visibility are remembered between sessions and restarts.

## How it stays out of your way

* Overlay windows use `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` + topmost, so they
  never take keyboard focus; the focused application keeps focus the whole time.
* Single-key shortcuts exist **only while annotation mode is active**
  (registered via the Win32 `RegisterHotKey` API and released again), so normal
  typing is untouched before/after.
* During text entry a low-level keyboard hook swallows every key so nothing
  leaks into the underlying window; the hook is removed as soon as you finish.
* Annotations live in a small object model (`PenStroke`, `RectangleAnnotation`,
  `TextAnnotation`) rendered with QPainter per monitor; undo/redo operates on
  those objects only — never on other applications.

## Configuration (`config.json`)

Hotkeys, palette colours, pen width/colour/opacity, box border/fill,
text font family/size/weight/colour, eraser radius and toolbar position /
visibility / edge threshold are all persisted here automatically.

## Logs

`logs/app.log` (rotating). Hotkey conflicts, API failures and unexpected
errors are logged instead of crashing; a tray warning appears if a global
hotkey could not be registered (e.g. another app already owns it).

## Multi-monitor & DPI

One overlay per monitor is created, coordinates are handled in logical
(device-independent) pixels and Qt's per-monitor DPI awareness is enabled, so
100 %–200 % scaling and mixed-DPI multi-monitor setups draw exactly under the
cursor.

## Project layout

```
screen_annotator/
├── main.py               entry point
├── requirements.txt
├── config.json           persisted settings
├── logs/app.log          rotating log file
└── app/
    ├── application.py    state machine, wiring, tray, screens
    ├── overlay.py        transparent per-monitor overlay widget
    ├── toolbar.py        movable icon-only toolbar
    ├── hotkeys.py        RegisterHotKey manager (+ config parsing)
    ├── windows_api.py    ctypes Win32 wrappers (hotkeys, hook, styles)
    ├── drawing.py        QPainter rendering + tool base class
    ├── annotations.py    object model & store
    ├── pen_tool.py       freehand pen
    ├── box_tool.py       rectangle tool
    ├── text_tool.py      text tool + keyboard-capture session
    ├── eraser.py         object-level eraser
    ├── move_tool.py      select/move/delete
    ├── undo_redo.py      command history
    ├── settings.py       config.json load/save
    └── utils.py          logging + geometry helpers
```
