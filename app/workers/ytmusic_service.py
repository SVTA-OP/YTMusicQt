"""
YTMusic API Worker
Runs all ytmusicapi calls on background threads to keep UI responsive.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic worker infrastructure
# ---------------------------------------------------------------------------

class WorkerSignals(QObject):
    result = pyqtSignal(str, object)   # (task_id, data)
    error  = pyqtSignal(str, str)      # (task_id, message)


class _Task(QRunnable):
    def __init__(self, task_id: str, fn, *args, **kwargs):
        super().__init__()
        self.task_id  = task_id
        self.fn       = fn
        self.args     = args
        self.kwargs   = kwargs
        self.signals  = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(self.task_id, result)
        except Exception as exc:
            log.exception("Worker task %s failed", self.task_id)
            self.signals.error.emit(self.task_id, str(exc))


# ---------------------------------------------------------------------------
# YTMusic service wrapper
# ---------------------------------------------------------------------------

class YTMusicService(QObject):
    """
    Thin async wrapper around ytmusicapi.YTMusic.
    All network calls are dispatched to the global thread pool.
    Callers connect to `result` / `error` and dispatch by task_id.
    """

    result  = pyqtSignal(str, object)
    error   = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ytm: Any = None          # ytmusicapi.YTMusic instance (set after auth)
        pool = QThreadPool.globalInstance()
        assert pool is not None
        self._pool: QThreadPool = pool
        self._pool.setMaxThreadCount(4)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def setup_authenticated(self, headers_auth_path: str):
        """Initialize with saved auth headers file."""
        try:
            from ytmusicapi import YTMusic
            self._ytm = YTMusic(headers_auth_path)
            return True
        except Exception as exc:
            log.error("Auth setup failed: %s", exc)
            return False

    def setup_oauth(self, client_id: str, client_secret: str, token_path: str):
        """Initialize with OAuth credentials."""
        try:
            from ytmusicapi import YTMusic, OAuthCredentials
            creds = OAuthCredentials(client_id, client_secret)
            self._ytm = YTMusic("oauth.json", oauth_credentials=creds)
            return True
        except Exception as exc:
            log.error("OAuth setup failed: %s", exc)
            return False

    def is_authenticated(self) -> bool:
        return self._ytm is not None

    # ------------------------------------------------------------------
    # Dispatch helper
    # ------------------------------------------------------------------

    def _dispatch(self, task_id: str, fn, *args, **kwargs):
        if self._ytm is None:
            message = "YTMusic service is not authenticated"
            log.warning("Cannot dispatch %s: %s", task_id, message)
            self.error.emit(task_id, message)
            return
        task = _Task(task_id, fn, *args, **kwargs)
        task.signals.result.connect(self.result)
        task.signals.error.connect(self.error)
        self._pool.start(task)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, filter: str = "songs", limit: int = 20):
        """filter: songs | videos | albums | artists | playlists | community_playlists"""
        def _run():
            return self._ytm.search(query, filter=filter, limit=limit)
        self._dispatch(f"search:{query}:{filter}", _run)

    # ------------------------------------------------------------------
    # Home / Recommendations
    # ------------------------------------------------------------------

    def get_home(self):
        def _run():
            return self._ytm.get_home(limit=6)
        self._dispatch("home", _run)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self):
        def _run():
            return self._ytm.get_history()
        self._dispatch("history", _run)

    def remove_history_items(self, feedback_tokens: list[str]):
        def _run():
            return self._ytm.remove_history_items(feedback_tokens)
        self._dispatch("remove_history", _run)

    # ------------------------------------------------------------------
    # Liked songs / Library
    # ------------------------------------------------------------------

    def get_liked_songs(self, limit: int = 100):
        def _run():
            return self._ytm.get_liked_songs(limit=limit)
        self._dispatch("liked_songs", _run)

    def rate_song(self, video_id: str, rating: str):
        """rating: LIKE | DISLIKE | INDIFFERENT"""
        def _run():
            return self._ytm.rate_song(video_id, rating)
        self._dispatch(f"rate:{video_id}", _run)

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------

    def get_library_playlists(self, limit: int = 25):
        def _run():
            return self._ytm.get_library_playlists(limit=limit)
        self._dispatch("library_playlists", _run)

    def get_playlist(self, playlist_id: str, limit: int = 100):
        def _run():
            # YouTube Mixes, Radios, and Podcast feeds start with "RD"
            if playlist_id.startswith("RD"):
                res = self._ytm.get_watch_playlist(playlistId=playlist_id, limit=limit)
                tracks = res.get("tracks", [])
                return {
                    "title": res.get("title", "Radio / Podcast Mix"),
                    "trackCount": len(tracks),
                    "tracks": tracks
                }
            
            # Standard user-created playlists
            return self._ytm.get_playlist(playlist_id, limit=limit)
            
        self._dispatch(f"playlist:{playlist_id}", _run)
        
    def create_playlist(self, title: str, description: str = "", privacy: str = "PRIVATE"):
        def _run():
            return self._ytm.create_playlist(title, description, privacy)
        self._dispatch(f"create_playlist:{title}", _run)

    def add_playlist_items(self, playlist_id: str, video_ids: list[str]):
        def _run():
            return self._ytm.add_playlist_items(playlist_id, video_ids)
        self._dispatch(f"add_to_playlist:{playlist_id}", _run)

    def remove_playlist_items(self, playlist_id: str, videos: list[dict]):
        def _run():
            return self._ytm.remove_playlist_items(playlist_id, videos)
        self._dispatch(f"remove_from_playlist:{playlist_id}", _run)

    # ------------------------------------------------------------------
    # Album / Artist
    # ------------------------------------------------------------------

    def get_album(self, browse_id: str):
        def _run():
            return self._ytm.get_album(browse_id)
        self._dispatch(f"album:{browse_id}", _run)

    def get_artist(self, channel_id: str):
        def _run():
            return self._ytm.get_artist(channel_id)
        self._dispatch(f"artist:{channel_id}", _run)

    # ------------------------------------------------------------------
    # Song info / streaming URL
    # ------------------------------------------------------------------

    def get_song(self, video_id: str):
        def _run():
            return self._ytm.get_song(video_id)
        self._dispatch(f"song:{video_id}", _run)

    def get_watch_playlist(self, video_id: str, limit: int = 25):
        """Get up-next queue for a video."""
        def _run():
            return self._ytm.get_watch_playlist(videoId=video_id, limit=limit)
        self._dispatch(f"watch:{video_id}", _run)

    # ------------------------------------------------------------------
    # Thumbnail download (returns bytes)
    # ------------------------------------------------------------------

    def download_thumbnail(self, url: str, video_id: str):
        import urllib.request
        def _run():
            with urllib.request.urlopen(url, timeout=6) as resp:
                return resp.read()
        self._dispatch(f"thumb:{video_id}", _run)

    def add_history_item(self, video_id: str):
        """Record a played track in YTMusic history."""
        def _run():
            try:
                return self._ytm.add_history_item(video_id)
            except Exception as e:
                log.warning("Could not sync history (upstream ytmusicapi issue): %s", e)
                return None
        self._dispatch(f"add_history:{video_id}", _run)    
