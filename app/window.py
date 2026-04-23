"""
Main Window
Wires together: YTMusicService, PlayerService, DiscordRPCService,
Sidebar, Pages, and the PlayerBar.
"""
from __future__ import annotations

import logging
import os
import pathlib
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QSettings, pyqtSlot, QSize
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QStackedWidget, QStatusBar, QMessageBox, QFrame,
    QSplitter, QLabel,
)
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut

from app.auth_dialog import AuthDialog
from app.sidebar import Sidebar
from app.player_bar import PlayerBar
from app.pages import (
    HomePage, SearchPage, HistoryPage, LikedPage,
    PlaylistPage, QueuePage, NowPlayingPage, LibraryPage,
    _raw_to_track,
)
from app.workers.ytmusic_service import YTMusicService
from app.workers.player_service import PlayerService, Track
from app.workers.discord_rpc import DiscordRPCService

log = logging.getLogger(__name__)

CONFIG_DIR = str(pathlib.Path.home() / ".config" / "ytmusic-desktop")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(CONFIG_DIR, exist_ok=True)

        self.setWindowTitle("YTMusic Desktop")
        self.setMinimumSize(900, 600)
        self._restore_geometry()

        # --- Services ---
        self._ytm    = YTMusicService(self)
        self._player = PlayerService(self)
        self._rpc    = DiscordRPCService(self)

        # --- Build UI ---
        self._build_ui()
        self._connect_services()
        self._setup_shortcuts()

        # --- Auth ---
        QTimer.singleShot(0, self._init_auth)

        # --- Discord RPC update timer ---
        self._rpc_timer = QTimer(self)
        self._rpc_timer.setInterval(5000)
        self._rpc_timer.timeout.connect(self._update_discord_rpc)
        self._rpc_timer.start()

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main body (sidebar + content)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_requested.connect(self._go_to_page)
        self._sidebar.playlist_requested.connect(self._load_playlist)
        self._library_page = LibraryPage()
        self._now_playing_page = NowPlayingPage()

        # Vertical divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)

        # Pages stack
        self._pages = QStackedWidget()

        self._home_page     = HomePage()
        self._search_page   = SearchPage()
        self._history_page  = HistoryPage()
        self._liked_page    = LikedPage()
        self._playlist_page = PlaylistPage()
        self._queue_page    = QueuePage()

        self._page_map: dict[str, tuple[int, QWidget]] = {}
        for page_id, widget in [
            ("home",     self._home_page),
            ("search",   self._search_page),
            ("history",  self._history_page),
            ("liked",    self._liked_page),
            ("playlist", self._playlist_page),
            ("queue",    self._queue_page),
        ]:
            idx = self._pages.addWidget(widget)
            self._page_map[page_id] = (idx, widget)
        self._page_map["library"] = (self._pages.addWidget(self._library_page), self._library_page)
        self._page_map["now_playing"] = (self._pages.addWidget(self._now_playing_page), self._now_playing_page)

        body.addWidget(self._sidebar)
        body.addWidget(line)
        body.addWidget(self._pages, 1)

        # Player bar — separated by a native HLine (Breeze renders this
        # as a proper 1-px rule using the theme's mid colour).
        self._player_bar = PlayerBar(self._player)
        bar_sep = QFrame()
        bar_sep.setFrameShape(QFrame.Shape.HLine)
        bar_sep.setFrameShadow(QFrame.Shadow.Sunken)

        root.addLayout(body, 1)
        root.addWidget(bar_sep)
        root.addWidget(self._player_bar)

    # ------------------------------------------------------------------
    # Service connections
    # ------------------------------------------------------------------

    def _connect_services(self):
        # YTMusic API results
        self._ytm.result.connect(self._on_ytm_result)
        self._ytm.error.connect(self._on_ytm_error)

        # Player events
        self._player.track_changed.connect(self._on_track_changed)
        self._player.state_changed.connect(self._on_player_state)
        self._player.error.connect(self._on_player_error)
        self._player.queue_changed.connect(self._refresh_queue_page)

        # Page signals → service calls
        self._home_page.refresh_requested.connect(self._load_home)
        self._home_page.track_play_requested.connect(self._play_tracks)

        self._search_page.search_requested.connect(self._do_search)
        self._search_page.track_play_requested.connect(self._play_tracks)

        self._history_page.refresh_requested.connect(self._load_history)
        self._history_page.track_play_requested.connect(self._play_tracks)

        self._liked_page.refresh_requested.connect(self._load_liked)
        self._liked_page.track_play_requested.connect(self._play_tracks)

        self._playlist_page.track_play_requested.connect(self._play_tracks)
        self._queue_page.track_play_requested.connect(self._play_from_queue)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self).activated.connect(
            self._player.toggle_play_pause)
        QShortcut(QKeySequence("Ctrl+Right"), self).activated.connect(
            self._player.next)
        QShortcut(QKeySequence("Ctrl+Left"), self).activated.connect(
            self._player.previous)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            lambda: self._go_to_page("search"))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _init_auth(self):
        auth_file = os.path.join(CONFIG_DIR, "browser.json")
        oauth_file = os.path.join(CONFIG_DIR, "oauth.json")

        # CHANGE: Check oauth_file FIRST, then auth_file
        for f in (oauth_file, auth_file):
            if os.path.exists(f):
                if self._ytm.setup_authenticated(f):
                    self._on_authenticated()
                    return

        # Need to auth
        dlg = AuthDialog(CONFIG_DIR, self)
        if dlg.exec() and dlg.result_path:
            if self._ytm.setup_authenticated(dlg.result_path):
                self._on_authenticated()
            else:
                QMessageBox.critical(self, "Auth Failed", "Could not authenticate. Please try again.")
        else:
            log.warning("Authentication not completed; API features will be unavailable")
            self._status.showMessage("Not authenticated — some features unavailable")

    def _on_authenticated(self):
        self._status.showMessage("Signed in ✓", 3000)
        self._load_home()
        self._load_sidebar_playlists()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_page(self, page_id: str):
        idx, widget = self._page_map.get(page_id, (0, self._home_page))
        self._pages.setCurrentIndex(idx)
        self._sidebar.set_page(page_id)

        # Lazy load
        if page_id == "history" and not self._history_page._list.track_model.rowCount():
            self._load_history()
        elif page_id == "liked" and not self._liked_page._list.track_model.rowCount():
            self._load_liked()
        elif page_id == "queue":
            self._refresh_queue_page()

    def _load_playlist(self, playlist_id: str):
        self._go_to_page("playlist")
        self._playlist_page.show_loading(True)
        self._ytm.get_playlist(playlist_id)

    # ------------------------------------------------------------------
    # Data loaders
    # ------------------------------------------------------------------

    def _load_home(self):
        if not self._ytm.is_authenticated():
            return
        self._home_page.show_loading(True)
        self._ytm.get_home()

    def _load_history(self):
        if not self._ytm.is_authenticated():
            return
        self._history_page.show_loading(True)
        self._ytm.get_history()

    def _load_liked(self):
        if not self._ytm.is_authenticated():
            return
        self._liked_page.show_loading(True)
        self._ytm.get_liked_songs()

    def _load_sidebar_playlists(self):
        self._ytm.get_library_playlists()

    def _do_search(self, query: str, filter_type: str):
        self._search_page.show_loading(True)
        self._ytm.search(query, filter=filter_type)
        self._status.showMessage(f'Searching for "{query}"…')

    # ------------------------------------------------------------------
    # YTMusic result handler (dispatch by task_id)
    # ------------------------------------------------------------------

    @pyqtSlot(str, object)
    def _on_ytm_result(self, task_id: str, data):
        if task_id == "home":
            self._home_page.show_loading(False)
            self._home_page.set_home_data(data or [])
            # --- NEW: Fetch thumbnails for the home page sections! ---
            for section in (data or []):
                self._fetch_thumbnails_for(section.get("contents", []), "home")

        elif task_id == "history":
            self._history_page.show_loading(False)
            self._history_page.set_history(data or [])
            self._fetch_thumbnails_for(data or [], "history")

        elif task_id == "liked_songs":
            self._liked_page.show_loading(False)
            self._liked_page.set_liked(data or {})
            tracks_raw = (data or {}).get("tracks", [])
            self._fetch_thumbnails_for(tracks_raw, "liked")

        elif task_id == "library_playlists":
            self._sidebar.set_playlists(data or [])
            self._library_page.set_playlists(data or [])

        elif task_id.startswith("playlist:"):
            self._playlist_page.show_loading(False)
            self._playlist_page.set_playlist(data or {})
            tracks_raw = (data or {}).get("tracks", [])
            self._fetch_thumbnails_for(tracks_raw, "playlist")

        elif task_id.startswith("search:"):
            self._search_page.show_loading(False)
            self._search_page.set_results(data or [])
            self._fetch_thumbnails_for(data or [], "search")
            self._status.showMessage(f"{len(data or [])} results")

        elif task_id.startswith("thumb:"):
            video_id = task_id[6:]
            data_bytes: bytes = data
            
            # Forward to static pages
            self._history_page.set_thumbnail(video_id, data_bytes)
            self._liked_page.set_thumbnail(video_id, data_bytes)
            self._search_page.set_thumbnail(video_id, data_bytes)
            self._playlist_page.set_thumbnail(video_id, data_bytes)
            self._queue_page._list.set_thumbnail(video_id, data_bytes)
            self._now_playing_page.set_large_thumbnail(data_bytes)
            
            # --- NEW: Forward to dynamic HomePage horizontal lists ---
            from app.track_list import HorizontalTrackListView
            for child in self._home_page._body.findChildren(HorizontalTrackListView):
                child.set_thumbnail(video_id, data_bytes)

            # Player bar if this is current track
            cur = self._player.current_track
            if cur and cur.video_id == video_id:
                self._player_bar.set_thumbnail(data_bytes)
        elif task_id.startswith("watch:"):
            # FIX 3: Fetch thumbnails for the tracks loaded into the queue
            tracks_raw = (data or {}).get("tracks", [])
            self._fetch_thumbnails_for(tracks_raw, "watch")

        elif task_id.startswith("thumb:"):
            video_id = task_id[6:]
            data_bytes: bytes = data
            
            # Forward to static pages
            self._history_page.set_thumbnail(video_id, data_bytes)
            self._liked_page.set_thumbnail(video_id, data_bytes)
            self._search_page.set_thumbnail(video_id, data_bytes)
            self._playlist_page.set_thumbnail(video_id, data_bytes)
            self._queue_page._list.set_thumbnail(video_id, data_bytes)
            
            # Forward to dynamic HomePage horizontal lists
            from app.track_list import HorizontalTrackListView
            for child in self._home_page._body.findChildren(HorizontalTrackListView):
                child.set_thumbnail(video_id, data_bytes)

            # FIX 2: Only update Player Bar and NowPlaying Large Art if it's the current track
            cur = self._player.current_track
            if cur and cur.video_id == video_id:
                self._player_bar.set_thumbnail(data_bytes)
                self._now_playing_page.set_large_thumbnail(data_bytes)

    @pyqtSlot(str, str)
    def _on_ytm_error(self, task_id: str, message: str):
        log.error("YTMusic API error [%s]: %s", task_id, message)
        # Hide loading bars
        for page in (self._home_page, self._search_page,
                     self._history_page, self._liked_page, self._playlist_page):
            page.show_loading(False)
        self._status.showMessage(f"API error: {message}", 8000)

    # ------------------------------------------------------------------
    # Thumbnail batch fetch (low priority, throttled)
    # ------------------------------------------------------------------

    def _fetch_thumbnails_for(self, raw_list: list[dict], _source: str):
        """Fetch thumbnails for first 30 items; stagger to avoid hammering."""
        seen = set()
        count = 0
        for raw in raw_list[:30]:
            # --- NEW SAFETY CHECK ---
            if not raw:
                continue

            # Look for playlistId and browseId too
            vid = raw.get("videoId") or raw.get("playlistId") or raw.get("browseId", "")
            
            thumbs = raw.get("thumbnails") or raw.get("thumbnail") or []
            if not vid or not thumbs or vid in seen:
                continue
            
            seen.add(vid)
            # Use the LAST entry — it is always the highest resolution.
            url = thumbs[-1].get("url", "")
            if url:
                delay = count * 5   # 5ms stagger for faster thumbnail loading
                QTimer.singleShot(delay, lambda u=url, v=vid: self._ytm.download_thumbnail(u, v))
                count += 1

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    @pyqtSlot(object, list, int)
    def _play_tracks(self, track: Track, all_tracks: list[Track], idx: int):
        # --- NEW: Intercept Playlists and Albums ---
        # YouTube video IDs are strictly 11 characters. 
        # Anything longer (PL..., MPREb..., RD...) is a Playlist or Album!
        if len(track.video_id) > 11:
            self._load_playlist(track.video_id) # Route to the Playlist page
            return

        if not all_tracks:
            all_tracks = [track]
            idx = 0
        
        self._player.set_queue(all_tracks, idx)

    def _play_from_queue(self, track: Track, _all: list[Track]):
        queue = self._player.get_queue()
        try:
            idx = next(i for i, t in enumerate(queue) if t.video_id == track.video_id)
            self._player.play_index(idx)
        except StopIteration:
            pass

    def _on_track_changed(self, track: Track):
        self.setWindowTitle(f"{track.title} — {track.artist} | YTMusic Desktop")
        # Update Now Playing Page
        self._now_playing_page.set_now_playing(track, self._player.get_queue())
        # Automatically switch view if not already on search/history
        if self._pages.currentWidget() not in (self._search_page, self._history_page):
            self._go_to_page("now_playing")

        # Fetch thumbnail for player bar and now playing art
        if track.thumbnail_url:
            self._ytm.download_thumbnail(track.thumbnail_url, track.video_id)

        # Load up-next queue only if authenticated
        if self._ytm.is_authenticated():
            self._ytm.get_watch_playlist(track.video_id)
            # Sync play to YTMusic history (non-blocking, best-effort)
            self._ytm.add_history_item(track.video_id)
        else:
            log.warning(
                "Skipping watch playlist sync and history update because YTMusic is not authenticated"
            )

        # Update playing indicators
        for page in (self._history_page, self._liked_page,
                     self._playlist_page, self._queue_page):
            page.set_playing(track.video_id)
        self._now_playing_page.set_playing(track.video_id)
        # Invalidate cached history so next visit fetches fresh data
        self._history_page._list.track_model.set_tracks([])

    def _on_player_state(self, state: str):
        log.info("Player state changed: %s", state)
        self._update_discord_rpc()

    def _on_player_error(self, message: str):
        log.error("Player error: %s", message)
        self._status.showMessage(f"Player: {message}", 6000)

    def _refresh_queue_page(self):
        q   = self._player.get_queue()
        idx = self._player.get_queue_index()
        self._queue_page.set_queue(q, idx)

    # ------------------------------------------------------------------
    # Discord RPC
    # ------------------------------------------------------------------

    def _update_discord_rpc(self):
        cur = self._player.current_track
        if not cur:
            self._rpc.clear()
            return
        self._rpc.update(
            title=cur.title,
            artist=cur.artist,
            is_playing=self._player.is_playing(),
            position_sec=self._player.position() // 1000,
            duration_sec=cur.duration_sec,
            thumbnail_url=cur.thumbnail_url, # <-- Pass the live URL
        )

    # ------------------------------------------------------------------
    # Window state
    # ------------------------------------------------------------------

    def _restore_geometry(self):
        settings = QSettings("YTMusicDesktop", "MainWindow")
        geo = settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1100, 700)

    def closeEvent(self, event):
        settings = QSettings("YTMusicDesktop", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        self._rpc.close()
        super().closeEvent(event)
