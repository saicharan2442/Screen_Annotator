#!/usr/bin/env python3
"""Screen Annotator - digital teacher pen for Windows.

Run:  python main.py
The app starts in the background (tray icon only).

    Ctrl+Shift+A   activate annotation overlay
    Ctrl+Shift+Q   clear everything + hide overlay
    Ctrl+Shift+T   show / hide toolbar

While annotating:
    P pen | B box | T text | E eraser | V select-move | C clear all
    X cycle colour | [ ] size (or mouse wheel) | Ctrl+Z / Ctrl+Y undo/redo
    Delete removes the selected object.
Text tool: click, type, Enter = newline, Ctrl+Enter or Esc = done.
"""

import os
import sys


def main():
    # Must happen before QApplication is constructed.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    from app.utils import setup_logging
    logger = setup_logging()

    from app import APP_NAME, __version__
    from app import windows_api

    if not windows_api.acquire_single_instance():
        logger.error("%s is already running.", APP_NAME)
        print("Screen Annotator is already running (check the tray icon).")
        return 1

    if sys.platform != "win32":
        logger.error("This application requires Windows.")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)   # background app: no windows by default
    QGuiApplication.setApplicationDisplayName(APP_NAME)

    try:
        from app.application import ApplicationController
        controller = ApplicationController()
    except Exception:
        logger.exception("Fatal error during startup")
        raise

    # Keep settings fresh on exit as well.
    app.aboutToQuit.connect(controller.settings.save)

    logger.info("%s v%s ready - press Ctrl+Shift+A to annotate",
                APP_NAME, __version__)
    print(f"{APP_NAME} v{__version__} running in the background.")
    print("  Ctrl+Shift+A  = annotate      Ctrl+Shift+Q = clear & hide")
    print("  Ctrl+Shift+T  = toolbar       Quit via the tray icon menu.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
