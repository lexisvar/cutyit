"""Video player with live real-time subtitle overlay.

Architecture
────────────
Uses a QGraphicsScene with two stacked items:
  Z=0  QGraphicsVideoItem  — hardware-decoded video frames
  Z=10 _SubtitleItem       — transparent item that paints subtitles
                             with proper outline / shadow / box effects
                             via QPainterPath (supports anti-aliased stroke).

SubtitleOverlayPlayer is a drop-in replacement for VideoPlayerWidget.
Same public API: load/play/pause/stop/toggle_play/seek/position/duration,
signals duration_changed(int) and position_changed(int).

Extra API
─────────
set_subtitle_rows(rows)   rows = [(start_ms, end_ms, text), ...]
set_subtitle_style(style) style = SubtitleStyle instance
"""
from __future__ import annotations

import math
import re
import time

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QSizePolicy, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsObject, QComboBox,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QRectF, QPointF, QSizeF, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QFont, QFontMetrics, QBrush, QPainterPath,
)

from src.ui.subtitle_style import SubtitleStyle, PRESETS, _should_emphasize


# ─────────────────────────────────────────────────────────────────────────── #
#  Word Emphasis AI  (defined in subtitle_style, re-exported here)            #
# ─────────────────────────────────────────────────────────────────────────── #


def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


# ═══════════════════════════════════════════════════════════════════════════ #
#  Graphics item                                                              #
# ═══════════════════════════════════════════════════════════════════════════ #

class _SubtitleItem(QGraphicsObject):
    """Transparent QGraphicsObject that paints the active subtitle over the video.

    Positioned at (0,0) in scene coordinates; the scene rect matches the
    video's native resolution so all measurements scale automatically with
    the view transform.
    """

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[int, int, str]] = []
        self._word_rows: list[list[tuple[int, int, str]]] = []
        self._position_ms: int = 0
        self._style: SubtitleStyle = PRESETS["TikTok"].clone()
        self._scene_w: float = 1280.0
        self._scene_h: float = 720.0
        # Drag state
        self._drag_offset: QPointF = QPointF(0.0, 0.0)
        self._dragging: bool = False
        self._drag_start_scene: QPointF = QPointF(0.0, 0.0)
        self._drag_start_offset: QPointF = QPointF(0.0, 0.0)
        self._text_rect: QRectF = QRectF()   # updated each frame for hit-testing
        self._on_drag_end: object = None     # callable(dx_scene, dy_scene) | None
        # Pop-animation state (60 fps timer, runs only during the 220 ms pop window)
        self._anim_timer: QTimer = QTimer()
        self._anim_timer.setInterval(16)      # ~60 fps
        self._anim_timer.timeout.connect(self.update)
        self._anim_start_time: float = 0.0   # wall-clock ms when current word began
        self._anim_word_key: str = ""        # unique key per active word
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)

    # ------------------------------------------------------------------ #
    #  Public setters (all trigger a repaint)                             #
    # ------------------------------------------------------------------ #

    def set_scene_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._scene_w = w
        self._scene_h = h

    def set_rows(self, rows: list[tuple[int, int, str]]) -> None:
        self._rows = rows
        if not rows:
            self._drag_offset = QPointF(0.0, 0.0)
            self._anim_timer.stop()
            self._anim_word_key = ""
        self.update()

    def set_word_rows(self, word_rows: list) -> None:
        self._word_rows = word_rows
        self.update()

    def reset_drag(self) -> None:
        self._drag_offset = QPointF(0.0, 0.0)
        if self._on_drag_end is not None:
            self._on_drag_end(0.0, 0.0)
        self.update()

    def set_position(self, ms: int) -> None:
        self._position_ms = ms
        self.update()

    def set_style(self, style: SubtitleStyle) -> None:
        self._style = style
        self.update()

    # ------------------------------------------------------------------ #
    #  QGraphicsItem interface                                            #
    # ------------------------------------------------------------------ #

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self._scene_w, self._scene_h)

    # ------------------------------------------------------------------ #
    #  Mouse / hover (drag to reposition; double-click to reset)         #
    # ------------------------------------------------------------------ #

    def hoverMoveEvent(self, event) -> None:
        if self._text_rect.contains(event.pos()):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._text_rect.contains(event.pos()):
            self._dragging = True
            self._drag_start_scene = QPointF(event.pos())
            self._drag_start_offset = QPointF(self._drag_offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            delta = event.pos() - self._drag_start_scene
            self._drag_offset = QPointF(
                self._drag_start_offset.x() + delta.x(),
                self._drag_start_offset.y() + delta.y(),
            )
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._on_drag_end is not None:
                self._on_drag_end(self._drag_offset.x(), self._drag_offset.y())
            event.accept()
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._text_rect.contains(event.pos()):
            self._drag_offset = QPointF(0.0, 0.0)
            if self._on_drag_end is not None:
                self._on_drag_end(0.0, 0.0)
            self.update()
            event.accept()
        else:
            event.ignore()

    # ------------------------------------------------------------------ #
    #  Painting                                                           #
    # ------------------------------------------------------------------ #

    def paint(self, painter: QPainter, _option, _widget=None) -> None:  # noqa: N802
        # ── Find the subtitle active at the current position ─────── #
        text = ""
        active_idx = -1
        for i, (start_ms, end_ms, t) in enumerate(self._rows):
            if start_ms <= self._position_ms < end_ms:
                text = t.strip()
                active_idx = i
                break
        if not text:
            self._text_rect = QRectF()
            return

        s = self._style
        w, h = self._scene_w, self._scene_h
        scale = min(w / 1920.0, h / 1080.0)

        # ── Font ─────────────────────────────────────────────────── #
        font_size = max(6, int(s.font_size * scale))
        font = QFont(s.font_family, font_size)
        font.setBold(s.bold)
        font.setItalic(s.italic)
        if s.spacing > 0.0:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, s.spacing * scale)

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        text_h = fm.height()

        # ── Word-effect data ─────────────────────────────────────── #
        active_words: list[tuple[int, int, str]] = []
        if s.word_effect != "none" and 0 <= active_idx < len(self._word_rows):
            active_words = self._word_rows[active_idx]

        # ── Placement (ASS numpad alignment) ─────────────────────── #
        a = s.alignment
        mv = s.margin_vertical * scale
        ml = s.margin_left  * scale
        mr = s.margin_right * scale

        if a in (7, 8, 9):
            baseline_y = mv + fm.ascent()
        elif a in (4, 5, 6):
            baseline_y = (h - text_h) / 2.0 + fm.ascent()
        else:
            baseline_y = h - mv - fm.descent()

        if a in (1, 4, 7):
            text_x = ml
        elif a in (3, 6, 9):
            text_x = w - mr - text_w
        else:
            text_x = (w - text_w) / 2.0

        # Apply drag offset
        text_x    += self._drag_offset.x()
        baseline_y += self._drag_offset.y()

        # Cache hit-test rect
        pad_x = 12.0 * scale
        pad_y =  6.0 * scale
        self._text_rect = QRectF(
            text_x - pad_x,
            baseline_y - fm.ascent() - pad_y,
            text_w + pad_x * 2.0,
            text_h + pad_y * 2.0,
        )

        # ── Route to renderer ─────────────────────────────────────── #
        if active_words:
            self._paint_words(painter, active_words, text_x, baseline_y, font, fm, scale)
        else:
            self._paint_full(painter, text, text_x, baseline_y, text_w, text_h, font, fm, scale)

    def _paint_full(self, painter, text, text_x, baseline_y, text_w, text_h, font, fm, scale):
        """Standard full-line rendering."""
        s = self._style

        if s.border_style == 3:
            br, bg, bb, ba = s.back_color
            pad_x = 10.0 * scale
            pad_y =  5.0 * scale
            painter.fillRect(
                QRectF(
                    text_x - pad_x,
                    baseline_y - fm.ascent() - pad_y,
                    text_w + pad_x * 2.0,
                    text_h + pad_y * 2.0,
                ),
                QColor(br, bg, bb, ba),
            )

        path = QPainterPath()
        path.addText(QPointF(text_x, baseline_y), font, text)

        if s.shadow_depth > 0.0:
            sd = s.shadow_depth * scale
            or_, og, ob, _ = s.outline_color
            sp = QPainterPath()
            sp.addText(QPointF(text_x + sd, baseline_y + sd), font, text)
            painter.fillPath(sp, QBrush(QColor(or_, og, ob, 150)))

        if s.outline_width > 0.0:
            or_, og, ob, oa = s.outline_color
            pen = QPen(QColor(or_, og, ob, oa))
            pen.setWidthF(s.outline_width * scale * 2.2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        pr, pg, pb, pa = s.primary_color
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, QBrush(QColor(pr, pg, pb, pa)))

    def _paint_words(self, painter, word_rows, text_x, baseline_y, font, fm, scale):
        """Word-by-word rendering with highlight colour, scale pop, and glow."""
        s = self._style

        # ── Find which word is spoken right now ──────────────────────── #
        active_w_start = -1
        for w_start, w_end, _ in word_rows:
            if w_start <= self._position_ms < w_end:
                active_w_start = w_start
                break

        # ── Restart pop animation when active word changes ───────────── #
        word_key = str(active_w_start)
        if active_w_start >= 0 and word_key != self._anim_word_key:
            self._anim_word_key = word_key
            self._anim_start_time = time.monotonic() * 1000.0
            if not self._anim_timer.isActive():
                self._anim_timer.start()

        # ── Compute pop-animation scale contribution ──────────────────── #
        ANIM_MS = 220.0
        elapsed = time.monotonic() * 1000.0 - self._anim_start_time
        if elapsed >= ANIM_MS and self._anim_timer.isActive():
            self._anim_timer.stop()
        t_norm = max(0.0, min(elapsed / ANIM_MS, 1.0))
        pop_extra = 0.18 * math.sin(t_norm * math.pi)   # 0 → 0.18 → 0 bell curve

        # ── Draw each word ────────────────────────────────────────────── #
        x = text_x
        for w_start, w_end, word in word_rows:
            word = word.strip()
            spaced = word + " "
            word_w = fm.horizontalAdvance(spaced)

            if s.word_effect == "appear" and w_start > self._position_ms:
                x += word_w
                continue

            is_active = (w_start == active_w_start) and active_w_start >= 0

            if s.word_effect == "ai_emphasis":
                is_em = _should_emphasize(word)
                fill = s.highlight_color if (is_active or is_em) else s.primary_color
                ws = (1.12 + pop_extra) if is_active else (1.08 if is_em else 1.0)
                do_glow = is_active or is_em
            else:
                fill = s.highlight_color if is_active else s.primary_color
                ws = (1.12 + pop_extra) if is_active else 1.0
                do_glow = is_active

            path = QPainterPath()
            path.addText(QPointF(x, baseline_y), font, spaced)

            # Scale transform centred on this word
            needs_scale = ws > 1.001
            if needs_scale:
                word_cx = x + word_w / 2.0
                word_cy = baseline_y - fm.height() / 2.0
                painter.save()
                painter.translate(word_cx, word_cy)
                painter.scale(ws, ws)
                painter.translate(-word_cx, -word_cy)

            # Glow (drawn first so it sits behind outline and fill)
            if do_glow:
                gr, gg, gb, _ = s.highlight_color
                for gw_f, ga in ((11.0, 18), (7.5, 32), (4.5, 52), (2.0, 72)):
                    gp = QPen(QColor(gr, gg, gb, ga))
                    gp.setWidthF(gw_f * scale)
                    gp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    gp.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(gp)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)

            # Shadow
            if s.shadow_depth > 0.0:
                sd = s.shadow_depth * scale
                or_, og, ob, _ = s.outline_color
                sp = QPainterPath()
                sp.addText(QPointF(x + sd, baseline_y + sd), font, spaced)
                painter.fillPath(sp, QBrush(QColor(or_, og, ob, 120)))

            # Outline
            if s.outline_width > 0.0:
                or_, og, ob, oa = s.outline_color
                pen = QPen(QColor(or_, og, ob, oa))
                pen.setWidthF(s.outline_width * scale * 2.2)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)

            # Fill
            r, g, b, av = fill
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(path, QBrush(QColor(r, g, b, av)))

            if needs_scale:
                painter.restore()

            x += word_w


# ═══════════════════════════════════════════════════════════════════════════ #
#  Safe-zone overlay item                                                     #
# ═══════════════════════════════════════════════════════════════════════════ #

_SAFE_ZONE_CONFIGS: dict[str, dict] = {
    "TikTok": {
        "top": 0.12, "bottom": 0.22, "right": 0.12, "left": 0.0,
        "color": QColor(255, 60, 60, 55),
        "border": QColor(255, 100, 100, 200),
    },
    "Reels": {
        "top": 0.10, "bottom": 0.20, "right": 0.10, "left": 0.0,
        "color": QColor(255, 160, 40, 55),
        "border": QColor(255, 180, 80, 200),
    },
    "Shorts": {
        "top": 0.08, "bottom": 0.18, "right": 0.0, "left": 0.0,
        "color": QColor(255, 50, 50, 55),
        "border": QColor(255, 80, 80, 200),
    },
}


class _SafeZoneItem(QGraphicsItem):
    """Overlay that marks platform UI danger zones on the preview canvas.

    Shaded rectangles show where platform chrome (nav bar, like buttons, etc.)
    overlaps the video.  A dashed border shows the safe subtitle region.
    """

    def __init__(self) -> None:
        super().__init__()
        self._platform: str | None = None
        self._scene_w: float = 1280.0
        self._scene_h: float = 720.0
        self.setZValue(20)  # above _SubtitleItem (Z=10)
        self.setVisible(False)

    def set_scene_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._scene_w = w
        self._scene_h = h
        self.update()

    def set_platform(self, platform: str | None) -> None:
        self._platform = platform
        self.setVisible(bool(platform) and platform in _SAFE_ZONE_CONFIGS)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(0.0, 0.0, self._scene_w, self._scene_h)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:  # noqa: N802
        if not self._platform or self._platform not in _SAFE_ZONE_CONFIGS:
            return
        cfg = _SAFE_ZONE_CONFIGS[self._platform]
        w, h = self._scene_w, self._scene_h
        c    = cfg["color"]
        bc   = cfg["border"]

        top_h = h * cfg["top"]
        bot_h = h * cfg["bottom"]
        rgt_w = w * cfg["right"]
        lft_w = w * cfg["left"]

        # Danger zone fills
        if top_h > 0:
            painter.fillRect(QRectF(0, 0, w, top_h), c)
        if bot_h > 0:
            painter.fillRect(QRectF(0, h - bot_h, w, bot_h), c)
        if rgt_w > 0:
            painter.fillRect(QRectF(w - rgt_w, top_h, rgt_w, h - top_h - bot_h), c)
        if lft_w > 0:
            painter.fillRect(QRectF(0, top_h, lft_w, h - top_h - bot_h), c)

        # Safe-region dashed border
        pen = QPen(bc, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(lft_w, top_h, w - lft_w - rgt_w, h - top_h - bot_h))

        # Zone labels
        label_font = QFont("Arial", max(7, int(min(w, h) * 0.018)))
        painter.setFont(label_font)
        painter.setPen(bc)
        if top_h > 0:
            painter.drawText(
                QRectF(0, 0, w, top_h),
                Qt.AlignmentFlag.AlignCenter,
                f"{self._platform} Top UI",
            )
        if bot_h > 0:
            painter.drawText(
                QRectF(0, h - bot_h, w, bot_h),
                Qt.AlignmentFlag.AlignCenter,
                f"{self._platform} Bottom UI",
            )


# ═══════════════════════════════════════════════════════════════════════════ #
#  Player widget                                                              #
# ═══════════════════════════════════════════════════════════════════════════ #

class SubtitleOverlayPlayer(QWidget):
    """Video player with a live subtitle overlay rendered in the graphics scene."""

    duration_changed = pyqtSignal(int)          # ms
    position_changed = pyqtSignal(int)          # ms
    drag_position_changed = pyqtSignal(float, float)  # dx, dy in PlayRes (1920x1080) units
    video_native_size_changed = pyqtSignal(int, int)  # native video width, height (px)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration: int = 0
        self._user_seeking = False

        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.7)

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ #
    #  UI construction                                                     #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Scene / view ────────────────────────────────────────────── #
        self._scene = QGraphicsScene(self)
        self._video_item = QGraphicsVideoItem()
        self._scene.addItem(self._video_item)
        self._player.setVideoOutput(self._video_item)

        self._sub_item = _SubtitleItem()
        self._sub_item._on_drag_end = self._on_sub_drag_end
        self._scene.addItem(self._sub_item)

        self._safe_zone_item = _SafeZoneItem()
        self._scene.addItem(self._safe_zone_item)

        self._view = QGraphicsView(self._scene)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setBackgroundBrush(QBrush(QColor(0, 0, 0)))
        self._view.setStyleSheet("border: none; outline: none;")
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._view.setMinimumHeight(260)
        layout.addWidget(self._view, 1)

        # ── Controls bar ─────────────────────────────────────────────── #
        bar = QWidget()
        bar.setObjectName("player_controls")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(10, 7, 10, 8)
        bar_layout.setSpacing(6)

        # Seek bar
        self._seek_bar = QSlider(Qt.Orientation.Horizontal)
        self._seek_bar.setRange(0, 0)
        self._seek_bar.setObjectName("seek_bar")
        bar_layout.addWidget(self._seek_bar)

        # Transport row
        row = QHBoxLayout()
        row.setSpacing(8)

        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedSize(40, 36)
        self._btn_play.setObjectName("btn_play_primary")
        self._btn_play.setToolTip("Play / Pause  (Space)")
        row.addWidget(self._btn_play)

        self._lbl_time = QLabel("00:00 / 00:00")
        self._lbl_time.setObjectName("lbl_timecode")
        row.addWidget(self._lbl_time)

        row.addStretch()

        # Live-preview badge  (hidden until subtitles are loaded)
        self._badge = QLabel("● SUBTITLE PREVIEW")
        self._badge.setObjectName("sub_preview_badge")
        self._badge.hide()
        row.addWidget(self._badge)

        row.addSpacing(6)

        # Safe-zone overlay toggle
        self._safe_zone_cb = QComboBox()
        self._safe_zone_cb.addItems(["Off", "TikTok", "Reels", "Shorts"])
        self._safe_zone_cb.setFixedWidth(78)
        self._safe_zone_cb.setToolTip("Show platform safe-zone overlay on the preview")
        row.addWidget(self._safe_zone_cb)

        row.addSpacing(6)
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("color: #8b949e; font-size: 13px;")
        row.addWidget(vol_icon)

        self._vol_bar = QSlider(Qt.Orientation.Horizontal)
        self._vol_bar.setRange(0, 100)
        self._vol_bar.setValue(70)
        self._vol_bar.setFixedWidth(80)
        self._vol_bar.setObjectName("vol_bar")
        self._vol_bar.setToolTip("Volume")
        row.addWidget(self._vol_bar)

        bar_layout.addLayout(row)
        layout.addWidget(bar)

    def _connect_signals(self) -> None:
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_state)
        self._video_item.nativeSizeChanged.connect(self._on_native_size)
        self._player.errorOccurred.connect(
            lambda err, msg: print(f"[MediaPlayer] {err}: {msg}")
        )

        self._btn_play.clicked.connect(self.toggle_play)
        self._seek_bar.sliderPressed.connect(
            lambda: setattr(self, "_user_seeking", True)
        )
        self._seek_bar.sliderReleased.connect(self._on_seek_released)
        self._seek_bar.sliderMoved.connect(self._on_seek_moved)
        self._vol_bar.valueChanged.connect(
            lambda v: self._audio.setVolume(v / 100.0)
        )
        self._safe_zone_cb.currentTextChanged.connect(self._on_safe_zone_changed)

    # ------------------------------------------------------------------ #
    #  Slots                                                               #
    # ------------------------------------------------------------------ #

    def _on_native_size(self, size: QSizeF) -> None:
        if size.width() > 0 and size.height() > 0:
            self._video_item.setSize(size)
            self._scene.setSceneRect(0.0, 0.0, size.width(), size.height())
            self._sub_item.set_scene_size(size.width(), size.height())
            self._safe_zone_item.set_scene_size(size.width(), size.height())
            self._view.fitInView(
                self._video_item, Qt.AspectRatioMode.KeepAspectRatio
            )
            self.video_native_size_changed.emit(int(size.width()), int(size.height()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        sz = self._video_item.size()
        if sz.width() > 0:
            self._view.fitInView(
                self._video_item, Qt.AspectRatioMode.KeepAspectRatio
            )

    def _on_duration(self, ms: int) -> None:
        self._duration = ms
        self._seek_bar.setRange(0, ms)
        self._refresh_time_label()
        self.duration_changed.emit(ms)

    def _on_position(self, ms: int) -> None:
        if not self._user_seeking:
            self._seek_bar.blockSignals(True)
            self._seek_bar.setValue(ms)
            self._seek_bar.blockSignals(False)
        self._sub_item.set_position(ms)
        self._refresh_time_label(ms)
        self.position_changed.emit(ms)

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._btn_play.setText("⏸" if playing else "▶")

    def _on_seek_released(self) -> None:
        self._user_seeking = False
        self._player.setPosition(self._seek_bar.value())

    def _on_seek_moved(self, value: int) -> None:
        self._refresh_time_label(value)

    def _refresh_time_label(self, pos: int | None = None) -> None:
        pos = pos if pos is not None else self._player.position()
        self._lbl_time.setText(f"{_fmt(pos)} / {_fmt(self._duration)}")

    # ------------------------------------------------------------------ #
    #  Subtitle preview API                                               #
    # ------------------------------------------------------------------ #

    def set_subtitle_rows(self, rows: list[tuple[int, int, str]]) -> None:
        self._sub_item.set_rows(rows)
        self._badge.setVisible(len(rows) > 0)

    def set_word_rows(self, word_rows: list) -> None:
        self._sub_item.set_word_rows(word_rows)

    def set_subtitle_style(self, style: SubtitleStyle) -> None:
        self._sub_item.set_style(style)
        # If rows are already loaded, force a repaint with the new style
        self._sub_item.update()

    def _on_sub_drag_end(self, dx_scene: float, dy_scene: float) -> None:
        """Convert scene-pixel drag offset to PlayRes (1920×1080) units and emit.

        Uses per-axis scale factors so portrait videos (e.g. 1080×1920) convert
        correctly — a single min-scale causes pos_y to overshoot and go off-screen.
        """
        sw = self._sub_item._scene_w
        sh = self._sub_item._scene_h
        if sw <= 0 or sh <= 0:
            return
        # libass maps PlayRes → video as: video_x = playres_x * sw/1920
        # Inverse: playres_offset = scene_offset * (1920/sw) for x, (1080/sh) for y
        self.drag_position_changed.emit(dx_scene * (1920.0 / sw), dy_scene * (1080.0 / sh))

    def _on_safe_zone_changed(self, value: str) -> None:
        platform = None if value == "Off" else value
        self._safe_zone_item.set_platform(platform)

    # ------------------------------------------------------------------ #
    #  VideoPlayerWidget-compatible public API                            #
    # ------------------------------------------------------------------ #

    def load(self, file_path: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(file_path))

    def play(self) -> None:
        self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()

    def toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def seek(self, ms: int) -> None:
        self._player.setPosition(ms)

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._duration
