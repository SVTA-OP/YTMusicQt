"""
Page Panels
Each panel is a QWidget shown/hidden in the main stacked area.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea,
    QStackedWidget, QComboBox, QFrame, QProgressBar,
    QSizePolicy, QMenu, QToolBar,
)
from PyQt6.QtGui import QFont, QAction

from app.track_list import TrackListView, Track


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(font.pointSize() + 2)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setContentsMargins(0, 8, 0, 4)
    return lbl


def _loading_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 0)
    bar.setMaximumHeight(3)
    bar.setTextVisible(False)
    return bar


# ---------------------------------------------------------------------------
# Base page
# ---------------------------------------------------------------------------

class BasePage(QWidget):
    """All pages share: track_play_requested signal, a loading bar, a body layout."""

    track_play_requested = pyqtSignal(object, list)  # Track, all tracks

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 12, 16, 8)
        self._root.setSpacing(8)

        self._loading_bar = _loading_bar()
        self._loading_bar.hide()
        self._root.addWidget(self._loading_bar)

    def show_loading(self, visible: bool):
        if visible:
            self._loading_bar.show()
        else:
            self._loading_bar.hide()

    def _wire_list(self, lst: TrackListView):
        lst.track_activated.connect(
            lambda t: self.track_play_requested.emit(t, lst.track_model.all_tracks())
        )
        lst.context_menu_requested.connect(self._show_track_context)

    def _show_track_context(self, track: Track, pos):
        menu = QMenu(self)
        play_action = menu.addAction("Play")
        if play_action is not None:
            play_action.triggered.connect(
                lambda: self.track_play_requested.emit(track, [track])
            )

        menu.addAction("Add to queue")
        menu.addSeparator()
        copy_action = menu.addAction("Copy video ID")
        if copy_action is not None:
            copy_action.triggered.connect(
                lambda: __import__("PyQt6.QtWidgets", fromlist=["QApplication"]).QApplication.clipboard().setText(track.video_id)
            )
        menu.exec(pos)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

class HomePage(BasePage):
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        hdr = QHBoxLayout()
        hdr.addWidget(_section_header("Home"))
        hdr.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFlat(True)
        refresh_btn.clicked.connect(self.refresh_requested)
        hdr.addWidget(refresh_btn)
        self._root.addLayout(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(12)
        self._body_layout.addStretch()

        scroll.setWidget(self._body)
        self._root.addWidget(scroll, 1)

    def set_home_data(self, sections: list[dict]):
        layout = self._body_layout
        # clear
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        for section in sections[:6]:
            title_lbl = _section_header(section.get("title", ""))
            layout.insertWidget(layout.count() - 1, title_lbl)

            lst = TrackListView()
            tracks = []
            for raw in section.get("contents", [])[:10]:
                t = _raw_to_track(raw)
                if t:
                    tracks.append(t)
            lst.set_tracks(tracks)
            lst.setMaximumHeight(min(len(tracks), 5) * 60)
            self._wire_list(lst)
            layout.insertWidget(layout.count() - 1, lst)


# ---------------------------------------------------------------------------
# Search page
# ---------------------------------------------------------------------------

class SearchPage(BasePage):
    search_requested = pyqtSignal(str, str)   # query, filter

    def __init__(self, parent=None):
        super().__init__(parent)

        # Search bar
        bar = QHBoxLayout()
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search songs, artists, albums…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setMinimumHeight(36)
        self._search_box.returnPressed.connect(self._do_search)

        self._filter_combo = QComboBox()
        for label, val in [
            ("Songs", "songs"), ("Videos", "videos"),
            ("Albums", "albums"), ("Artists", "artists"),
            ("Playlists", "community_playlists"),
        ]:
            self._filter_combo.addItem(label, val)

        search_btn = QPushButton("Search")
        search_btn.setMinimumHeight(36)
        search_btn.clicked.connect(self._do_search)

        bar.addWidget(self._search_box, 1)
        bar.addWidget(self._filter_combo)
        bar.addWidget(search_btn)
        self._root.addLayout(bar)

        self._results_list = TrackListView()
        self._wire_list(self._results_list)
        self._root.addWidget(self._results_list, 1)

        self._status = QLabel("Enter a search query above")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._root.addWidget(self._status)

    def set_results(self, results: list[dict]):
        tracks = [t for raw in results if (t := _raw_to_track(raw))]
        self._results_list.set_tracks(tracks)
        self._status.setText(f"{len(tracks)} results")
        self._status.setVisible(len(tracks) == 0)

    def set_thumbnail(self, video_id: str, data: bytes):
        self._results_list.set_thumbnail(video_id, data)

    def _do_search(self):
        q = self._search_box.text().strip()
        if q:
            f = self._filter_combo.currentData()
            self.search_requested.emit(q, f)


# ---------------------------------------------------------------------------
# History page
# ---------------------------------------------------------------------------

class HistoryPage(BasePage):
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        hdr = QHBoxLayout()
        hdr.addWidget(_section_header("Listening History"))
        hdr.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFlat(True)
        refresh_btn.clicked.connect(self.refresh_requested)
        hdr.addWidget(refresh_btn)
        self._root.addLayout(hdr)

        self._list = TrackListView()
        self._wire_list(self._list)
        self._root.addWidget(self._list, 1)

    def set_history(self, items: list[dict]):
        tracks = [t for raw in items if (t := _raw_to_track(raw))]
        self._list.set_tracks(tracks)

    def set_thumbnail(self, video_id: str, data: bytes):
        self._list.set_thumbnail(video_id, data)

    def set_playing(self, video_id: str):
        self._list.set_playing(video_id)


# ---------------------------------------------------------------------------
# Liked Songs page
# ---------------------------------------------------------------------------

class LikedPage(BasePage):
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        hdr = QHBoxLayout()
        hdr.addWidget(_section_header("❤ Liked Songs"))
        hdr.addStretch()
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFlat(True)
        refresh_btn.clicked.connect(self.refresh_requested)
        hdr.addWidget(refresh_btn)
        self._root.addLayout(hdr)

        self._count_label = QLabel("")
        self._root.addWidget(self._count_label)

        self._list = TrackListView()
        self._wire_list(self._list)
        self._root.addWidget(self._list, 1)

    def set_liked(self, playlist_data: dict):
        tracks_raw = playlist_data.get("tracks", [])
        tracks = [t for raw in tracks_raw if (t := _raw_to_track(raw))]
        self._list.set_tracks(tracks)
        self._count_label.setText(f"{len(tracks)} songs")

    def set_thumbnail(self, video_id: str, data: bytes):
        self._list.set_thumbnail(video_id, data)

    def set_playing(self, video_id: str):
        self._list.set_playing(video_id)


# ---------------------------------------------------------------------------
# Playlist page
# ---------------------------------------------------------------------------

class PlaylistPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._title_label = _section_header("Playlist")
        self._root.addWidget(self._title_label)

        self._meta_label = QLabel("")
        self._root.addWidget(self._meta_label)

        self._list = TrackListView()
        self._wire_list(self._list)
        self._root.addWidget(self._list, 1)

    def set_playlist(self, playlist_data: dict):
        self._title_label.setText(playlist_data.get("title", "Playlist"))
        count = playlist_data.get("trackCount", 0)
        self._meta_label.setText(f"{count} tracks")
        tracks_raw = playlist_data.get("tracks", [])
        tracks = [t for raw in tracks_raw if (t := _raw_to_track(raw))]
        self._list.set_tracks(tracks)

    def set_thumbnail(self, video_id: str, data: bytes):
        self._list.set_thumbnail(video_id, data)

    def set_playing(self, video_id: str):
        self._list.set_playing(video_id)


# ---------------------------------------------------------------------------
# Queue page
# ---------------------------------------------------------------------------

class QueuePage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._root.addWidget(_section_header("≡ Queue"))

        self._now_playing = QLabel("Nothing playing")
        self._now_playing.setStyleSheet("font-weight: bold; padding: 4px;")
        self._root.addWidget(self._now_playing)

        self._list = TrackListView()
        self._wire_list(self._list)
        self._root.addWidget(self._list, 1)

    def set_queue(self, tracks: list[Track], current_index: int):
        self._list.set_tracks(tracks)
        if 0 <= current_index < len(tracks):
            t = tracks[current_index]
            self._now_playing.setText(f"▶  {t.title} — {t.artist}")
            self._list.set_playing(t.video_id)

    def set_playing(self, video_id: str):
        self._list.set_playing(video_id)


# ---------------------------------------------------------------------------
# Raw → Track converter
# ---------------------------------------------------------------------------

def _raw_to_track(raw: dict) -> Track | None:
    """Convert ytmusicapi result dict to a Track dataclass."""
    if not raw:
        return None

    video_id = raw.get("videoId") or raw.get("videoID", "")
    if not video_id:
        return None

    title   = raw.get("title", "Unknown")
    artists = raw.get("artists") or []
    artist  = ", ".join(a.get("name", "") for a in artists) if artists else raw.get("artist", "")
    album_d = raw.get("album") or {}
    album   = album_d.get("name", "") if isinstance(album_d, dict) else str(album_d)

    duration = raw.get("duration_seconds") or 0
    if not duration:
        dur_str = raw.get("duration", "") or ""
        parts   = dur_str.split(":")
        try:
            if len(parts) == 2:
                duration = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            duration = 0

    thumb_url = ""
    thumbs    = raw.get("thumbnails") or []
    if thumbs:
        thumb_url = thumbs[-1].get("url", "")

    return Track(
        video_id=video_id,
        title=title,
        artist=artist,
        album=album,
        duration_sec=duration,
        thumbnail_url=thumb_url,
    )
