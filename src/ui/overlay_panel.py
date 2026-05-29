import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QFileDialog, QSpinBox, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread


def _fmt(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    return f"{m:02d}:{s:02d}.{(ms % 1000) // 10:02d}"


# --------------------------------------------------------------------------- #
#  Background worker                                                           #
# --------------------------------------------------------------------------- #

class _BurnWorker(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(
        self,
        input_path: str,
        overlays: list,
        output_path: str,
        x: int,
        y: int,
        size_pct: int,
    ) -> None:
        super().__init__()
        self._input   = input_path
        self._overlays = overlays
        self._output  = output_path
        self._x       = x
        self._y       = y
        self._size_pct = size_pct

    def run(self) -> None:
        try:
            from src.core.video_processor import burn_image_overlays  # noqa: PLC0415
            burn_image_overlays(
                self._input, self._overlays, self._output,
                x=self._x, y=self._y, size_pct=self._size_pct,
                on_progress=self.progress.emit,
            )
            self.finished.emit(self._output)
        except Exception as exc:
            self.error.emit(str(exc))


# --------------------------------------------------------------------------- #
#  Widget                                                                      #
# --------------------------------------------------------------------------- #

class OverlayPanel(QWidget):
    """Panel for adding and managing image overlays on the video timeline."""

    overlays_changed = pyqtSignal(list)   # [(start_ms, end_ms, path), ...]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._overlays  : list[tuple[int, int, str]] = []
        self._video_path: str | None = None
        self._duration  : int = 0
        self._playhead  : int = 0
        self._burn_worker: _BurnWorker | None = None
        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────── #

    def set_video_path(self, path: str | None) -> None:
        self._video_path = path
        self._btn_add.setEnabled(path is not None)
        self._update_burn_btn()

    def set_duration(self, ms: int) -> None:
        self._duration = ms

    def set_playhead(self, ms: int) -> None:
        self._playhead = ms

    def on_overlay_moved(self, row: int, new_start_ms: int, new_end_ms: int) -> None:
        """Called when the user drags/resizes an overlay block on the timeline."""
        if row < 0 or row >= len(self._overlays):
            return
        _, _, path = self._overlays[row]
        self._overlays[row] = (new_start_ms, new_end_ms, path)
        self._refresh_list()
        self.overlays_changed.emit(list(self._overlays))

    # ── Build UI ──────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Hint label
        hint = QLabel("Add images that appear over the video at specific times.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(hint)

        # Action row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_add = QPushButton("＋ Add Image…")
        self._btn_add.setEnabled(False)
        self._btn_add.setFixedHeight(26)
        btn_row.addWidget(self._btn_add)
        self._btn_remove = QPushButton("✕ Remove")
        self._btn_remove.setEnabled(False)
        self._btn_remove.setFixedHeight(26)
        btn_row.addWidget(self._btn_remove)
        layout.addLayout(btn_row)

        # Overlay list
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setMinimumHeight(80)
        self._list.setStyleSheet(
            "QListWidget { font-size: 11px; }"
            "QListWidget::item { padding: 3px 6px; }"
        )
        layout.addWidget(self._list, 1)

        # No-overlay placeholder
        self._lbl_empty = QLabel("No overlays yet.\nAdd an image and drag it on the timeline.")
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setStyleSheet("color: #555f6e; font-size: 11px;")
        layout.addWidget(self._lbl_empty)

        # Position / size
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d;")
        layout.addWidget(sep)

        pos_row = QHBoxLayout()
        pos_row.setSpacing(4)
        pos_row.addWidget(QLabel("X:"))
        self._x_spin = QSpinBox()
        self._x_spin.setRange(0, 3840)
        self._x_spin.setValue(10)
        self._x_spin.setFixedWidth(60)
        pos_row.addWidget(self._x_spin)
        pos_row.addWidget(QLabel("Y:"))
        self._y_spin = QSpinBox()
        self._y_spin.setRange(0, 2160)
        self._y_spin.setValue(10)
        self._y_spin.setFixedWidth(60)
        pos_row.addWidget(self._y_spin)
        pos_row.addWidget(QLabel("Size:"))
        self._size_spin = QSpinBox()
        self._size_spin.setRange(5, 200)
        self._size_spin.setValue(30)
        self._size_spin.setSuffix(" %")
        self._size_spin.setToolTip("Scale image to this % of the video width")
        self._size_spin.setFixedWidth(64)
        pos_row.addWidget(self._size_spin)
        pos_row.addStretch()
        layout.addLayout(pos_row)

        # Burn button
        self._btn_burn = QPushButton("🔥  Burn overlays into video…")
        self._btn_burn.setObjectName("btn_primary")
        self._btn_burn.setEnabled(False)
        self._btn_burn.setFixedHeight(28)
        layout.addWidget(self._btn_burn)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._lbl_status.hide()
        layout.addWidget(self._lbl_status)

        # Connections
        self._btn_add.clicked.connect(self._add_image)
        self._btn_remove.clicked.connect(self._remove_selected)
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._btn_burn.clicked.connect(self._burn)

        self._refresh_list()

    # ── Internals ─────────────────────────────────────────────────────── #

    def _add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image",
            os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tiff)",
        )
        if not path:
            return
        start_ms = self._playhead
        dur_ms   = 3000
        end_ms   = min(self._duration, start_ms + dur_ms) if self._duration else start_ms + dur_ms
        if end_ms <= start_ms:
            end_ms = start_ms + dur_ms
        self._overlays.append((start_ms, end_ms, path))
        self._refresh_list()
        self._update_burn_btn()
        self.overlays_changed.emit(list(self._overlays))

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._overlays):
            return
        self._overlays.pop(row)
        self._refresh_list()
        self._update_burn_btn()
        self.overlays_changed.emit(list(self._overlays))

    def _on_selection_changed(self, row: int) -> None:
        self._btn_remove.setEnabled(0 <= row < len(self._overlays))

    def _refresh_list(self) -> None:
        self._list.clear()
        for start_ms, end_ms, path in self._overlays:
            name  = os.path.basename(path)
            label = f"{name}   {_fmt(start_ms)} → {_fmt(end_ms)}"
            self._list.addItem(label)
        has = bool(self._overlays)
        self._list.setVisible(has)
        self._lbl_empty.setVisible(not has)

    def _update_burn_btn(self) -> None:
        self._btn_burn.setEnabled(
            bool(self._video_path) and bool(self._overlays)
            and (self._burn_worker is None or not self._burn_worker.isRunning())
        )

    def _burn(self) -> None:
        if not self._video_path or not self._overlays:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save video with overlays",
            os.path.splitext(self._video_path)[0] + "_overlays.mp4",
            "MP4 (*.mp4)",
        )
        if not out_path:
            return
        self._btn_burn.setEnabled(False)
        self._lbl_status.setText("Burning overlays…")
        self._lbl_status.show()
        self._burn_worker = _BurnWorker(
            self._video_path,
            list(self._overlays),
            out_path,
            x=self._x_spin.value(),
            y=self._y_spin.value(),
            size_pct=self._size_spin.value(),
        )
        self._burn_worker.finished.connect(self._on_burn_done)
        self._burn_worker.error.connect(self._on_burn_error)
        self._burn_worker.start()

    def _on_burn_done(self, path: str) -> None:
        self._lbl_status.setText(f"Saved → {os.path.basename(path)}")
        self._update_burn_btn()

    def _on_burn_error(self, msg: str) -> None:
        self._lbl_status.setText("Export failed")
        self._update_burn_btn()
        QMessageBox.critical(self, "Overlay Export Failed", msg)
