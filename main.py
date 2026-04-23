#!/usr/bin/env python3
"""
YTMusic Desktop Client - Main Entry Point
"""
import sys
import os

# Use the KDE platform theme so PyQt6 picks up Breeze colours, fonts,
# icon themes, and window decorations automatically on Plasma 6.
# On non-KDE desktops this env-var is simply ignored.
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")

from PyQt6.QtWidgets import QApplication, QStyleFactory
from app.window import MainWindow


def _pick_style() -> "str | None":
    """Return the best available style name, preferring Breeze."""
    available = {s.lower(): s for s in QStyleFactory.keys()}
    for candidate in ("breeze", "breezedark", "fusion"):
        if candidate in available:
            return available[candidate]
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("YTMusic Desktop")
    app.setApplicationDisplayName("YTMusic Desktop")
    app.setOrganizationName("YTMusicDesktop")
    app.setOrganizationDomain("ytmusic.local")

    # If the platform theme already loaded Breeze (KDE session), do nothing.
    # Otherwise explicitly set the best available style.
    current = app.style().objectName().lower() if app.style() else ""
    if "breeze" not in current:
        style_name = _pick_style()
        if style_name:
            app.setStyle(style_name)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
