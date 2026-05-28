from PyQt6.QtWidgets import QWidget, QSizePolicy, QMenu, QToolTip
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QPolygon, QCursor, QLinearGradient,
)

# ── Layout constants ──────────────────────────────────────────────────── #
_HEADER_W  = 44     # left strip width for track labels
_PAD_TOP   = 2      # padding above ruler
_RULER_H   = 18     # time ruler
_VIDEO_H   = 42     # video track
_TRACK_GAP = 3      # gap between video and sub tracks
_SUB_H     = 22     # subtitle track
_PAD_BOT   = 6      # padding below sub track
_HANDLE_R  = 5      # playhead circle radius

_VIDEO_Y  = _PAD_TOP + _RULER_H
_SUB_Y    = _VIDEO_Y + _VIDEO_H + _TRACK_GAP
_WIDGET_H = _SUB_Y + _SUB_H + _PAD_BOT

# Clip fill colours (gradient-lit)
_SEG_COLORS = [
    QColor( 56, 139, 255),
    QColor( 63, 185,  80),
    QColor(255, 166,  77),
    QColor(188, 140, 255),
    QColor( 79, 201, 176),
]

_C_BG        = QColor(22,  27,  34)
_C_HDR_BG   = QColor(28,  35,  44)
_C_TRACK_BG  = QColor(45,  51,  62)
_C_SUB_BG    = QColor(36,  42,  52)
_C_PLAYHEAD  = QColor(255, 255, 255)
_C_CUT_IDLE  = QColor(255, 200,  50)
_C_CUT_HOV   = QColor(255,  80,  80)
_C_RULER_TXT = QColor(140, 150, 165)
_C_RULER_TK  = QColor( 65,  75,  90)


def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _fmt_tc(ms: int) -> str:
    """HH:MM:SS.cs"""
    s  = ms // 1000
    cs = (ms % 1000) // 10
    m  = s // 60
    s %= 60
    return f"{m:02d}:{s:02d}.{cs:02d}"


class TimelineWidget(QWidget):
    """Multi-track timeline with ruler, video track and subtitle track.

    Tracks
    ------
    VIDEO   — coloured clip blocks between cut points; cut markers as knife lines
    SUBS    — cyan blocks for each subtitle entry

    Interactions
    ------------
    Left-click content area     → seek
    Left-click a cut marker     → remove that cut
    Right-click content area    → context menu (add cut / clear all)
    Drag                        → scrub
    Cmd+Scroll                  → zoom in/out centred on cursor
    Scroll (when zoomed)        → pan
    Double-click                → reset zoom

    Public API is unchanged from the previous version so no callers need updating.
    """

    position_changed = pyqtSignal(int)   # ms — user-initiated seek
    split_added      = pyqtSignal(int)   # ms — new cut
    split_removed    = pyqtSignal(int)   # index removed  (-1 = all cleared)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration   : int       = 0
        self._position   : int       = 0
        self._splits     : list[int] = []
        self._dragging   : bool      = False
        self._hovered_cut: int       = -1
        self._subtitle_rows: list[tuple] = []
        self._zoom       : float     = 1.0
        self._zoom_start : int       = 0

        self.setFixedHeight(_WIDGET_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ── Public API ────────────────────────────────────────────────────── #

    def set_duration(self, duration_ms: int) -> None:
        self._duration   = duration_ms
        self._splits     = []
        self._position   = 0
        self._zoom       = 1.0
        self._zoom_start = 0
        self._subtitle_rows = []
        self.update()

    def set_position(self, ms: int) -> None:
        self._position = ms
        self.update()

    def split_points(self) -> list[int]:
        return list(self._splits)

    def add_split(self, ms: int) -> None:
        if 0 < ms < self._duration and ms not in self._splits:
            self._splits.append(ms)
            self._splits.sort()
            self.update()

    def remove_split(self, index: int) -> None:
        if 0 <= index < len(self._splits):
            self._splits.pop(index)
            self.update()

    def clear_splits(self) -> None:
        self._splits.clear()
        self.update()

    def set_subtitle_rows(self, rows: list[tuple]) -> None:
        self._subtitle_rows = list(rows)
        self.update()

    # ── Coordinate helpers ────────────────────────────────────────────── #

    def _cw(self) -> int:
        """Width of the scrollable content area (right of header strip)."""
        return max(1, self.width() - _HEADER_W)

    def _visible_range(self) -> tuple[int, int]:
        if self._duration == 0:
            return 0, 0
        vis   = max(1, int(self._duration / self._zoom))
        start = max(0, min(self._zoom_start, self._duration - vis))
        return start, start + vis

    def _ms_to_x(self, ms: int) -> int:
        if self._duration == 0:
            return _HEADER_W
        v_s, v_e = self._visible_range()
        ratio = (ms - v_s) / max(1, v_e - v_s)
        return _HEADER_W + int(ratio * self._cw())

    def _x_to_ms(self, x: int) -> int:
        if self._duration == 0:
            return 0
        v_s, v_e = self._visible_range()
        ratio = (x - _HEADER_W) / self._cw()
        return int(v_s + max(0.0, min(1.0, ratio)) * (v_e - v_s))

    def _cut_at(self, x: int, tol: int = 7) -> int:
        for i, sp in enumerate(self._splits):
            if abs(self._ms_to_x(sp) - x) <= tol:
                return i
        return -1

    def _nice_interval(self) -> int:
        v_s, v_e = self._visible_range()
        span = max(1, v_e - v_s) if self._duration > 0 else self._duration
        for ms in [500, 1_000, 2_000, 5_000, 10_000, 30_000,
                   60_000, 120_000, 300_000, 600_000]:
            if span / ms <= 12:
                return ms
        return 600_000

    # ── Paint ─────────────────────────────────────────────────────────── #

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Full background
        p.fillRect(0, 0, w, h, _C_BG)

        # ── Track header strip ───────────────────────────────────────── #
        p.fillRect(0, 0, _HEADER_W, h, _C_HDR_BG)
        p.setPen(QPen(QColor(50, 60, 75), 1))
        p.drawLine(_HEADER_W - 1, 0, _HEADER_W - 1, h)

        lbl_font = QFont()
        lbl_font.setPointSize(7)
        lbl_font.setBold(True)
        p.setFont(lbl_font)
        p.setPen(QPen(QColor(110, 125, 145), 1))
        # VIDEO label
        p.drawText(QRect(0, _VIDEO_Y, _HEADER_W - 5, _VIDEO_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "VIDEO")
        # SUBS label
        p.drawText(QRect(0, _SUB_Y, _HEADER_W - 5, _SUB_H),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   "SUBS")

        if self._duration <= 0:
            hint_font = QFont()
            hint_font.setPointSize(9)
            p.setFont(hint_font)
            p.setPen(QPen(QColor(70, 82, 98), 1))
            p.drawText(QRect(_HEADER_W + 12, 0, w - _HEADER_W - 12, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Open a video file to begin")
            return

        v_s, v_e = self._visible_range()

        # ── Ruler ────────────────────────────────────────────────────── #
        ruler_y = _PAD_TOP
        p.fillRect(QRect(_HEADER_W, ruler_y, self._cw(), _RULER_H), QColor(27, 32, 40))
        ruler_font = QFont()
        ruler_font.setPointSize(8)
        p.setFont(ruler_font)
        fm = QFontMetrics(ruler_font)
        interval = self._nice_interval()
        t = (v_s // interval) * interval
        while t <= v_e + interval:
            x = self._ms_to_x(t)
            if _HEADER_W <= x <= w:
                p.setPen(QPen(_C_RULER_TK, 1))
                p.drawLine(x, ruler_y + _RULER_H - 5, x, ruler_y + _RULER_H)
                lbl = _fmt(t)
                lw  = fm.horizontalAdvance(lbl)
                lx  = x - lw // 2
                if lx > _HEADER_W and lx + lw < w:
                    p.setPen(QPen(_C_RULER_TXT, 1))
                    p.drawText(lx, ruler_y + _RULER_H - 6, lbl)
            t += interval

        # ── Video track ──────────────────────────────────────────────── #
        vt_rect = QRect(_HEADER_W, _VIDEO_Y, self._cw(), _VIDEO_H)
        p.fillRect(vt_rect, _C_TRACK_BG)

        bounds = [0] + self._splits + [self._duration]
        clip_font = QFont()
        clip_font.setPointSize(8)
        clip_font.setBold(True)

        for i in range(len(bounds) - 1):
            x1 = max(_HEADER_W, self._ms_to_x(bounds[i]))
            x2 = min(w, self._ms_to_x(bounds[i + 1]))
            if x2 <= x1 + 1:
                continue
            base = _SEG_COLORS[i % len(_SEG_COLORS)]
            seg_r = QRect(x1 + 1, _VIDEO_Y + 2, x2 - x1 - 2, _VIDEO_H - 4)
            # vertical gradient: slightly lighter top
            grad = QLinearGradient(seg_r.topLeft(), seg_r.bottomLeft())
            light = QColor(min(255, base.red() + 30),
                           min(255, base.green() + 30),
                           min(255, base.blue() + 30), 210)
            grad.setColorAt(0.0, light)
            grad.setColorAt(1.0, QColor(base.red(), base.green(), base.blue(), 180))
            p.fillRect(seg_r, grad)
            if seg_r.width() > 30:
                p.setFont(clip_font)
                p.setPen(QPen(QColor(255, 255, 255, 210), 1))
                p.drawText(seg_r.adjusted(4, 0, -4, 0),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           f"Clip {i + 1}")

        p.setPen(QPen(QColor(55, 65, 80), 1))
        p.drawRect(vt_rect.adjusted(0, 0, -1, -1))

        # ── Subtitle track ───────────────────────────────────────────── #
        sub_rect = QRect(_HEADER_W, _SUB_Y, self._cw(), _SUB_H)
        p.fillRect(sub_rect, _C_SUB_BG)
        p.setPen(QPen(QColor(55, 65, 80), 1))
        p.drawRect(sub_rect.adjusted(0, 0, -1, -1))

        sub_font = QFont()
        sub_font.setPointSize(7)
        p.setFont(sub_font)
        for start_ms, end_ms, text in self._subtitle_rows:
            x1 = max(_HEADER_W, self._ms_to_x(start_ms))
            x2 = min(w, self._ms_to_x(end_ms))
            if x2 > x1:
                sb = QRect(x1, _SUB_Y + 2, x2 - x1, _SUB_H - 4)
                p.fillRect(sb, QColor(56, 139, 255, 190))
                if sb.width() > 22:
                    p.setPen(QPen(QColor(215, 228, 255), 1))
                    p.drawText(sb.adjusted(2, 0, -2, 0),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                               text[:20])

        # ── Cut markers ──────────────────────────────────────────────── #
        p.setFont(QFont())
        for i, sp in enumerate(self._splits):
            x   = self._ms_to_x(sp)
            col = _C_CUT_HOV if i == self._hovered_cut else _C_CUT_IDLE
            # Knife line through both tracks
            p.setPen(QPen(col, 2))
            p.drawLine(x, _VIDEO_Y - 3, x, _SUB_Y + _SUB_H + 2)
            # Diamond handle at top of video track
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            tri = QPolygon([
                QPoint(x - 5, _VIDEO_Y - 9),
                QPoint(x + 5, _VIDEO_Y - 9),
                QPoint(x,     _VIDEO_Y - 1),
            ])
            p.drawPolygon(tri)
            # Timestamp badge when hovered
            if i == self._hovered_cut:
                ts = _fmt_tc(sp)
                tf = QFont()
                tf.setPointSize(8)
                p.setFont(tf)
                tfm = QFontMetrics(tf)
                bw  = tfm.horizontalAdvance(ts) + 10
                bx  = max(_HEADER_W + 2, min(x - bw // 2, w - bw - 2))
                br  = QRect(bx, _VIDEO_Y + 4, bw, 16)
                p.setBrush(QBrush(QColor(18, 22, 30, 230)))
                p.setPen(QPen(col, 1))
                p.drawRoundedRect(br, 3, 3)
                p.setFont(tf)
                p.setPen(QPen(QColor(255, 255, 255), 1))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, ts)
                p.setFont(QFont())

        # ── Playhead ─────────────────────────────────────────────────── #
        ph = self._ms_to_x(self._position)
        # Thin shadow line
        p.setPen(QPen(QColor(0, 0, 0, 80), 3))
        p.drawLine(ph + 1, _PAD_TOP + 1, ph + 1, h - _PAD_BOT + 1)
        # Main line
        p.setPen(QPen(_C_PLAYHEAD, 1))
        p.drawLine(ph, _PAD_TOP, ph, h - _PAD_BOT)
        # Circle cap
        p.setBrush(QBrush(_C_PLAYHEAD))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(ph - _HANDLE_R, _PAD_TOP, _HANDLE_R * 2, _HANDLE_R * 2)

    # ── Mouse events ─────────────────────────────────────────────────── #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._duration == 0 or event.pos().x() < _HEADER_W:
            return
        x = event.pos().x()

        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._cut_at(x)
            if idx >= 0:
                self.split_removed.emit(idx)
                self.remove_split(idx)
            else:
                self._dragging = True
                ms = self._x_to_ms(x)
                self._position = ms
                self.position_changed.emit(ms)
                self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            ms   = self._x_to_ms(x)
            menu = QMenu(self)
            act_add   = menu.addAction(f"Add cut at {_fmt_tc(ms)}")
            act_clear = None
            if self._splits:
                menu.addSeparator()
                act_clear = menu.addAction("Clear all cuts")
            action = menu.exec(event.globalPosition().toPoint())
            if action == act_add:
                self.add_split(ms)
                self.split_added.emit(ms)
            elif act_clear and action == act_clear:
                self._splits.clear()
                self.update()
                self.split_removed.emit(-1)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.pos().x()
        if x < _HEADER_W:
            return
        if self._dragging:
            ms = self._x_to_ms(x)
            self._position = ms
            self.position_changed.emit(ms)
            self.update()
        else:
            prev = self._hovered_cut
            self._hovered_cut = self._cut_at(x)
            if self._hovered_cut != prev:
                self.update()
            if self._hovered_cut >= 0:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"Click to remove  ·  {_fmt_tc(self._splits[self._hovered_cut])}",
                )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.MetaModifier:
            cursor_ms = self._x_to_ms(int(event.position().x()))
            delta  = event.angleDelta().y()
            factor = 1.25 if delta > 0 else (1.0 / 1.25)
            new_z  = max(1.0, min(20.0, self._zoom * factor))
            if new_z != self._zoom:
                old_vis   = self._duration / self._zoom if self._zoom > 0 else self._duration
                new_vis   = self._duration / new_z
                ratio     = (cursor_ms - self._zoom_start) / old_vis if old_vis > 0 else 0.5
                new_start = int(cursor_ms - ratio * new_vis)
                max_start = max(0, self._duration - int(new_vis))
                self._zoom       = new_z
                self._zoom_start = max(0, min(max_start, new_start))
                self.update()
            event.accept()
        elif self._zoom > 1.0:
            vis  = int(self._duration / self._zoom)
            step = max(100, vis // 10)
            self._zoom_start += (-1 if event.angleDelta().y() > 0 else 1) * step
            self._zoom_start = max(0, min(self._duration - vis, self._zoom_start))
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._zoom       = 1.0
            self._zoom_start = 0
            self.update()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
