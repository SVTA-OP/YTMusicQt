"""
Discord Rich Presence Service
Updates Discord RPC with current track info.
Gracefully handles Discord not being present.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

log = logging.getLogger(__name__)

APP_ID = "1234567890123456789"   # Replace with your Discord App ID


class DiscordRPCService(QObject):
    """
    Manages Discord Rich Presence updates.
    If pypresence / Discord is unavailable, silently does nothing.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rpc:     object = None
        self._enabled: bool   = False
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(False)
        self._retry_timer.setInterval(30_000)   # retry every 30 s
        self._retry_timer.timeout.connect(self._try_connect)
        self._last_update: dict = {}

        self._try_connect()
        self._retry_timer.start()

    def _try_connect(self):
        if self._enabled:
            return
        try:
            from pypresence import Presence
            rpc = Presence(APP_ID)
            rpc.connect()
            self._rpc     = rpc
            self._enabled = True
            self._retry_timer.stop()
            log.info("Discord RPC connected")
        except Exception:
            pass   # Discord not running or pypresence not installed — silent

    def update(
        self,
        title:    str,
        artist:   str,
        is_playing: bool,
        position_sec: int = 0,
        duration_sec: int = 0,
    ):
        if not self._enabled or self._rpc is None:
            return

        update_data: dict = {
            "details": title[:128] if title else "Unknown",
            "state":   f"by {artist[:128]}" if artist else "Unknown artist",
            "large_image": "ytmusic_logo",
            "large_text":  "YouTube Music Desktop",
            "small_image": "playing" if is_playing else "paused",
            "small_text":  "Playing" if is_playing else "Paused",
            "buttons": [
                {"label": "YouTube Music", "url": "https://music.youtube.com"},
            ],
        }

        if is_playing and duration_sec > 0 and position_sec < duration_sec:
            now = int(time.time())
            update_data["start"] = now - position_sec
            update_data["end"]   = now + (duration_sec - position_sec)

        # Avoid unnecessary updates
        if update_data == self._last_update:
            return
        self._last_update = update_data

        try:
            self._rpc.update(**update_data)
        except Exception as exc:
            log.warning("Discord RPC update failed: %s", exc)
            self._enabled = False
            self._rpc     = None
            self._retry_timer.start()

    def clear(self):
        if not self._enabled or self._rpc is None:
            return
        try:
            self._rpc.clear()
        except Exception:
            pass

    def close(self):
        self._retry_timer.stop()
        self.clear()
        if self._rpc:
            try:
                self._rpc.close()
            except Exception:
                pass
        self._enabled = False
        self._rpc     = None

    @property
    def is_connected(self) -> bool:
        return self._enabled
