#!/usr/bin/env python3
"""
YTMusic Desktop Client - Main Entry Point
"""
import sys
import os

# Ensure Qt uses system theme
os.environ.setdefault("QT_QPA_PLATFORMTHEME", "gtk3")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette

from app.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("YTMusic Desktop")
    app.setApplicationDisplayName("YTMusic Desktop")
    app.setOrganizationName("YTMusicDesktop")
    app.setOrganizationDomain("ytmusic.local")

    # Use system style
    app.setStyle("Fusion")  # Fusion adapts to system palette well

    # Enable high DPI
    # app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
