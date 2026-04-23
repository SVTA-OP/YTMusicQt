"""
Track List Widget
A fast, virtual-scrolling-friendly list view for tracks.
"""
from __future__ import annotations

from typing import Optional
from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QVariant,
    pyqtSignal, QSize, QRect, QRectF
)
from PyQt6.QtWidgets import (
    QListView, QWidget, QStyledItemDelegate, QStyleOptionViewItem,
    QApplication, QMenu, QAbstractItemView, QStyle
)
from PyQt6.QtGui import (
    QPainter, QPixmap, QIcon, QColor, QFont, QFontMetrics, QPalette, QPainterPath
)

from app.workers.player_service import Track


class TrackModel(QAbstractListModel):
    """Model holding a flat list of tracks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._thumbnails: dict[str, QPixmap] = {}   # video_id → QPixmap
        self._playing_id: str = ""

    def set_tracks(self, tracks: list[Track]):
        self.beginResetModel()
        self._tracks = list(tracks)
        self.endResetModel()

    def append_tracks(self, tracks: list[Track]):
        if not tracks:
            return
        start = len(self._tracks)
        self.beginInsertRows(QModelIndex(), start, start + len(tracks) - 1)
        self._tracks.extend(tracks)
        self.endInsertRows()

    def track_at(self, index: int) -> Optional[Track]:
        if 0 <= index < len(self._tracks):
            return self._tracks[index]
        return None

    def all_tracks(self) -> list[Track]:
        return list(self._tracks)

    def set_thumbnail(self, video_id: str, data: bytes):
        px = QPixmap()
        if px.loadFromData(data):
            self._thumbnails[video_id] = px.scaled(
                48, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
        # Notify the affected row
        for i, t in enumerate(self._tracks):
            if t.video_id == video_id:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                break

    def set_playing(self, video_id: str):
        old = self._playing_id
        self._playing_id = video_id
        for i, t in enumerate(self._tracks):
            if t.video_id in (old, video_id):
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)

    # Qt interface
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._tracks)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        track = self._tracks[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return track.title
        if role == Qt.ItemDataRole.UserRole:
            return track
        if role == Qt.ItemDataRole.DecorationRole:
            return self._thumbnails.get(track.video_id)
        if role == Qt.ItemDataRole.UserRole + 1:
            return track.video_id == self._playing_id
        return None


ITEM_HEIGHT = 80
THUMB_SIZE  = 64
PAD         = 10


class TrackDelegate(QStyledItemDelegate):
    """Paints each track row: thumbnail | title + artist | duration"""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ITEM_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        palette = option.palette
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_playing  = index.data(Qt.ItemDataRole.UserRole + 1)
        track: Optional[Track] = index.data(Qt.ItemDataRole.UserRole)

        # Background
        if is_selected:
            painter.fillRect(option.rect, palette.highlight())
            text_color = palette.highlightedText().color()
        elif is_playing:
            bg = palette.highlight().color()
            bg.setAlpha(60)
            painter.fillRect(option.rect, bg)
            text_color = palette.text().color()
        else:
            text_color = palette.text().color()

        r = option.rect.adjusted(PAD, PAD, -PAD, -PAD)

        # Thumbnail
        thumb: Optional[QPixmap] = index.data(Qt.ItemDataRole.DecorationRole)
        thumb_rect_x = r.x()
        if thumb:
            dest = option.rect.adjusted(PAD, (ITEM_HEIGHT - THUMB_SIZE) // 2, 0, 0)
            dest.setWidth(THUMB_SIZE)
            dest.setHeight(THUMB_SIZE)
            painter.drawPixmap(dest, thumb)
        else:
            # Placeholder box
            placeholder = option.rect.adjusted(PAD, (ITEM_HEIGHT - THUMB_SIZE) // 2, 0, 0)
            placeholder.setWidth(THUMB_SIZE)
            placeholder.setHeight(THUMB_SIZE)
            placeholder_color = palette.mid().color()
            painter.fillRect(placeholder, placeholder_color)
            painter.setPen(palette.midlight().color())
            painter.drawRect(placeholder)

        text_x = thumb_rect_x + THUMB_SIZE + PAD * 2
        text_w = r.width() - THUMB_SIZE - PAD * 2 - 70

        # Title
        title_font = QFont(option.font)
        title_font.setPointSize(title_font.pointSize() + 2) # Larger font
        if is_playing:
            title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(text_color)
        title_fm = QFontMetrics(title_font)
        title = title_fm.elidedText(
            track.title if track else "Unknown",
            Qt.TextElideMode.ElideRight, text_w
        )
        title_y = option.rect.y() + ITEM_HEIGHT // 2 - 10
        painter.drawText(text_x, title_y + title_fm.ascent(), title)

        # Artist
        artist_font = QFont(option.font)
        artist_font.setPointSize(max(7, option.font.pointSize() - 1))
        painter.setFont(artist_font)
        dim_color = text_color
        dim_color.setAlpha(160)
        painter.setPen(dim_color)
        artist_fm = QFontMetrics(artist_font)
        artist = artist_fm.elidedText(
            track.artist if track else "",
            Qt.TextElideMode.ElideRight, text_w
        )
        painter.drawText(text_x, title_y + title_fm.ascent() + artist_fm.height() + 2, artist)

        # Duration (right-aligned)
        if track and track.duration_sec:
            dur_str = _fmt_duration(track.duration_sec)
            painter.setFont(artist_font)
            painter.setPen(dim_color)
            painter.drawText(
                option.rect.right() - PAD - artist_fm.horizontalAdvance(dur_str),
                option.rect.y() + ITEM_HEIGHT // 2 + artist_fm.ascent() // 2,
                dur_str,
            )

        # Playing indicator bar
        if is_playing:
            accent = palette.highlight().color()
            painter.fillRect(option.rect.x(), option.rect.y(), 3, option.rect.height(), accent)

        painter.restore()


def _fmt_duration(secs: int) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class TrackListView(QListView):
    """
    List view showing tracks with fast delegate-based rendering.
    """
    track_activated        = pyqtSignal(object, int)         # Track, index
    context_menu_requested = pyqtSignal(object, object)  # Track, QPoint

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = TrackModel(self)
        self.setModel(self._model)
        self.setItemDelegate(TrackDelegate(self))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        
        # Connect both single click and double click
        self.activated.connect(self._on_activated)
        self.clicked.connect(self._on_activated)

    @property
    def track_model(self) -> TrackModel:
        return self._model

    def set_tracks(self, tracks: list[Track]):
        self._model.set_tracks(tracks)

    def set_thumbnail(self, video_id: str, data: bytes):
        self._model.set_thumbnail(video_id, data)

    def set_playing(self, video_id: str):
        self._model.set_playing(video_id)

    def _on_activated(self, index: QModelIndex):
        track = self._model.track_at(index.row())
        if track:
            self.track_activated.emit(track, index.row())

    def _on_context_menu(self, pos):
        index = self.indexAt(pos)
        if not index.isValid():
            return
        track = self._model.track_at(index.row())
        if track:
            self.context_menu_requested.emit(track, self.mapToGlobal(pos))


CARD_WIDTH  = 160
CARD_HEIGHT = 220
IMAGE_SIZE  = 140
CARD_PAD    = 10

class CardDelegate(QStyledItemDelegate):
    """Paints each track as a Spotify-style card: Large Square Image -> Title -> Artist"""

    def sizeHint(self, option, index):
        return QSize(CARD_WIDTH, CARD_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = option.palette
        track: Optional[Track] = index.data(Qt.ItemDataRole.UserRole)

        # Subtle hover background
        if option.state & QStyle.StateFlag.State_MouseOver:
            hover_bg = palette.midlight().color()
            hover_bg.setAlpha(60)
            path = QPainterPath()
            path.addRoundedRect(QRectF(option.rect), 8, 8)
            painter.fillPath(path, hover_bg)

        # Calculate Image Box
        img_rect = QRect(
            option.rect.x() + CARD_PAD,
            option.rect.y() + CARD_PAD,
            IMAGE_SIZE, IMAGE_SIZE
        )

        # Draw Thumbnail with Rounded Corners
        thumb: Optional[QPixmap] = index.data(Qt.ItemDataRole.DecorationRole)
        if thumb and not thumb.isNull():
            scaled = thumb.scaled(
                IMAGE_SIZE, IMAGE_SIZE, 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                Qt.TransformationMode.SmoothTransformation
            )
            path = QPainterPath()
            path.addRoundedRect(QRectF(img_rect), 8, 8)
            painter.setClipPath(path)
            painter.drawPixmap(img_rect.topLeft(), scaled)
            painter.setClipping(False)
        else:
            # Fallback empty box
            path = QPainterPath()
            path.addRoundedRect(QRectF(img_rect), 8, 8)
            painter.fillPath(path, palette.mid().color())

        # Text Layout
        text_x = option.rect.x() + CARD_PAD
        text_w = IMAGE_SIZE
        title_y = img_rect.bottom() + 20

        # Draw Title (Bold)
        title_font = QFont(option.font)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette.text().color())
        
        title_fm = QFontMetrics(title_font)
        title_str = title_fm.elidedText(track.title if track else "Unknown", Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, title_y, title_str)

        # Draw Artist (Dimmed)
        artist_font = QFont(option.font)
        artist_font.setPointSize(max(8, artist_font.pointSize() - 1))
        painter.setFont(artist_font)
        
        dim_color = palette.text().color()
        dim_color.setAlpha(160)
        painter.setPen(dim_color)
        
        artist_fm = QFontMetrics(artist_font)
        artist_str = artist_fm.elidedText(track.artist if track else "", Qt.TextElideMode.ElideRight, text_w)
        painter.drawText(text_x, title_y + artist_fm.height() + 4, artist_str)

        painter.restore()


class HorizontalTrackListView(QListView):
    """A horizontal scrolling shelf for cards."""
    
    track_activated        = pyqtSignal(object, int)
    context_menu_requested = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = TrackModel(self)
        self.setModel(self._model)
        self.setItemDelegate(CardDelegate(self))
        
        # Configure for horizontal layout
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(CARD_HEIGHT + 10)
        self.setSpacing(0)
        self.setStyleSheet("QListView { border: none; background: transparent; outline: none; }")
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        
        # Connect both single click and double click
        self.activated.connect(self._on_activated)
        self.clicked.connect(self._on_activated)

    @property
    def track_model(self) -> TrackModel:
        return self._model

    def set_tracks(self, tracks: list[Track]):
        self._model.set_tracks(tracks)

    def set_thumbnail(self, video_id: str, data: bytes):
        self._model.set_thumbnail(video_id, data)

    def _on_activated(self, index: QModelIndex):
        track = self._model.track_at(index.row())
        if track:
            self.track_activated.emit(track, index.row())

    def _on_context_menu(self, pos):
        index = self.indexAt(pos)
        if index.isValid():
            track = self._model.track_at(index.row())
            if track:
                self.context_menu_requested.emit(track, self.mapToGlobal(pos))