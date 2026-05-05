"""
Main Window
Wires together: YTMusicService, PlayerService, DiscordRPCService,
Sidebar, Pages, and the PlayerBar. Redesigned for modern responsive layout.
"""
from __future__ import annotations

import logging
import os
import pathlib
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QSettings, pyqtSlot, QSize
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, 
    QStackedWidget, QStatusBar, QMessageBox, QFrame,QSplitter,QLabel
)
from PyQt6.QtGui import QIcon

from app.auth_dialog import AuthDialog
from app.sidebar import Sidebar
from app.player_bar import PlayerBar
from app.pages import (
    HomePage, SearchPage, HistoryPage, LikedPage, 
    PlaylistPage, QueuePage, NowPlayingPage, LibraryPage,_raw_to_track
)
from app.workers.ytmusic_service import YTMusicService
from app.workers.player_service import PlayerService as PlayerServiceClass # Avoid conflict with imported class name if any
from app.workers.discord_rpc import DiscordRPCService

log = logging.getLogger(__name__)

CONFIG_DIR = str(pathlib.Path.home() / ".config" / "ytmusic-desktop")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(CONFIG_DIR, exist_ok=True)

        self.setWindowTitle("YTMusic Desktop")
        # Minimum size for a comfortable experience, but flexible max size.
        self.setMinimumSize(900, 600) 
        # Don't set fixed geometry here; let _restore_geometry handle it or default to min.

        # --- Services ---
        self._ytm    = YTMusicService(self)
        self._player = PlayerServiceClass(self)
        self._rpc    = DiscordRPCService(self)

        # --- Build UI ---
        self._build_ui()
        
        # Connect services after UI is built to ensure widgets exist if needed (though mostly independent now)
        self._connect_services() 
        
        # Setup shortcuts before auth timer starts so they work immediately.
        self._setup_shortcuts()

        # --- Auth ---
        QTimer.singleShot(0, self._init_auth)

        # --- Discord RPC update timer ---
        self._rpc_timer = QTimer(self)
        self._rpc_timer.setInterval(5000)
        self._rpc_timer.timeout.connect(self._update_discord_rpc)
        self._rpc_timer.start()

        # Status bar (styled at bottom of window, not part of main layout usually but here for integration)
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        
    # ------------------------------------------------------------------
    # UI Construction - Modern Responsive Layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8) # Slight spacing between sections

        # --- Left Sidebar ---
        sidebar_container = QWidget()
        sidebar_vbox = QVBoxLayout(sidebar_container)
        
        self._sidebar = Sidebar()
        
        self._library_page = LibraryPage()

        sidebar_vbox.addWidget(self._sidebar, 0, Qt.AlignmentFlag.AlignTop) # Fixed height for header/logo area if any
        
        main_layout.addWidget(sidebar_container, 150) # Approximate width in pixels or use stretch logic later

        # --- Vertical Divider ---
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        
        content_widget = QWidget()
        content_vbox = QVBoxLayout(content_widget)
        
        self._pages = QStackedWidget()

        self._home_page     = HomePage()
        self._search_page   = SearchPage()
        self._history_page  = HistoryPage()
        self._liked_page    = LikedPage()
        self._playlist_page= PlaylistPage()
        self._queue_page    = QueuePage()

        
        # Map pages to indices and widgets for easy access later. 
        # Note: We add them here, but the actual mapping logic in _go_to_page needs these references.
        
        page_widgets = [self._home_page, self._search_page, self._history_page, 
                        self._liked_page, self._playlist_page, self._queue_page]

        for i in range(len(page_widgets)):
            idx = self._pages.addWidget(page_widgets[i])
            
        # Add Library and NowPlaying pages too (often hidden or special)
        lib_idx = self._pages.addWidget(self._library_page) 
        np_idx  = self._pages.addWidget(self._now_playing_page)

        
        main_layout.addWidget(content_widget, 1) # Takes remaining space
        
    def _connect_services(self):
        # YTMusic API results
        self._ytm.result.connect(self._on_ytm_result)
        self._ytm.error.connect(self._on_ytm_error)

        # Player events
        self._player.track_changed.connect(self._on_track_changed)
        self._player.state_changed.connect(self._on_player_state)
        self._player.error.connect(self._on_player_error)
        
    def _setup_shortcuts(self):
        pass
        
    # ------------------------------------------------------------------