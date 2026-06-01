import os
import json

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QToolBar, QFileDialog, QMessageBox, QListWidget, QComboBox,
    QPushButton, QLabel, QTabWidget, QStatusBar, QSizePolicy, QFrame,
    QSpinBox, QProgressBar, QScrollArea, QSlider,
)
from PyQt6.QtCore import Qt, QThread, QDir, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut

from src.ui.subtitle_overlay import SubtitleOverlayPlayer
from src.ui.timeline import TimelineWidget
from src.ui.subtitle_editor import SubtitleEditorWidget
from src.ui.overlay_panel import OverlayPanel


# --------------------------------------------------------------------------- #
#  Background workers                                                          #
# --------------------------------------------------------------------------- #

class _SplitWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)   # output paths
    error = pyqtSignal(str)

    def __init__(self, input_path: str, splits: list[int], output_dir: str) -> None:
        super().__init__()
        self._input = input_path
        self._splits = splits
        self._out_dir = output_dir

    def run(self) -> None:
        try:
            from src.core.video_processor import split_video  # noqa: PLC0415
            base = os.path.splitext(os.path.basename(self._input))[0]
            self.progress.emit("Splitting…")
            paths = split_video(self._input, self._splits, self._out_dir, base)
            self.finished.emit(paths)
        except Exception as exc:
            self.error.emit(str(exc))


class _SubExportWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)   # 0-100

    def __init__(
        self,
        input_path: str,
        srt_path: str,
        output_path: str,
        burn_in: bool,
        start_ms: int = 0,
        end_ms: int = -1,
    ) -> None:
        super().__init__()
        self._input = input_path
        self._srt = srt_path
        self._output = output_path
        self._burn_in = burn_in
        self._start_s = start_ms / 1000.0
        self._end_s = end_ms / 1000.0 if end_ms >= 0 else None

    def run(self) -> None:
        try:
            if self._burn_in and self._srt.endswith(".ass"):
                from src.core.video_processor import burn_ass_subtitles  # noqa: PLC0415
                burn_ass_subtitles(
                    self._input, self._srt, self._output,
                    start_s=self._start_s, end_s=self._end_s,
                    on_progress=self.progress.emit,
                )
            else:
                from src.core.video_processor import add_subtitles  # noqa: PLC0415
                add_subtitles(
                    self._input, self._srt, self._output, self._burn_in,
                    start_s=self._start_s, end_s=self._end_s,
                    on_progress=self.progress.emit,
                )
            self.finished.emit(self._output)
        except Exception as exc:
            self.error.emit(str(exc))


class _SocialExportWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)   # output path
    error = pyqtSignal(str)

    def __init__(self, input_path: str, output_path: str, platform: str) -> None:
        super().__init__()
        self._input = input_path
        self._output = output_path
        self._platform = platform

    def run(self) -> None:
        try:
            from src.core.video_processor import export_social  # noqa: PLC0415
            self.progress.emit(f"Exporting for {self._platform}…")
            export_social(self._input, self._output, platform=self._platform)
            self.finished.emit(self._output)
        except Exception as exc:
            self.error.emit(str(exc))


class _DetectSilenceWorker(QThread):
    finished = pyqtSignal(list)   # list of (start_s, end_s) tuples
    error = pyqtSignal(str)

    def __init__(self, input_path: str) -> None:
        super().__init__()
        self._input = input_path

    def run(self) -> None:
        try:
            from src.core.video_processor import detect_silences  # noqa: PLC0415
            silences = detect_silences(self._input)
            self.finished.emit(silences)
        except Exception as exc:
            self.error.emit(str(exc))


class _ConcatWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, input_path: str, segments_ms: list, output_path: str) -> None:
        super().__init__()
        self._input    = input_path
        self._segments = segments_ms
        self._output   = output_path

    def run(self) -> None:
        try:
            from src.core.video_processor import concat_segments  # noqa: PLC0415
            concat_segments(self._input, self._segments, self._output, self.progress.emit)
            self.finished.emit(self._output)
        except Exception as exc:
            self.error.emit(str(exc))


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def _fmt_dur(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _h_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #21262d;")
    return f


# --------------------------------------------------------------------------- #
#  Main window                                                                 #
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._video_path: str | None = None
        self._duration: int = 0
        self._split_worker: _SplitWorker | None = None
        self._sub_worker: _SubExportWorker | None = None
        self._social_worker: _SocialExportWorker | None = None
        self._silence_worker: _DetectSilenceWorker | None = None
        self._concat_worker: _ConcatWorker | None = None
        self._excluded_segs: set[int] = set()
        self._clip_order: list[int] = []
        self._undo_stack: list[tuple] = []   # (splits, excluded, clip_order) snapshots
        self._redo_stack: list[tuple] = []
        self._splits_snapshot: list[int] = []
        self._pending_project: dict | None = None

        self.setWindowTitle("Cutyit")
        self.setMinimumSize(1080, 660)

        self._build_toolbar()
        self._build_ui()
        self._connect()
        self._apply_style()

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Info bar (hidden until video is opened) ──────────────────── #
        self._info_bar = QWidget()
        self._info_bar.setObjectName("info_bar")
        self._info_bar.setFixedHeight(26)
        info_lay = QHBoxLayout(self._info_bar)
        info_lay.setContentsMargins(10, 0, 10, 0)
        info_lay.setSpacing(10)
        self._lbl_filename = QLabel("")
        self._lbl_filename.setObjectName("lbl_filename")
        self._lbl_meta = QLabel("")
        self._lbl_meta.setObjectName("lbl_meta")
        info_lay.addWidget(self._lbl_filename)
        info_lay.addWidget(self._lbl_meta)
        info_lay.addStretch()
        self._info_bar.hide()
        root_layout.addWidget(self._info_bar)
        root_layout.addWidget(_h_sep())

        # ── Horizontal splitter ─────────────────────────────────────── #
        h_split = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.player = SubtitleOverlayPlayer()
        left_layout.addWidget(self.player, 1)

        self.timeline = TimelineWidget()
        left_layout.addWidget(self.timeline)

        # ── Zoom bar ────────────────────────────────────────────────── #
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(44, 0, 4, 0)   # align with timeline content (past header)
        zoom_row.setSpacing(4)

        self._btn_zoom_out = QPushButton("−")
        self._btn_zoom_out.setFixedSize(20, 16)
        self._btn_zoom_out.setToolTip("Zoom out")
        self._btn_zoom_out.setStyleSheet("QPushButton { font-size:13px; padding:0; }")

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(10, 200)   # /10 → 1.0× … 20.0×
        self._zoom_slider.setValue(10)
        self._zoom_slider.setFixedHeight(16)
        self._zoom_slider.setToolTip("Timeline zoom  (or ⌘+Scroll on the timeline)")

        self._btn_zoom_in = QPushButton("+")
        self._btn_zoom_in.setFixedSize(20, 16)
        self._btn_zoom_in.setToolTip("Zoom in")
        self._btn_zoom_in.setStyleSheet("QPushButton { font-size:13px; padding:0; }")

        self._zoom_lbl = QLabel("1×")
        self._zoom_lbl.setFixedWidth(36)
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setStyleSheet("color: #8c96a5; font-size: 11px;")

        self._btn_zoom_reset = QPushButton("↺")
        self._btn_zoom_reset.setFixedSize(20, 16)
        self._btn_zoom_reset.setToolTip("Reset zoom (or double-click timeline)")
        self._btn_zoom_reset.setStyleSheet("QPushButton { font-size:12px; padding:0; }")

        zoom_row.addWidget(self._btn_zoom_out)
        zoom_row.addWidget(self._zoom_slider, 1)
        zoom_row.addWidget(self._btn_zoom_in)
        zoom_row.addWidget(self._zoom_lbl)
        zoom_row.addWidget(self._btn_zoom_reset)
        left_layout.addLayout(zoom_row)

        h_split.addWidget(left)

        # Right panel
        right_panel = QWidget()
        right_panel.setObjectName("right_panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("editor_tabs")
        self._tabs.setMinimumWidth(270)
        self._tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._tabs.addTab(self._build_split_tab(), "✂ Clips")
        self.subtitle_editor = SubtitleEditorWidget()
        _sub_scroll = QScrollArea()
        _sub_scroll.setWidgetResizable(True)
        _sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _sub_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        _sub_scroll.setWidget(self.subtitle_editor)
        self._tabs.addTab(_sub_scroll, "💬 Subs")
        self.overlay_panel = OverlayPanel()
        _ovl_scroll = QScrollArea()
        _ovl_scroll.setWidgetResizable(True)
        _ovl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _ovl_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        _ovl_scroll.setWidget(self.overlay_panel)
        self._tabs.addTab(_ovl_scroll, "🖼 Overlays")
        right_layout.addWidget(self._tabs)

        h_split.addWidget(right_panel)
        h_split.setSizes([760, 320])
        h_split.setStretchFactor(0, 3)
        h_split.setStretchFactor(1, 1)

        root_layout.addWidget(h_split, 1)

        # Status bar
        self._status = QStatusBar()
        self._status.setObjectName("app_status")
        self.setStatusBar(self._status)
        self._export_progress = QProgressBar()
        self._export_progress.setRange(0, 100)
        self._export_progress.setFixedWidth(160)
        self._export_progress.setFixedHeight(16)
        self._export_progress.setTextVisible(True)
        self._export_progress.hide()
        self._status.addPermanentWidget(self._export_progress)
        self._status.showMessage("Ready — File › Open Video to begin")

    def _build_split_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)

        # ── Split at playhead ─────────────────────────────────────────── #
        self._btn_add_split = QPushButton("✂  Cut Here")
        self._btn_add_split.setObjectName("btn_primary")
        self._btn_add_split.setToolTip("Add a cut at the playhead position  (S)")
        self._btn_add_split.setEnabled(False)
        self._btn_add_split.setFixedHeight(28)
        lay.addWidget(self._btn_add_split)

        # ── Auto-split + silence row ──────────────────────────────────── #
        auto_row = QHBoxLayout()
        auto_row.setSpacing(4)
        self._lbl_seg_count = QLabel("1 seg")
        self._lbl_seg_count.setObjectName("lbl_muted")
        auto_row.addWidget(self._lbl_seg_count)
        auto_row.addStretch()
        auto_row.addWidget(QLabel("Every:"))
        self._split_interval_sp = QSpinBox()
        self._split_interval_sp.setRange(5, 3600)
        self._split_interval_sp.setValue(30)
        self._split_interval_sp.setSuffix(" s")
        self._split_interval_sp.setFixedWidth(64)
        auto_row.addWidget(self._split_interval_sp)
        self._btn_auto_split = QPushButton("⏱")
        self._btn_auto_split.setEnabled(False)
        self._btn_auto_split.setFixedSize(26, 26)
        self._btn_auto_split.setToolTip("Auto-cut at regular intervals")
        auto_row.addWidget(self._btn_auto_split)
        self._btn_silence = QPushButton("🔇")
        self._btn_silence.setEnabled(False)
        self._btn_silence.setFixedSize(26, 26)
        self._btn_silence.setToolTip(
            "Detect silences and auto-add cut points at their midpoints"
        )
        auto_row.addWidget(self._btn_silence)
        lay.addLayout(auto_row)

        # ── Clips list ────────────────────────────────────────────────── #
        hdr = QLabel("CLIPS")
        hdr.setObjectName("section_header")
        lay.addWidget(hdr)

        self._split_list = QListWidget()
        self._split_list.setObjectName("segment_list")
        self._split_list.setToolTip("Click to seek · double-click to jump to start")
        lay.addWidget(self._split_list, 1)

        # ── Remove / Export row ───────────────────────────────────────── #
        btn_row = QHBoxLayout()
        btn_row.setSpacing(5)
        self._btn_del_split = QPushButton("✕ Remove Cut")
        self._btn_del_split.setEnabled(False)
        self._btn_del_split.setFixedHeight(26)
        btn_row.addWidget(self._btn_del_split)
        self._btn_export = QPushButton("⬇ Export Clips…")
        self._btn_export.setObjectName("btn_primary")
        self._btn_export.setEnabled(False)
        self._btn_export.setFixedHeight(26)
        btn_row.addWidget(self._btn_export)
        lay.addLayout(btn_row)

        # ── Join kept clips row ───────────────────────────────────────── #
        self._btn_join = QPushButton("⬇ Join Kept Clips…")
        self._btn_join.setObjectName("btn_primary")
        self._btn_join.setEnabled(False)
        self._btn_join.setFixedHeight(26)
        self._btn_join.setToolTip(
            "Export only the non-excluded clips joined into one file"
        )
        lay.addWidget(self._btn_join)

        # ── Social export row ─────────────────────────────────────────── #
        social_row = QHBoxLayout()
        social_row.setSpacing(5)
        self._social_cb = QComboBox()
        self._social_cb.addItems(["TikTok", "Reels", "Shorts"])
        self._social_cb.setFixedWidth(80)
        self._social_cb.setToolTip("Target platform for social export")
        social_row.addWidget(self._social_cb)
        self._btn_social = QPushButton("📱 Export for Social…")
        self._btn_social.setObjectName("btn_primary")
        self._btn_social.setEnabled(False)
        self._btn_social.setFixedHeight(26)
        self._btn_social.setToolTip(
            "Re-encode as 1080×1920 vertical video with loudness normalisation"
        )
        social_row.addWidget(self._btn_social)
        lay.addLayout(social_row)

        return tab

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setObjectName("main_toolbar")
        tb.setIconSize(__import__('PyQt6.QtCore', fromlist=['QSize']).QSize(16, 16))
        self.addToolBar(tb)

        logo = QLabel(" ✂ Cutyit")
        logo.setObjectName("toolbar_logo")
        tb.addWidget(logo)

        gap = QWidget()
        gap.setFixedWidth(10)
        tb.addWidget(gap)

        act_open = QAction(" Open Video… ", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._open_video)
        tb.addAction(act_open)

        tb.addSeparator()

        act_open_proj = QAction(" Open Project… ", self)
        act_open_proj.triggered.connect(self._open_project)
        tb.addAction(act_open_proj)

        self._act_save_proj = QAction(" Save Project ", self)
        self._act_save_proj.setEnabled(False)
        self._act_save_proj.triggered.connect(self._save_project)
        tb.addAction(self._act_save_proj)

        tb.addSeparator()

        self._act_export = QAction(" Export Clips… ", self)
        self._act_export.setEnabled(False)
        self._act_export.triggered.connect(self._export_segments)
        tb.addAction(self._act_export)

        stretch = QWidget()
        stretch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(stretch)

    # ------------------------------------------------------------------ #
    #  Signal wiring                                                       #
    # ------------------------------------------------------------------ #

    def _connect(self) -> None:
        # Player ↔ timeline sync
        self.player.duration_changed.connect(self._on_duration)
        self.player.position_changed.connect(self.timeline.set_position)
        self.player.position_changed.connect(self._update_split_btn)

        # Timeline → player seek
        self.timeline.position_changed.connect(self.player.seek)
        self.timeline.split_added.connect(self._on_split_added)
        self.timeline.split_removed.connect(self._on_split_removed)

        # Split tab
        self._btn_add_split.clicked.connect(self._add_split_here)
        self._btn_del_split.clicked.connect(self._remove_selected_split)
        self._btn_export.clicked.connect(self._export_segments)
        self._split_list.currentRowChanged.connect(self._on_segment_selected)
        self._split_list.itemDoubleClicked.connect(self._on_segment_double_clicked)

        # Subtitle editor
        self.subtitle_editor.jump_to.connect(self.player.seek)
        self.subtitle_editor.export_with_subs.connect(self._export_with_subs)

        # Live subtitle preview
        self.subtitle_editor.subtitles_updated.connect(self.player.set_subtitle_rows)
        self.subtitle_editor.subtitles_updated.connect(self.timeline.set_subtitle_rows)
        self.subtitle_editor.word_rows_updated.connect(self.player.set_word_rows)
        self.subtitle_editor.style_preview_changed.connect(self.player.set_subtitle_style)

        # Subtitle drag on timeline → update editor table
        self.timeline.subtitle_moved.connect(self.subtitle_editor.on_subtitle_moved)
        self.timeline.segment_toggled.connect(self._on_segment_toggled)
        self.timeline.clip_reordered.connect(self._on_clip_reordered)

        # Zoom bar
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self._btn_zoom_in.clicked.connect(
            lambda: self.timeline.set_zoom(self.timeline.zoom() * 1.5))
        self._btn_zoom_out.clicked.connect(
            lambda: self.timeline.set_zoom(self.timeline.zoom() / 1.5))
        self._btn_zoom_reset.clicked.connect(lambda: self.timeline.set_zoom(1.0))
        self.timeline.zoom_changed.connect(self._on_zoom_changed)

        # Overlay panel ↔ timeline
        self.overlay_panel.overlays_changed.connect(self.timeline.set_overlay_rows)
        self.timeline.overlay_moved.connect(self.overlay_panel.on_overlay_moved)
        self.player.position_changed.connect(self.overlay_panel.set_playhead)

        # Subtitle drag position → stored in editor for ASS export
        self.player.drag_position_changed.connect(self.subtitle_editor.set_drag_offset)

        # Native video size → editor uses it to export ASS at the correct PlayRes
        self.player.video_native_size_changed.connect(self.subtitle_editor.set_native_video_size)

        # Table auto-scroll to active subtitle row during playback
        self.player.position_changed.connect(self.subtitle_editor.sync_to_position)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Space"), self).activated.connect(self.player.toggle_play)
        QShortcut(QKeySequence("S"), self).activated.connect(self._add_split_here)
        QShortcut(QKeySequence("C"), self).activated.connect(self._add_split_here)
        QShortcut(QKeySequence("Left"), self).activated.connect(
            lambda: self.player.seek(max(0, self.player.position() - 5_000))
        )
        QShortcut(QKeySequence("Right"), self).activated.connect(
            lambda: self.player.seek(min(self._duration, self.player.position() + 5_000))
        )
        QShortcut(QKeySequence("Shift+Left"), self).activated.connect(
            lambda: self.player.seek(max(0, self.player.position() - 1_000))
        )
        QShortcut(QKeySequence("Shift+Right"), self).activated.connect(
            lambda: self.player.seek(min(self._duration, self.player.position() + 1_000))
        )
        # Subtitle navigation
        QShortcut(QKeySequence("Down"), self).activated.connect(
            self.subtitle_editor.select_next_subtitle
        )
        QShortcut(QKeySequence("Up"), self).activated.connect(
            self.subtitle_editor.select_prev_subtitle
        )
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(
            lambda: self.subtitle_editor.nudge_selected(-100)
        )
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(
            lambda: self.subtitle_editor.nudge_selected(100)
        )
        QShortcut(QKeySequence("Backspace"), self).activated.connect(
            self.subtitle_editor.delete_selected_subtitle
        )
        QShortcut(QKeySequence("Return"), self).activated.connect(
            lambda: self.subtitle_editor.add_subtitle_at(self.player.position())
        )
        # Auto-split at intervals
        self._btn_auto_split.clicked.connect(self._auto_split_intervals)
        # Social export
        self._btn_social.clicked.connect(self._export_social)
        # Silence detection
        self._btn_silence.clicked.connect(self._detect_silences)
        # Join kept clips
        self._btn_join.clicked.connect(self._join_kept_clips)
        # Undo / Redo
        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self._redo)

    # ------------------------------------------------------------------ #
    #  Slots — playback                                                    #
    # ------------------------------------------------------------------ #

    def _on_duration(self, ms: int) -> None:
        self._duration = ms
        self.timeline.set_duration(ms)
        self.overlay_panel.set_duration(ms)
        self._btn_add_split.setEnabled(True)
        self._btn_export.setEnabled(True)
        self._act_export.setEnabled(True)
        self._btn_social.setEnabled(True)
        self._btn_auto_split.setEnabled(True)
        self._btn_silence.setEnabled(True)
        self._refresh_split_list()
        if self._pending_project is not None:
            self._restore_project_state(self._pending_project)
            self._pending_project = None

    def _update_split_btn(self, ms: int) -> None:
        if self._video_path:
            self._btn_add_split.setText(f"✂  Cut at {_fmt(ms)}")

    # ------------------------------------------------------------------ #
    #  Slots — split management                                            #
    # ------------------------------------------------------------------ #

    def _on_split_changed(self, _=None) -> None:
        # Kept for backward compatibility; routes to _on_split_removed
        self._on_split_removed(-1)

    def _on_split_added(self, ms: int) -> None:
        """Timeline right-click ‘Add cut’ — split already added when signal fires."""
        self._push_undo_state_from_snapshot()
        self._excluded_segs.clear()
        self.timeline.set_excluded(set())
        self._btn_join.setEnabled(False)
        self._splits_snapshot = list(self.timeline.split_points())
        self._refresh_split_list()

    def _on_split_removed(self, idx: int) -> None:
        """Timeline cut removed (click on marker, or clear-all from right-click)."""
        self._push_undo_state_from_snapshot()
        self._excluded_segs.clear()
        self.timeline.set_excluded(set())
        self._clip_order = []
        self.timeline.set_clip_order([])
        self._btn_join.setEnabled(False)
        if idx == -1:
            # clear-all: splits already gone
            self._splits_snapshot = []
        else:
            # single removal: split still present now (emit happens before remove_split)
            # update snapshot after the current event finishes
            QTimer.singleShot(0, self._deferred_splits_snapshot_update)
        self._refresh_split_list()

    def _deferred_splits_snapshot_update(self) -> None:
        self._splits_snapshot = list(self.timeline.split_points())

    # ── Undo / Redo ────────────────────────────────────────────────────────── #

    def _push_undo_state_from_snapshot(self) -> None:
        """Push the current snapshot (pre-operation state) onto the undo stack."""
        self._undo_stack.append((
            list(self._splits_snapshot),
            set(self._excluded_segs),
            list(self._clip_order),
        ))
        self._redo_stack.clear()
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _apply_state(self, splits: list, excluded: set, clip_order: list | None = None) -> None:
        """Restore a (splits, excluded, clip_order) snapshot without touching either undo stack."""
        self.timeline.clear_splits()
        for ms in sorted(splits):
            self.timeline.add_split(ms)
        self._excluded_segs = set(excluded)
        self.timeline.set_excluded(excluded)
        self._clip_order = list(clip_order) if clip_order else []
        self.timeline.set_clip_order(self._clip_order)
        is_reordered = (bool(self._clip_order)
                        and self._clip_order != list(range(len(self._clip_order))))
        self._btn_join.setEnabled(
            bool(self._video_path) and (bool(excluded) or is_reordered)
        )
        self._splits_snapshot = list(self.timeline.split_points())
        self._refresh_split_list()

    def _undo(self) -> None:
        if not self._undo_stack:
            self._status.showMessage("Nothing to undo")
            return
        self._redo_stack.append((
            list(self.timeline.split_points()),
            set(self._excluded_segs),
            list(self._clip_order),
        ))
        self._apply_state(*self._undo_stack.pop())
        self._status.showMessage("Undo")

    def _redo(self) -> None:
        if not self._redo_stack:
            self._status.showMessage("Nothing to redo")
            return
        self._undo_stack.append((
            list(self.timeline.split_points()),
            set(self._excluded_segs),
            list(self._clip_order),
        ))
        self._apply_state(*self._redo_stack.pop())
        self._status.showMessage("Redo")

    def _add_split_here(self) -> None:
        if not self._video_path:
            return
        pos = self.player.position()
        if 0 < pos < self._duration:
            self._push_undo_state_from_snapshot()
            self.timeline.add_split(pos)
            self._clip_order = []
            self.timeline.set_clip_order([])
            self._splits_snapshot = list(self.timeline.split_points())
            self._refresh_split_list()

    def _auto_split_intervals(self) -> None:
        """Add split points at regular time intervals across the entire video."""
        if not self._duration:
            return
        self._push_undo_state_from_snapshot()
        interval_ms = self._split_interval_sp.value() * 1000
        t = interval_ms
        added = 0
        while t < self._duration:
            self.timeline.add_split(t)
            added += 1
            t += interval_ms
        if added:
            self._clip_order = []
            self.timeline.set_clip_order([])
            self._splits_snapshot = list(self.timeline.split_points())
            self._refresh_split_list()
        self._status.showMessage(
            f"Added {added} cut point(s) every {self._split_interval_sp.value()}s"
        )

    def _remove_selected_split(self) -> None:
        row = self._split_list.currentRow()
        splits = self.timeline.split_points()
        if 0 <= row < len(splits):
            self._push_undo_state_from_snapshot()
            self.timeline.remove_split(row)
            self._clip_order = []
            self.timeline.set_clip_order([])
            self._splits_snapshot = list(self.timeline.split_points())
            self._refresh_split_list()

    def _on_segment_toggled(self, idx: int, excluded: bool) -> None:
        self._push_undo_state_from_snapshot()
        if excluded:
            self._excluded_segs.add(idx)
        else:
            self._excluded_segs.discard(idx)
        self._refresh_split_list()
        n_total = len(self.timeline.split_points()) + 1
        kept = n_total - len(self._excluded_segs)
        self._btn_join.setEnabled(
            bool(self._video_path) and kept > 0 and bool(self._excluded_segs)
        )

    def _on_zoom_slider(self, value: int) -> None:
        self.timeline.set_zoom(value / 10.0)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(round(zoom * 10))
        self._zoom_slider.blockSignals(False)
        z = round(zoom, 1)
        self._zoom_lbl.setText(f"{int(z)}×" if z == int(z) else f"{z}×")

    def _on_clip_reordered(self, order: list[int]) -> None:
        """Timeline drag-to-reorder finished — update clip order and enable join."""
        self._push_undo_state_from_snapshot()
        self._clip_order = list(order)
        self._splits_snapshot = list(self.timeline.split_points())
        is_reordered = self._clip_order != list(range(len(self._clip_order)))
        if is_reordered:
            self._btn_join.setEnabled(True)
        self._refresh_split_list()
        self._status.showMessage(
            "Clips reordered — use ⬇ Join Kept Clips to export in the new order"
        )

    def _join_kept_clips(self) -> None:
        if not self._video_path:
            return
        splits = self.timeline.split_points()
        boundaries = [0] + splits + [self._duration]
        n_segs = len(boundaries) - 1
        order = (self._clip_order if len(self._clip_order) == n_segs
                 else list(range(n_segs)))
        segments_ms = [
            (boundaries[src], boundaries[src + 1])
            for src in order
            if src not in self._excluded_segs
        ]
        if not segments_ms:
            QMessageBox.warning(self, "No clips", "All clips are excluded. Nothing to join.")
            return
        base = os.path.splitext(os.path.basename(self._video_path))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Joined Video", f"{base}_joined.mp4",
            "MP4 Files (*.mp4);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not out_path:
            return
        self._concat_worker = _ConcatWorker(self._video_path, segments_ms, out_path)
        self._export_progress.setValue(0)
        self._export_progress.show()
        self._concat_worker.progress.connect(self._export_progress.setValue)
        self._concat_worker.finished.connect(self._on_join_done)
        self._concat_worker.error.connect(self._on_join_error)
        self._btn_join.setEnabled(False)
        self._status.showMessage(f"Joining {len(segments_ms)} clip(s)…")
        self._concat_worker.start()

    def _on_join_done(self, path: str) -> None:
        self._export_progress.hide()
        n_kept = len(self.timeline.split_points()) + 1 - len(self._excluded_segs)
        self._btn_join.setEnabled(True)
        self._status.showMessage(f"Joined → {path}")
        QMessageBox.information(
            self, "Export Complete",
            f"Joined {n_kept} clip(s) saved to:\n{path}",
        )

    def _on_join_error(self, msg: str) -> None:
        self._export_progress.hide()
        self._status.showMessage(f"Join failed: {msg}")
        n_total = len(self.timeline.split_points()) + 1
        kept = n_total - len(self._excluded_segs)
        self._btn_join.setEnabled(kept > 0 and bool(self._excluded_segs))

    def _refresh_split_list(self) -> None:
        from PyQt6.QtWidgets import QListWidgetItem  # noqa: PLC0415
        from PyQt6.QtGui import QColor as _QC        # noqa: PLC0415
        splits = self.timeline.split_points()
        self._split_list.clear()
        boundaries = [0] + splits + [self._duration]
        segs_info: list[tuple[int, int, str]] = []
        for i in range(len(boundaries) - 1):
            s, e = boundaries[i], boundaries[i + 1]
            dur_label = _fmt_dur(e - s)
            excl = i in self._excluded_segs
            prefix = "✕ " if excl else "  "
            item = QListWidgetItem(
                f"{prefix}Clip {i + 1}   {_fmt(s)} → {_fmt(e)}  ·  {dur_label}"
            )
            if excl:
                item.setForeground(_QC(180, 80, 80))
            self._split_list.addItem(item)
            segs_info.append((s, e, f"Clip {i + 1}  ({_fmt(s)} – {_fmt(e)})"))
        n = len(boundaries) - 1
        self._lbl_seg_count.setText(f"{n} seg{'s' if n != 1 else ''}")
        self._btn_del_split.setEnabled(False)
        self.subtitle_editor.update_segments(segs_info)

    def _on_segment_selected(self, row: int) -> None:
        """Single-click: enable Remove and seek to segment start."""
        self._btn_del_split.setEnabled(row >= 0)
        if row >= 0:
            splits = self.timeline.split_points()
            boundaries = [0] + splits + [self._duration]
            if row < len(boundaries) - 1:
                self.player.seek(boundaries[row])

    def _on_segment_double_clicked(self, item) -> None:
        row = self._split_list.row(item)
        splits = self.timeline.split_points()
        boundaries = [0] + splits + [self._duration]
        if 0 <= row < len(boundaries) - 1:
            self.player.seek(boundaries[row])

    # ------------------------------------------------------------------ #
    #  File operations                                                     #
    # ------------------------------------------------------------------ #

    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video",
            QDir.homePath(),
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv *.wmv *.ts);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        self._pending_project = None
        self._do_load_video(path)

    def _do_load_video(self, path: str) -> None:
        """Load a video file; restore project state afterwards if _pending_project is set."""
        # Terminate any running background workers so the UI cannot lock up
        for _w in (self._sub_worker, self._split_worker,
                   self._social_worker, self._silence_worker):
            if _w is not None and _w.isRunning():
                _w.terminate()
                _w.wait(3000)
        self._export_progress.hide()
        self._set_export_busy(False)
        self._btn_social.setEnabled(False)
        self._btn_silence.setEnabled(False)

        self._video_path = path
        self._excluded_segs.clear()
        self._clip_order = []
        self._btn_join.setEnabled(False)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._splits_snapshot = []
        self.player.load(path)
        self.player.play()
        self.player.set_subtitle_rows([])          # clear previous overlay
        self.subtitle_editor.set_video_path(path)
        self.overlay_panel.set_video_path(path)
        self.timeline.set_duration(0)
        self.timeline.set_overlay_rows([])
        self._refresh_split_list()

        name = os.path.basename(path)
        self._lbl_filename.setText(f"📄  {name}")
        self._update_meta_label(path)
        self._info_bar.show()
        self._act_save_proj.setEnabled(True)
        self.setWindowTitle(f"Cutyit — {name}")
        self._status.showMessage(f"Opened: {path}")

    # ------------------------------------------------------------------ #
    #  Project save / open                                                 #
    # ------------------------------------------------------------------ #

    def _save_project(self) -> None:
        if not self._video_path:
            return
        default = os.path.splitext(self._video_path)[0] + ".cyt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", default,
            "Cutyit Project (*.cyt);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        subs = self.subtitle_editor.get_subtitle_rows()
        overlays = self.overlay_panel.get_overlays()
        data = {
            "version": "1",
            "video_path": self._video_path,
            "splits": self.timeline.split_points(),
            "excluded_segs": sorted(self._excluded_segs),
            "clip_order": list(self._clip_order),
            "subtitles": [
                {"start_ms": s, "end_ms": e, "text": t} for s, e, t in subs
            ],
            "overlays": [
                {"start_ms": s, "end_ms": e, "path": p} for s, e, p in overlays
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._status.showMessage(f"Project saved: {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", QDir.homePath(),
            "Cutyit Project (*.cyt);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Open Error", f"Cannot read project:\n{exc}")
            return
        video_path = data.get("video_path", "")
        if not os.path.isfile(video_path):
            QMessageBox.warning(
                self, "Video not found",
                f"The video file was not found:\n{video_path}\n\n"
                "The project will open but playback may not work.",
            )
        self._pending_project = data
        self._do_load_video(video_path)

    def _restore_project_state(self, data: dict) -> None:
        """Restore project state after the video duration is known."""
        for ms in data.get("splits", []):
            self.timeline.add_split(int(ms))
        self._splits_snapshot = list(self.timeline.split_points())

        self._excluded_segs = set(data.get("excluded_segs", []))
        self.timeline.set_excluded(self._excluded_segs)

        self._clip_order = list(data.get("clip_order", []))
        self.timeline.set_clip_order(self._clip_order)

        is_reordered = (bool(self._clip_order)
                        and self._clip_order != list(range(len(self._clip_order))))
        self._btn_join.setEnabled(bool(self._excluded_segs) or is_reordered)

        subs = data.get("subtitles", [])
        if subs:
            rows = [(s["start_ms"], s["end_ms"], s["text"]) for s in subs]
            self.subtitle_editor.load_subtitle_rows(rows)
            self.player.set_subtitle_rows(rows)

        overlays = data.get("overlays", [])
        if overlays:
            self.overlay_panel.load_overlays(
                [(o["start_ms"], o["end_ms"], o["path"]) for o in overlays]
            )

        self._refresh_split_list()
        self._status.showMessage("Project loaded")

    def _update_meta_label(self, path: str) -> None:
        try:
            from src.core.video_processor import get_video_info  # noqa: PLC0415
            info = get_video_info(path)
            w   = info.get("width", "?")
            h   = info.get("height", "?")
            fps = info.get("fps", "?")
            dur = info.get("duration_ms", 0)
            self._lbl_meta.setText(f"{w}×{h}  ·  {fps} fps  ·  {_fmt_dur(dur)}")
        except Exception:
            self._lbl_meta.setText("")

    # ------------------------------------------------------------------ #
    #  Export — split segments                                             #
    # ------------------------------------------------------------------ #

    def _export_segments(self) -> None:
        if not self._video_path:
            return
        out_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", os.path.dirname(self._video_path),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not out_dir:
            return

        splits = self.timeline.split_points()
        self._set_export_busy(True)
        self._status.showMessage("Exporting segments…")

        self._split_worker = _SplitWorker(self._video_path, splits, out_dir)
        self._split_worker.progress.connect(self._status.showMessage)
        self._split_worker.finished.connect(self._on_split_done)
        self._split_worker.error.connect(self._on_split_error)
        self._split_worker.start()

    def _on_split_done(self, paths: list) -> None:
        self._set_export_busy(False)
        self._status.showMessage(f"Exported {len(paths)} clip(s)")
        QMessageBox.information(
            self,
            "Export Complete",
            f"Saved {len(paths)} clip(s):\n" + "\n".join(os.path.basename(p) for p in paths),
        )

    def _on_split_error(self, msg: str) -> None:
        self._set_export_busy(False)
        self._status.showMessage("Export failed")
        QMessageBox.critical(self, "Export Error", msg)

    def _set_export_busy(self, busy: bool) -> None:
        self._btn_export.setEnabled(not busy)
        self._act_export.setEnabled(not busy)

    # ------------------------------------------------------------------ #
    #  Export — with subtitles                                             #
    # ------------------------------------------------------------------ #

    def _export_with_subs(self, srt_path: str, burn_in: bool, start_ms: int, end_ms: int) -> None:
        if not self._video_path:
            os.unlink(srt_path)
            return

        ext = os.path.splitext(self._video_path)[1]
        if not burn_in and ext.lower() not in (".mp4", ".m4v"):
            ext = ".mp4"   # mov_text requires MP4 container

        stem = os.path.splitext(self._video_path)[0]
        suffix = "_burned" if burn_in else "_subbed"
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Video with Subtitles",
            stem + suffix + ext,
            f"Video (*{ext})",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not output_path:
            os.unlink(srt_path)
            return

        self._status.showMessage("Exporting with subtitles…")
        self._export_progress.setValue(0)
        self._export_progress.show()
        self._sub_worker = _SubExportWorker(
            self._video_path, srt_path, output_path, burn_in,
            start_ms=start_ms, end_ms=end_ms,
        )
        self._sub_worker.progress.connect(self._on_sub_progress)
        self._sub_worker.finished.connect(lambda p: self._on_sub_done(p, srt_path))
        self._sub_worker.error.connect(lambda e: self._on_sub_error(e, srt_path))
        self._sub_worker.start()

    def _on_sub_progress(self, pct: int) -> None:
        self._export_progress.setValue(pct)
        self._status.showMessage(f"Exporting with subtitles… {pct}%")

    def _on_sub_done(self, output_path: str, srt_path: str) -> None:
        self._export_progress.hide()
        _cleanup(srt_path)
        self._status.showMessage(f"Saved: {os.path.basename(output_path)}")
        QMessageBox.information(self, "Export Complete", f"Saved:\n{output_path}")

    def _on_sub_error(self, msg: str, srt_path: str) -> None:
        self._export_progress.hide()
        _cleanup(srt_path)
        self._status.showMessage("Export failed")
        QMessageBox.critical(self, "Export Error", msg)

    # ------------------------------------------------------------------ #
    #  Export — social (TikTok / Reels / Shorts)                           #
    # ------------------------------------------------------------------ #

    def _export_social(self) -> None:
        if not self._video_path:
            return
        platform = self._social_cb.currentText()
        stem = os.path.splitext(self._video_path)[0]
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export for {platform}",
            f"{stem}_{platform.lower()}_1080x1920.mp4",
            "Video Files (*.mp4)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not output_path:
            return
        self._btn_social.setEnabled(False)
        self._status.showMessage(f"Exporting for {platform}…")
        self._social_worker = _SocialExportWorker(
            self._video_path, output_path, platform
        )
        self._social_worker.progress.connect(self._status.showMessage)
        self._social_worker.finished.connect(self._on_social_done)
        self._social_worker.error.connect(self._on_social_error)
        self._social_worker.start()

    def _on_social_done(self, output_path: str) -> None:
        self._btn_social.setEnabled(True)
        self._status.showMessage(f"Saved: {os.path.basename(output_path)}")
        QMessageBox.information(
            self, "Social Export Complete", f"Saved:\n{output_path}"
        )

    def _on_social_error(self, msg: str) -> None:
        self._btn_social.setEnabled(True)
        self._status.showMessage("Social export failed")
        QMessageBox.critical(self, "Social Export Error", msg)

    # ------------------------------------------------------------------ #
    #  Silence detection                                                   #
    # ------------------------------------------------------------------ #

    def _detect_silences(self) -> None:
        if not self._video_path:
            return
        self._btn_silence.setEnabled(False)
        self._status.showMessage("Detecting silences…")
        self._silence_worker = _DetectSilenceWorker(self._video_path)
        self._silence_worker.finished.connect(self._on_silences_done)
        self._silence_worker.error.connect(self._on_silences_error)
        self._silence_worker.start()

    def _on_silences_done(self, silences: list) -> None:
        self._btn_silence.setEnabled(True)
        if not silences:
            self._status.showMessage("No silences detected — try a lower threshold")
            QMessageBox.information(
                self, "Silence Detection",
                "No silent regions found.\n\n"
                "The video may have continuous audio, or try a lower\n"
                "noise threshold (edit video_processor.py: noise_threshold).",
            )
            return
        self._push_undo_state_from_snapshot()
        added = 0
        for start_s, end_s in silences:
            mid_ms = int((start_s + end_s) / 2.0 * 1000)
            if 0 < mid_ms < self._duration:
                self.timeline.add_split(mid_ms)
                added += 1
        if added:
            self._clip_order = []
            self.timeline.set_clip_order([])
            self._splits_snapshot = list(self.timeline.split_points())
            self._refresh_split_list()
        self._status.showMessage(
            f"Found {len(silences)} silent region(s) — added {added} cut point(s)"
        )

    def _on_silences_error(self, msg: str) -> None:
        self._btn_silence.setEnabled(True)
        self._status.showMessage("Silence detection failed")
        QMessageBox.critical(self, "Silence Detection Error", msg)

    # ------------------------------------------------------------------ #
    #  Styling                                                             #
    # ------------------------------------------------------------------ #

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0d1117;
                color: #e6edf3;
                font-size: 12px;
            }
            QToolBar#main_toolbar {
                background: #161b22;
                border-bottom: 1px solid #21262d;
                padding: 2px 6px;
                spacing: 1px;
            }
            QToolBar#main_toolbar::separator {
                background: #30363d; width: 1px; margin: 4px 3px;
            }
            QToolBar QToolButton {
                color: #c9d1d9; background: transparent;
                border: 1px solid transparent;
                padding: 3px 10px; border-radius: 5px; font-size: 12px;
            }
            QToolBar QToolButton:hover { background: #21262d; border-color: #30363d; }
            QToolBar QToolButton:pressed { background: #161b22; }
            QLabel#toolbar_logo {
                color: #58a6ff; font-size: 13px; font-weight: bold; padding: 0 4px;
            }
            QWidget#info_bar { background: #161b22; border-bottom: 1px solid #21262d; }
            QLabel#lbl_filename { color: #c9d1d9; font-weight: bold; font-size: 12px; }
            QLabel#lbl_meta {
                color: #8b949e; font-size: 11px;
                font-family: 'SF Mono', 'Menlo', monospace;
            }
            QSplitter::handle { background: #21262d; }
            QSplitter::handle:horizontal { width: 1px; }
            QWidget#right_panel { border-left: 1px solid #21262d; }
            QTabWidget#editor_tabs::pane { border: none; background: #0d1117; }
            QTabBar { background: #161b22; }
            QTabBar::tab {
                background: transparent; color: #8b949e;
                padding: 6px 16px; border: none;
                border-bottom: 2px solid transparent; font-size: 12px;
            }
            QTabBar::tab:selected {
                color: #e6edf3; border-bottom: 2px solid #1f6feb; background: #0d1117;
            }
            QTabBar::tab:hover:!selected { color: #c9d1d9; background: #21262d; }
            QWidget#player_controls { background: #0d1117; }
            QLabel#lbl_timecode {
                color: #8b949e; font-family: 'SF Mono', 'Menlo', monospace; font-size: 11px;
            }
            QLabel#sub_preview_badge {
                background: #1f6feb; color: #ffffff;
                font-size: 10px; font-weight: bold; letter-spacing: 1px;
                padding: 2px 6px; border-radius: 4px;
            }
            QSlider#seek_bar::groove:horizontal {
                height: 4px; background: #21262d; border-radius: 2px;
            }
            QSlider#seek_bar::sub-page:horizontal {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #1f6feb, stop:1 #388bfd);
                border-radius: 2px;
            }
            QSlider#seek_bar::handle:horizontal {
                background: #e6edf3; width: 12px; height: 12px;
                margin: -4px 0; border-radius: 6px;
            }
            QSlider#seek_bar::handle:horizontal:hover { background: #ffffff; }
            QSlider#vol_bar::groove:horizontal {
                height: 3px; background: #30363d; border-radius: 1px;
            }
            QSlider#vol_bar::sub-page:horizontal { background: #8b949e; border-radius: 1px; }
            QSlider#vol_bar::handle:horizontal {
                background: #c9d1d9; width: 9px; height: 9px;
                margin: -3px 0; border-radius: 4px;
            }
            QPushButton#btn_primary {
                background: #1f6feb; color: #ffffff; border: none;
                padding: 4px 12px; border-radius: 5px; font-weight: 600;
            }
            QPushButton#btn_primary:hover { background: #388bfd; }
            QPushButton#btn_primary:pressed { background: #1158c7; }
            QPushButton#btn_primary:disabled { background: #21262d; color: #484f58; }
            QPushButton#btn_play_primary {
                background: #1f6feb; color: #ffffff; border: none;
                border-radius: 5px; font-size: 14px; font-weight: bold;
            }
            QPushButton#btn_play_primary:hover { background: #388bfd; }
            QPushButton#btn_play_primary:pressed { background: #1158c7; }
            QPushButton {
                background: #21262d; color: #c9d1d9;
                border: 1px solid #30363d; padding: 3px 10px; border-radius: 5px;
            }
            QPushButton:hover { background: #30363d; border-color: #8b949e; }
            QPushButton:pressed { background: #161b22; }
            QPushButton:disabled { color: #484f58; border-color: #21262d; }
            QPushButton:checked { background: #1a3a5a; border-color: #1f6feb; color: #58a6ff; }
            QLabel#section_header {
                color: #8b949e; font-size: 10px; font-weight: bold; letter-spacing: 1px;
            }
            QLabel#lbl_muted { color: #8b949e; font-size: 11px; }
            QListWidget#segment_list {
                background: #161b22; border: 1px solid #21262d;
                border-radius: 5px; outline: none;
            }
            QListWidget#segment_list::item {
                padding: 4px 4px; border-bottom: 1px solid #21262d;
            }
            QListWidget#segment_list::item:selected { background: #1f3a5a; color: #58a6ff; }
            QListWidget#segment_list::item:hover:!selected { background: #1c2128; }
            QTableWidget {
                background: #161b22; gridline-color: #21262d;
                alternate-background-color: #0d1117;
                border: 1px solid #21262d; border-radius: 4px; outline: none;
            }
            QTableWidget::item:selected { background: #1f3a5a; color: #58a6ff; }
            QHeaderView::section {
                background: #161b22; color: #8b949e; border: none;
                border-right: 1px solid #21262d; border-bottom: 1px solid #21262d;
                padding: 3px 5px; font-size: 11px; font-weight: bold;
            }
            QComboBox {
                background: #161b22; border: 1px solid #30363d;
                color: #c9d1d9; padding: 3px 6px; border-radius: 5px;
            }
            QComboBox:hover { border-color: #58a6ff; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
                selection-background-color: #1f3a5a;
            }
            QSpinBox, QDoubleSpinBox {
                background: #161b22; border: 1px solid #30363d;
                color: #c9d1d9; padding: 2px 5px; border-radius: 4px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover { border-color: #58a6ff; }
            QCheckBox { color: #c9d1d9; spacing: 5px; }
            QCheckBox::indicator {
                width: 13px; height: 13px; border: 1px solid #30363d;
                border-radius: 3px; background: #161b22;
            }
            QCheckBox::indicator:checked { background: #1f6feb; border-color: #1f6feb; }
            QGroupBox {
                color: #8b949e; border: 1px solid #21262d; border-radius: 5px;
                margin-top: 10px; padding-top: 6px;
                font-size: 10px; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: #0d1117; width: 7px; border-radius: 3px; }
            QScrollBar::handle:vertical {
                background: #30363d; border-radius: 3px; min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: #0d1117; height: 7px; border-radius: 3px; }
            QScrollBar::handle:horizontal {
                background: #30363d; border-radius: 3px; min-width: 20px;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QProgressBar { background: #21262d; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #1f6feb; border-radius: 2px; }
            QStatusBar#app_status {
                background: #161b22; color: #8b949e;
                border-top: 1px solid #21262d; font-size: 11px;
            }
            QMessageBox { background: #161b22; color: #e6edf3; }
        """)


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except Exception:
        pass
