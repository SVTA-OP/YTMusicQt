"""
Player Bar Widget
Bottom bar with album art, track info, transport controls, seek and volume.
Uses system palette / Breeze style — no hardcoded colours.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSlider, QPushButton, QSizePolicy, QFrame,
)
from PyQt6.QtGui import QPixmap, QIcon, QFont, QPalette, QColor

from app.workers.player_service import PlayerService, Track


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"


class PlayerBar(QWidget):
    """Full-width player controls bar — native KDE/Breeze styled."""

    next_requested     = pyqtSignal()
    previous_requested = pyqtSignal()

    def __init__(self, player: PlayerService, parent=None):
        super().__init__(parent)
        self._player  = player
        self._seeking = False
        self._repeat  = "off"   # off | one | all
        self._shuffle = False

        self.setFixedHeight(90)
        self.setObjectName("PlayerBar")
        # Use AutoFillBackground so the widget paints using the window palette.
        # A 1-px top separator is drawn via a QFrame above the bar (see window.py).
        self.setAutoFillBackground(True)

        self._build_ui()
        self._connect_player()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(0)

        # ---- Left: album art + track info ----
        left = QHBoxLayout()
        left.setSpacing(10)

        self._art_label = QLabel()
        self._art_label.setFixedSize(64, 64)
        self._art_label.setScaledContents(True)
        # Breeze-friendly: use AlternateBase for the placeholder
        self._art_label.setAutoFillBackground(True)
        art_pal = self._art_label.palette()
        art_pal.setColor(QPalette.ColorRole.Window, art_pal.color(QPalette.ColorRole.AlternateBase))
        self._art_label.setPalette(art_pal)
        left.addWidget(self._art_label)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        info_col.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel("Nothing playing")
        self._title_label.setFont(QFont(self.font().family(), -1, QFont.Weight.Bold))
        self._title_label.setMaximumWidth(220)
        info_col.addWidget(self._title_label)

        self._artist_label = QLabel("")
        self._artist_label.setMaximumWidth(220)
        info_col.addWidget(self._artist_label)

        self._like_btn = QPushButton("♡")
        self._like_btn.setFlat(True)
        self._like_btn.setFixedWidth(28)
        self._like_btn.setToolTip("Like")
        info_col.addWidget(self._like_btn)

        left.addLayout(info_col)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(260)
        root.addWidget(left_widget)

        # ---- Centre: transport + seek ----
        centre = QVBoxLayout()
        centre.setSpacing(4)

        transport = QHBoxLayout()
        transport.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        transport.setSpacing(4)

        def _tbtn(text: str, tooltip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setFlat(True)
            b.setFixedSize(36, 36)
            b.setToolTip(tooltip)
            return b

        self._shuffle_btn = _tbtn("⇄", "Shuffle")
        self._prev_btn    = _tbtn("⏮", "Previous")
        self._play_btn    = _tbtn("▶", "Play / Pause")
        self._play_btn.setFixedSize(44, 44)
        self._next_btn    = _tbtn("⏭", "Next")
        self._repeat_btn  = _tbtn("↻", "Repeat")

        self._shuffle_btn.clicked.connect(self._toggle_shuffle)
        self._prev_btn.clicked.connect(self._player.previous)
        self._play_btn.clicked.connect(self._player.toggle_play_pause)
        self._next_btn.clicked.connect(self._player.next)
        self._repeat_btn.clicked.connect(self._cycle_repeat)

        for b in (self._shuffle_btn, self._prev_btn, self._play_btn,
                  self._next_btn, self._repeat_btn):
            transport.addWidget(b)

        centre.addLayout(transport)

        # Seek row
        seek_row = QHBoxLayout()
        seek_row.setSpacing(6)

        self._pos_label = QLabel("0:00")
        self._pos_label.setFixedWidth(36)
        self._pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self._seek_slider.sliderReleased.connect(self._on_seek_released)

        self._dur_label = QLabel("0:00")
        self._dur_label.setFixedWidth(36)

        seek_row.addWidget(self._pos_label)
        seek_row.addWidget(self._seek_slider, 1)
        seek_row.addWidget(self._dur_label)
        centre.addLayout(seek_row)

        root.addLayout(centre, 1)

        # ---- Right: volume ----
        right = QHBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setSpacing(6)

        self._vol_icon = QLabel("🔊")
        self._vol_icon.setFixedWidth(24)

        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(70)
        self._vol_slider.setFixedWidth(90)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)

        right.addWidget(self._vol_icon)
        right.addWidget(self._vol_slider)

        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(160)
        root.addWidget(right_widget)

    # ------------------------------------------------------------------
    # Player signal connections
    # ------------------------------------------------------------------

    def _connect_player(self):
        p = self._player
        p.state_changed.connect(self._on_state)
        p.position_changed.connect(self._on_position)
        p.duration_changed.connect(self._on_duration)
        p.track_changed.connect(self._on_track)
        p.volume_changed.connect(self._on_volume_signal)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_state(self, state: str):
        icons = {
            "playing": "⏸",
            "paused":  "▶",
            "stopped": "▶",
            "loading": "⏳",
            "error":   "⚠",
        }
        self._play_btn.setText(icons.get(state, "▶"))

    def _on_position(self, ms: int):
        if self._seeking:
            return
        self._pos_label.setText(_fmt(ms))
        dur = self._player.duration()
        if dur > 0:
            self._seek_slider.setValue(int(ms * 1000 / dur))

    def _on_duration(self, ms: int):
        self._dur_label.setText(_fmt(ms))

    def _on_track(self, track: Track):
        self._title_label.setText(self._elide(track.title, 28))
        self._artist_label.setText(self._elide(track.artist, 32))
        self._art_label.clear()
        # Reset album art placeholder
        art_pal = self._art_label.palette()
        art_pal.setColor(QPalette.ColorRole.Window, self.palette().color(QPalette.ColorRole.AlternateBase))
        self._art_label.setPalette(art_pal)

    def set_thumbnail(self, data: bytes):
        px = QPixmap()
        if px.loadFromData(data):
            self._art_label.setPixmap(
                px.scaled(64, 64,
                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
            )

    def _on_seek_released(self):
        self._seeking = False
        dur = self._player.duration()
        if dur > 0:
            pos = int(self._seek_slider.value() * dur / 1000)
            self._player.seek(pos)

    def _on_volume_changed(self, val: int):
        self._player.set_volume(val / 100.0)
        if val == 0:
            self._vol_icon.setText("🔇")
        elif val < 40:
            self._vol_icon.setText("🔈")
        elif val < 70:
            self._vol_icon.setText("🔉")
        else:
            self._vol_icon.setText("🔊")

    def _on_volume_signal(self, vol: float):
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(int(vol * 100))
        self._vol_slider.blockSignals(False)

    def _toggle_shuffle(self):
        self._shuffle = not self._shuffle
        self._player.set_shuffle(self._shuffle)
        # Use highlight colour from palette — no hardcoded hex
        hl = self.palette().color(QPalette.ColorRole.Highlight).name()
        self._shuffle_btn.setStyleSheet(f"color: {hl};" if self._shuffle else "")

    def _cycle_repeat(self):
        modes  = ["off", "all", "one"]
        icons  = {"off": "↻", "all": "↻", "one": "🔂"}
        hl = self.palette().color(QPalette.ColorRole.Highlight).name()
        self._repeat = modes[(modes.index(self._repeat) + 1) % 3]
        self._player.set_repeat(self._repeat)
        self._repeat_btn.setText(icons[self._repeat])
        self._repeat_btn.setStyleSheet(f"color: {hl};" if self._repeat != "off" else "")

    @staticmethod
    def _elide(text: str, max_chars: int) -> str:
        if len(text) > max_chars:
            return text[:max_chars - 1] + "…"
        return text
