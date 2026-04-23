"""
Player Service
Extracts streaming URLs via yt-dlp on a background thread,
then feeds them to QMediaPlayer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from PyQt6.QtCore import (
    QObject, QRunnable, QThreadPool, QTimer,
    pyqtSignal, pyqtSlot, Qt,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

log = logging.getLogger(__name__)


@dataclass
class Track:
    video_id:     str
    title:        str       = ""
    artist:       str       = ""
    album:        str       = ""
    duration_sec: int       = 0
    thumbnail_url: str      = ""
    thumbnail_data: Optional[bytes] = field(default=None, repr=False)


class _ExtractTask(QRunnable):
    """Runs yt-dlp in a thread to get the best audio stream URL."""

    class Signals(QObject):
        done  = pyqtSignal(str, str)   # (video_id, stream_url)
        error = pyqtSignal(str, str)   # (video_id, message)

    def __init__(self, video_id: str):
        super().__init__()
        self.video_id = video_id
        self.signals  = self.Signals()

    @pyqtSlot()
    def run(self):
        try:
            import yt_dlp
            ydl_opts: Any = {
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "skip_download": True,
            }
            url = f"https://music.youtube.com/watch?v={self.video_id}"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            stream_url = info.get("url")
            if not stream_url:
                formats = info.get("formats") or []
                if not formats or not formats[-1].get("url"):
                    raise RuntimeError("No stream URL found in yt-dlp metadata")
                stream_url = formats[-1]["url"]
            self.signals.done.emit(self.video_id, stream_url)
        except Exception as exc:
            log.exception("yt-dlp extraction failed for %s", self.video_id)
            self.signals.error.emit(self.video_id, str(exc))


class PlayerService(QObject):
    """
    Manages playback state.
    Signals (all emitted on the main thread):
      state_changed(state_str)   — "playing" | "paused" | "stopped" | "loading" | "error"
      position_changed(ms)
      duration_changed(ms)
      track_changed(Track)
      volume_changed(float)      — 0.0..1.0
      queue_changed()
      error(message)
    """

    state_changed    = pyqtSignal(str)
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)
    track_changed    = pyqtSignal(object)   # Track
    volume_changed   = pyqtSignal(float)
    queue_changed    = pyqtSignal()
    error            = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player       = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.7)

        pool = QThreadPool.globalInstance()
        assert pool is not None
        self._pool: QThreadPool = pool
        self._queue: list[Track] = []
        self._queue_index: int       = -1
        self._current: Optional[Track] = None
        self._prefetch_pending: set[str] = set()
        self._prefetched: dict[str, str] = {}   # video_id → stream_url
        self._shuffle = False
        self._repeat  = "off"  # off | one | all

        # Wire Qt media player signals
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.positionChanged.connect(lambda p: self.position_changed.emit(p))
        self._player.durationChanged.connect(lambda d: self.duration_changed.emit(d))
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def set_queue(self, tracks: list[Track], start_index: int = 0):
        self._queue = list(tracks)
        self._queue_index = start_index
        self.queue_changed.emit()
        self.play_index(start_index)

    def append_to_queue(self, tracks: list[Track]):
        self._queue.extend(tracks)
        self.queue_changed.emit()

    def clear_queue(self):
        self._queue.clear()
        self._queue_index = -1
        self.queue_changed.emit()

    def get_queue(self) -> list[Track]:
        return list(self._queue)

    def get_queue_index(self) -> int:
        return self._queue_index

    # ------------------------------------------------------------------
    # Playback controls
    # ------------------------------------------------------------------

    def play_track(self, track: Track):
        self._current = track
        self.track_changed.emit(track)
        self.state_changed.emit("loading")

        if track.video_id in self._prefetched:
            self._start_stream(track.video_id, self._prefetched.pop(track.video_id))
        else:
            self._extract_stream(track.video_id)

    def play_index(self, index: int):
        if 0 <= index < len(self._queue):
            self._queue_index = index
            self.play_track(self._queue[index])

    def play(self):
        self._player.play()

    def pause(self):
        self._player.pause()

    def toggle_play_pause(self):
        s = self._player.playbackState()
        if s == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def next(self):
        if not self._queue:
            return
        if self._repeat == "one":
            self.play_index(self._queue_index)
            return
        nxt = self._queue_index + 1
        if nxt >= len(self._queue):
            if self._repeat == "all":
                nxt = 0
            else:
                self.state_changed.emit("stopped")
                return
        self.play_index(nxt)

    def previous(self):
        # If >3 s in, restart. Else go back.
        if self._player.position() > 3000:
            self._player.setPosition(0)
        else:
            prev = max(0, self._queue_index - 1)
            self.play_index(prev)

    def seek(self, ms: int):
        self._player.setPosition(ms)

    def set_volume(self, vol: float):
        self._audio_output.setVolume(max(0.0, min(1.0, vol)))
        self.volume_changed.emit(vol)

    def get_volume(self) -> float:
        return self._audio_output.volume()

    def set_repeat(self, mode: str):   # off | one | all
        self._repeat = mode

    def set_shuffle(self, on: bool):
        self._shuffle = on

    @property
    def current_track(self) -> Optional[Track]:
        return self._current

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_stream(self, video_id: str):
        if video_id in self._prefetch_pending:
            return
        self._prefetch_pending.add(video_id)
        task = _ExtractTask(video_id)
        task.signals.done.connect(self._on_stream_ready)
        task.signals.error.connect(self._on_stream_error)
        self._pool.start(task)

    def _start_stream(self, video_id: str, url: str):
        if self._current and self._current.video_id == video_id:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QMediaPlayer
            self._player.setSource(QUrl(url))
            self._player.play()
            # Prefetch next track
            QTimer.singleShot(2000, self._prefetch_next)

    @pyqtSlot(str, str)
    def _on_stream_ready(self, video_id: str, url: str):
        self._prefetch_pending.discard(video_id)
        if self._current and self._current.video_id == video_id:
            self._start_stream(video_id, url)
        else:
            # Prefetched for future use
            self._prefetched[video_id] = url

    @pyqtSlot(str, str)
    def _on_stream_error(self, video_id: str, message: str):
        self._prefetch_pending.discard(video_id)
        if self._current and self._current.video_id == video_id:
            self.error.emit(f"Stream extraction failed: {message}")
            self.state_changed.emit("error")

    def _prefetch_next(self):
        nxt = self._queue_index + 1
        if 0 <= nxt < len(self._queue):
            vid = self._queue[nxt].video_id
            if vid not in self._prefetched and vid not in self._prefetch_pending:
                self._extract_stream(vid)

    def _on_playback_state(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer as MP
        mapping = {
            MP.PlaybackState.PlayingState: "playing",
            MP.PlaybackState.PausedState:  "paused",
            MP.PlaybackState.StoppedState: "stopped",
        }
        self.state_changed.emit(mapping.get(state, "stopped"))

    def _on_media_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer as MP
        if status == MP.MediaStatus.EndOfMedia:
            self.next()

    def _on_error(self, error, error_string: str):
        self.error.emit(error_string)
        self.state_changed.emit("error")
