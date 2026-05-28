from PyQt6.QtWidgets import QWidget, QSizePolicy, QMenu, QToolTip
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QPolygon, QCursor,
)


_SEGMENT_COLORS = [
    QColor(70, 130, 180, 160),   # steel blue
    QColor(90, 170, 90, 160),    # green
    QColor(200, 140, 60, 160),   # orange
    QColor(160, 70, 160, 160),   # purple
    QColor(60, 180, 165, 160),   # teal
]

_TRACK_H = 20
_HANDLE_R = 6
_TOP_PAD = 14
_BOT_PAD = 18
_SUB_TRACK_H = 12
_SUB_TRACK_GAP = 8


def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class TimelineWidget(QWidget):
    """Custom timeline bar with a seek handle and split-point markers.

    Interactions
    ────────────
    Left-click on empty space  → seek to that position
    Left-click on split marker → remove that split
    Right-click                → context menu (add split / clear all)
    Drag                       → scrub position
    """

    position_changed = pyqtSignal(int)   # ms — user-initiated seek
    split_added = pyqtSignal(int)        # ms — new split created by the user
    split_removed = pyqtSignal(int)      # index of removed split

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration: int = 0
        self._position: int = 0
        self._splits: list[int] = []      # sorted ms values
        self._dragging = False
        self._hovered_split = -1
        self._subtitle_rows: list[tuple] = []
        self._zoom: float = 1.0
        self._zoom_start: int = 0
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_duration(self, duration_ms: int) -> None:
        self._duration = duration_ms
        self._splits = []
        self._position = 0
        self._zoom = 1.0
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
        """Update the subtitle segments shown in the subtitle track."""
        self._subtitle_rows = list(rows)
        self.update()

    # ------------------------------------------------------------------ #
    #  Coordinate helpers                                                  #
    # ------------------------------------------------------------------ #

    def _track_rect(self) -> QRect:
        return QRect(_HANDLE_R, _TOP_PAD, self.width() - 2 * _HANDLE_R, _TRACK_H)

    def _ms_to_x(self, ms: int) -> int:
        if self._duration == 0:
            return _HANDLE_R
        v_start, v_end = self._visible_range()
        v_dur = v_end - v_start
        if v_dur <= 0:
            return _HANDLE_R
        r = self._track_rect()
        ratio = (ms - v_start) / v_dur
        return r.left() + int(ratio * r.width())

    def _x_to_ms(self, x: int) -> int:
        if self._duration == 0:
            return 0
        v_start, v_end = self._visible_range()
        v_dur = v_end - v_start
        r = self._track_rect()
        ratio = (x - r.left()) / r.width()
        return int(v_start + max(0.0, min(1.0, ratio)) * v_dur)

    def _split_at(self, x: int, tol: int = 8) -> int:
        for i, sp in enumerate(self._splits):
            if abs(self._ms_to_x(sp) - x) <= tol:
                return i
        return -1

    def _visible_range(self) -> tuple[int, int]:
        """Return (start_ms, end_ms) of the currently visible range."""
        if self._duration == 0:
            return 0, 0
        visible_dur = max(1, int(self._duration / self._zoom))
        start = max(0, min(self._zoom_start, self._duration - visible_dur))
        return start, start + visible_dur

    def _nice_interval(self) -> int:
        v_start, v_end = self._visible_range()
        target = max(1, v_end - v_start) if self._duration > 0 else self._duration
        for ms in [500, 1_000, 2_000, 5_000, 10_000, 30_000, 60_000, 120_000, 300_000, 600_000]:
            if target / ms <= 12:
                return ms
        return 600_000

    # ------------------------------------------------------------------ #
    #  Painting                                                            #
    # ------------------------------------------------------------------ #

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, QColor(28, 28, 28))

        r = self._track_rect()
        # Track base
        p.fillRect(r, QColor(55, 55, 55))

        if self._duration <= 0:
            return

        # Coloured segment fills
        bounds = [0] + self._splits + [self._duration]
        for i in range(len(bounds) - 1):
            x1 = self._ms_to_x(bounds[i])
            x2 = self._ms_to_x(bounds[i + 1])
            p.fillRect(x1 + 1, r.top() + 2, x2 - x1 - 2, r.height() - 4,
                       _SEGMENT_COLORS[i % len(_SEGMENT_COLORS)])

        # Time markers
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)
        fm = QFontMetrics(font)
        interval = self._nice_interval()
        v_start, v_end = self._visible_range()
        t = (v_start // interval) * interval
        while t <= v_end + interval:
            x = self._ms_to_x(t)
            if r.left() <= x <= r.right():
                p.setPen(QPen(QColor(90, 90, 90), 1))
                p.drawLine(x, r.bottom(), x, r.bottom() + 4)
                label = _fmt(t)
                lx = x - fm.horizontalAdvance(label) // 2
                p.setPen(QPen(QColor(130, 130, 130), 1))
                p.drawText(lx, h - 3, label)
            t += interval

        # Subtitle track
        sub_y = _TOP_PAD + _TRACK_H + _SUB_TRACK_GAP
        p.fillRect(QRect(_HANDLE_R, sub_y, w - 2 * _HANDLE_R, _SUB_TRACK_H),
                   QColor(40, 40, 40))
        for start_ms, end_ms, text in self._subtitle_rows:
            x1 = max(_HANDLE_R, self._ms_to_x(start_ms))
            x2 = min(w - _HANDLE_R, self._ms_to_x(end_ms))
            if x2 > x1:
                sub_block = QRect(x1, sub_y + 1, x2 - x1, _SUB_TRACK_H - 2)
                p.fillRect(sub_block, QColor(74, 158, 255, 160))
                if x2 - x1 > 30:
                    sf = QFont()
                    sf.setPointSize(7)
                    p.setFont(sf)
                    p.setPen(QPen(QColor(220, 220, 220), 1))
                    p.drawText(sub_block.adjusted(2, 0, -2, 0),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                               text[:20])
                    p.setFont(font)

        # Split markers
        for i, sp in enumerate(self._splits):
            x = self._ms_to_x(sp)
            color = QColor(255, 80, 80) if i == self._hovered_split else QColor(255, 200, 50)
            p.setPen(QPen(color, 2))
            p.drawLine(x, r.top() - 6, x, r.bottom() + 6)
            # Triangle handle pointing down
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            tri = QPolygon([
                QPoint(x - 5, r.top() - 7),
                QPoint(x + 5, r.top() - 7),
                QPoint(x, r.top() + 1),
            ])
            p.drawPolygon(tri)

        # Position handle
        px = self._ms_to_x(self._position)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(px, r.top() - 8, px, r.bottom() + 8)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(px - _HANDLE_R, r.top() - 8 - _HANDLE_R,
                      _HANDLE_R * 2, _HANDLE_R * 2)

    # ------------------------------------------------------------------ #
    #  Mouse events                                                        #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._duration == 0:
            return
        x = event.pos().x()

        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._split_at(x)
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
            ms = self._x_to_ms(x)
            menu = QMenu(self)
            act_add = menu.addAction(f"Add split at {_fmt(ms)}")
            act_clear = None
            if self._splits:
                menu.addSeparator()
                act_clear = menu.addAction("Clear all splits")
            action = menu.exec(event.globalPosition().toPoint())
            if action == act_add:
                self.add_split(ms)
                self.split_added.emit(ms)
            elif act_clear and action == act_clear:
                self._splits.clear()
                self.update()
                # notify the main window that all splits were removed
                self.split_removed.emit(-1)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        x = event.pos().x()
        if self._dragging:
            ms = self._x_to_ms(x)
            self._position = ms
            self.position_changed.emit(ms)
            self.update()
        else:
            prev = self._hovered_split
            self._hovered_split = self._split_at(x)
            if self._hovered_split != prev:
                self.update()
            if self._hovered_split >= 0:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"Click to remove  ·  {_fmt(self._splits[self._hovered_split])}",
                )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.MetaModifier:
            # Cmd+Scroll — zoom in/out centred on the cursor position
            cursor_ms = self._x_to_ms(int(event.position().x()))
            delta = event.angleDelta().y()
            factor = 1.25 if delta > 0 else (1.0 / 1.25)
            new_zoom = max(1.0, min(20.0, self._zoom * factor))
            if new_zoom != self._zoom:
                old_vis = (self._duration / self._zoom) if self._zoom > 0 else self._duration
                new_vis = self._duration / new_zoom
                ratio = (cursor_ms - self._zoom_start) / old_vis if old_vis > 0 else 0.5
                new_start = int(cursor_ms - ratio * new_vis)
                max_start = max(0, self._duration - int(new_vis))
                self._zoom = new_zoom
                self._zoom_start = max(0, min(max_start, new_start))
                self.update()
            event.accept()
        elif self._zoom > 1.0:
            # Plain scroll — pan left/right when zoomed
            vis = int(self._duration / self._zoom)
            step = max(100, vis // 10)
            if event.angleDelta().y() > 0:
                self._zoom_start = max(0, self._zoom_start - step)
            else:
                self._zoom_start = min(self._duration - vis, self._zoom_start + step)
            self.update()
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click resets timeline zoom to 1:1."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._zoom = 1.0
            self._zoom_start = 0
            self.update()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
