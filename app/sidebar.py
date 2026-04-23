"""
Sidebar Navigation Widget
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QSizePolicy, QScrollArea, QFrame,
)
from PyQt6.QtGui import QFont


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(f"  {icon}  {label}", parent)
        self.setCheckable(True)
        self.setFlat(True)
        self.setFixedHeight(40)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 12px;
                border-radius: 6px;
            }
            QPushButton:checked {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QPushButton:hover:!checked {
                background: palette(midlight);
            }
        """)


class PlaylistItem(QPushButton):
    def __init__(self, label: str, playlist_id: str, parent=None):
        super().__init__(f"  ♪  {label}", parent)
        self.playlist_id = playlist_id
        self.setFlat(True)
        self.setFixedHeight(32)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 8px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: palette(midlight);
            }
        """)


class Sidebar(QWidget):
    """
    Navigation sidebar.
    Emits:
      page_requested(str)          — "home" | "search" | "history" | "liked" | "queue"
      playlist_requested(str)      — playlist_id
    """

    page_requested     = pyqtSignal(str)
    playlist_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self._nav_buttons: dict[str, NavButton] = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 12, 8, 8)
        root.setSpacing(2)

        # App title
        title = QLabel("YTMusic")
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        title.setFont(font)
        title.setContentsMargins(12, 0, 0, 8)
        root.addWidget(title)

        # --- Main navigation ---
        nav_items = [
            ("home",    "🏠", "Home"),
            ("search",  "🔍", "Search"),
            ("library", "📚", "Library"), # New Library entry
            ("history", "🕐", "History"),
            ("liked",   "❤", "Liked Songs"),
            ("queue",   "≡", "Queue"),
        ]

        for page_id, icon, label in nav_items:
            btn = NavButton(icon, label)
            btn.clicked.connect(lambda checked, p=page_id: self._nav_clicked(p))
            self._nav_buttons[page_id] = btn
            root.addWidget(btn)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: palette(mid);")
        root.addWidget(sep)

        # Playlists section
        pl_header = QLabel("PLAYLISTS")
        pl_header.setStyleSheet("font-size: 10px; font-weight: bold; color: palette(mid); padding-left: 12px;")
        pl_header.setContentsMargins(0, 4, 0, 4)
        root.addWidget(pl_header)

        self._playlist_scroll = QScrollArea()
        self._playlist_scroll.setWidgetResizable(True)
        self._playlist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._playlist_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._playlist_container = QWidget()
        self._playlist_layout    = QVBoxLayout(self._playlist_container)
        self._playlist_layout.setContentsMargins(0, 0, 0, 0)
        self._playlist_layout.setSpacing(1)
        self._playlist_layout.addStretch()

        self._playlist_scroll.setWidget(self._playlist_container)
        root.addWidget(self._playlist_scroll, 1)

        # Select home by default
        self._nav_buttons["home"].setChecked(True)

    def set_page(self, page_id: str):
        for pid, btn in self._nav_buttons.items():
            btn.setChecked(pid == page_id)

    def set_playlists(self, playlists: list[dict]):
        # Clear old items (except stretch)
        layout = self._playlist_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        for pl in playlists:
            pl_id   = pl.get("playlistId", "")
            pl_name = pl.get("title", "Untitled")
            btn     = PlaylistItem(pl_name, pl_id)
            btn.clicked.connect(lambda checked, pid=pl_id: self.playlist_requested.emit(pid))
            layout.insertWidget(layout.count() - 1, btn)

    def _nav_clicked(self, page_id: str):
        for pid, btn in self._nav_buttons.items():
            btn.setChecked(pid == page_id)
        self.page_requested.emit(page_id)
