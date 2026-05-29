import os
import subprocess
import tempfile
from typing import NamedTuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QComboBox, QLabel,
    QProgressBar, QFileDialog, QMessageBox, QHeaderView,
    QAbstractItemView, QFrame, QLineEdit, QStyledItemDelegate,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from src.ui.subtitle_style import SubtitleStyleWidget, build_ass_content


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _ms_to_srt(ms: int) -> str:
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1_000
    cs = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{cs:03d}"


def _ms_to_vtt(ms: int) -> str:
    """WebVTT timestamp (uses period, not comma)."""
    h = ms // 3_600_000
    m = (ms % 3_600_000) // 60_000
    s = (ms % 60_000) // 1_000
    cs = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d}.{cs:03d}"


def _srt_to_ms(text: str) -> int:
    try:
        h, m, rest = text.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3_600_000 + int(m) * 60_000 + int(sec) * 1_000 + int(ms)
    except Exception:
        return 0


# --------------------------------------------------------------------------- #
#  Simple segment container (works whether we transcribe a clip or full file)  #
# --------------------------------------------------------------------------- #

class _Seg(NamedTuple):
    start: float
    end: float
    text: str
    words: list = []   # [(start_s, end_s, word_text), ...]


# --------------------------------------------------------------------------- #
#  Background worker                                                           #
# --------------------------------------------------------------------------- #

class _TranscribeWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    status = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        video_path: str,
        model_size: str,
        language: str | None,
        start_ms: int = 0,
        end_ms: int | None = None,
    ) -> None:
        super().__init__()
        self._video_path = video_path
        self._model_size = model_size
        self._language = language
        self._start_ms = start_ms
        self._end_ms = end_ms
        self._stop = False
        self._proc: subprocess.Popen | None = None

    def stop(self) -> None:
        self._stop = True
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def run(self) -> None:
        tmp_audio: str | None = None
        try:
            audio_path = self._video_path

            # ── Extract a clip if a time range is specified ─────────── #
            if self._start_ms > 0 or self._end_ms is not None:
                self.status.emit("Extracting audio segment…")
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                tmp_audio = tmp.name

                cmd = ["ffmpeg", "-y",
                       "-ss", f"{self._start_ms / 1000:.3f}"]
                if self._end_ms is not None:
                    cmd += ["-to", f"{self._end_ms / 1000:.3f}"]
                cmd += ["-i", self._video_path,
                        "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
                        tmp_audio]
                self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE)
                _, stderr_bytes = self._proc.communicate()
                returncode = self._proc.returncode
                self._proc = None
                if self._stop:
                    self.cancelled.emit()
                    return
                if returncode != 0:
                    raise RuntimeError(
                        f"Audio extraction failed:\n{stderr_bytes.decode(errors='replace')}"
                    )
                audio_path = tmp_audio

            # ── Transcribe ────────────────────────────────────────────── #
            self.status.emit(f"Loading model '{self._model_size}'…")
            from faster_whisper import WhisperModel  # noqa: PLC0415
            model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
            if self._stop:
                self.cancelled.emit()
                return
            self.status.emit("Transcribing…")
            kwargs: dict = {"beam_size": 5, "word_timestamps": True}
            if self._language:
                kwargs["language"] = self._language
            raw, _ = model.transcribe(audio_path, **kwargs)

            # Offset timestamps back to original video time
            offset = self._start_ms / 1000.0
            segments = []
            for seg in raw:
                if self._stop:
                    self.cancelled.emit()
                    return
                words = []
                if seg.words:
                    words = [
                        (w.start + offset, w.end + offset, w.word)
                        for w in seg.words
                    ]
                segments.append(
                    _Seg(start=seg.start + offset, end=seg.end + offset,
                         text=seg.text, words=words)
                )
            self.finished.emit(segments)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if tmp_audio:
                try:
                    os.unlink(tmp_audio)
                except Exception:
                    pass


# --------------------------------------------------------------------------- #
#  Live-preview delegate                                                       #
# --------------------------------------------------------------------------- #

class _LiveDelegate(QStyledItemDelegate):
    """Delegate that emits `editing_changed` on every keystroke while a cell
    is being edited, enabling the preview to update in real time."""

    editing_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._editor: QLineEdit | None = None
        self._editor_row: int = -1

    def setEditorData(self, editor: QWidget, index) -> None:  # type: ignore[override]
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            self._editor = editor
            self._editor_row = index.row()
            editor.textEdited.connect(self.editing_changed)

    def destroyEditor(self, editor: QWidget, index) -> None:  # type: ignore[override]
        if isinstance(editor, QLineEdit):
            try:
                editor.textEdited.disconnect(self.editing_changed)
            except RuntimeError:
                pass
            self._editor = None
            self._editor_row = -1
        super().destroyEditor(editor, index)

    def live_text(self) -> tuple[int, str] | None:
        """Return (row, current_text) of the open editor, or None."""
        if self._editor is not None and self._editor_row >= 0:
            return (self._editor_row, self._editor.text())
        return None


# --------------------------------------------------------------------------- #
#  Widget                                                                      #
# --------------------------------------------------------------------------- #

class SubtitleEditorWidget(QWidget):
    """Panel for generating, editing, and exporting subtitles."""

    jump_to = pyqtSignal(int)              # seek the player to this ms
    export_with_subs = pyqtSignal(str, bool, int, int)  # (tmp_path, burn_in, start_ms, end_ms)
    subtitles_updated = pyqtSignal(list)       # [(start_ms, end_ms, text), ...] live preview
    word_rows_updated = pyqtSignal(list)       # list[list[tuple[int,int,str]]] word-level timing
    style_preview_changed = pyqtSignal(object) # SubtitleStyle — live style preview

    _COL_IDX = 0
    _COL_START = 1
    _COL_END = 2
    _COL_TEXT = 3

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._video_path: str | None = None
        self._worker: _TranscribeWorker | None = None
        self._segments_info: list[tuple[int, int, str]] = []
        self._drag_offset_playres: tuple[float, float] = (0.0, 0.0)
        self._word_rows: list[list[tuple[int, int, str]]] = []
        self._video_native_size: tuple[int, int] = (1920, 1080)  # updated when video loads
        self._populating: bool = False
        self._build_ui()
        self._style_panel.hide()   # collapsed by default; toggled by _style_toggle

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ── Style toggle ─────────────────────────────────────────────── #
        self._style_toggle = QPushButton("▶  Style: TikTok")
        self._style_toggle.setCheckable(True)
        self._style_toggle.setFixedHeight(26)
        self._style_toggle.setStyleSheet(
            "QPushButton { text-align: left; padding: 4px 8px;"
            "  background: #1c2a3a; border: 1px solid #4a9eff;"
            "  border-radius: 4px; color: #4a9eff; font-weight: bold; font-size: 11px; }"
            "QPushButton:checked { background: #1a3a5a; }"
            "QPushButton:hover { background: #223344; }"
        )
        layout.addWidget(self._style_toggle)

        # Style panel (hidden until toggle)
        self._style_panel = SubtitleStyleWidget()
        self._style_panel.setMinimumHeight(380)
        self._style_panel.setStyleSheet(
            "SubtitleStyleWidget { border: 1px solid #3a3a3a; border-radius: 4px;"
            "  background: #1a1a1a; }"
        )
        layout.addWidget(self._style_panel)

        self._style_toggle.toggled.connect(self._toggle_style_panel)
        self._style_panel.style_changed.connect(self._on_style_changed)

        # ── Model / Lang / Scope — single row ────────────────────────── #
        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(4)
        cfg_row.addWidget(QLabel("Model:"))
        self._model_cb = QComboBox()
        self._model_cb.addItems(["tiny", "base", "small", "medium", "large-v2"])
        self._model_cb.setCurrentText("base")
        self._model_cb.setToolTip(
            "tiny/base: fast, less accurate\n"
            "small/medium: balanced\n"
            "large-v2: most accurate, slowest"
        )
        cfg_row.addWidget(self._model_cb)
        cfg_row.addWidget(QLabel("Lang:"))
        self._lang_cb = QComboBox()
        self._lang_cb.addItems(
            ["Auto", "en", "es", "fr", "de", "it", "pt", "nl", "ja", "zh", "ko", "ar"]
        )
        self._lang_cb.setFixedWidth(54)
        cfg_row.addWidget(self._lang_cb)
        cfg_row.addWidget(QLabel("Scope:"))
        self._scope_cb = QComboBox()
        self._scope_cb.addItem("All")
        self._scope_cb.setToolTip(
            "Transcribe the whole video, or only one segment.\n"
            "Segments update automatically when you add splits."
        )
        cfg_row.addWidget(self._scope_cb, 1)
        layout.addLayout(cfg_row)

        # ── Generate / Chunk / Find — single row ─────────────────────── #
        gen_row = QHBoxLayout()
        gen_row.setSpacing(4)
        self._btn_generate = QPushButton("⚙ Generate")
        self._btn_generate.setObjectName("btn_primary")
        self._btn_generate.setEnabled(False)
        self._btn_generate.setFixedHeight(26)
        gen_row.addWidget(self._btn_generate)
        self._chunk_cb = QComboBox()
        self._chunk_cb.addItems(["2", "3", "4", "5", "6"])
        self._chunk_cb.setCurrentText("4")
        self._chunk_cb.setFixedWidth(40)
        self._chunk_cb.setToolTip("Max words per subtitle chunk")
        gen_row.addWidget(self._chunk_cb)
        self._btn_chunk = QPushButton("⚡ Chunk")
        self._btn_chunk.setEnabled(False)
        self._btn_chunk.setFixedHeight(26)
        self._btn_chunk.setToolTip("Split long lines into short TikTok-paced chunks")
        gen_row.addWidget(self._btn_chunk)
        self._btn_find_toggle = QPushButton("🔍")
        self._btn_find_toggle.setCheckable(True)
        self._btn_find_toggle.setFixedSize(26, 26)
        self._btn_find_toggle.setToolTip("Find & Replace")
        gen_row.addWidget(self._btn_find_toggle)
        layout.addLayout(gen_row)

        # Progress + status (very thin, hidden when idle)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(3)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #8b949e; font-size: 11px;")
        self._lbl_status.hide()
        layout.addWidget(self._lbl_status)

        # ── Find / Replace panel ─────────────────────────────────────── #
        self._find_panel = QFrame()
        self._find_panel.setFrameShape(QFrame.Shape.StyledPanel)
        find_panel_lay = QVBoxLayout(self._find_panel)
        find_panel_lay.setContentsMargins(5, 5, 5, 5)
        find_panel_lay.setSpacing(3)

        fr = QHBoxLayout()
        fr.setSpacing(4)
        fr.addWidget(QLabel("Find:"))
        self._find_le = QLineEdit()
        self._find_le.setPlaceholderText("Search text…")
        fr.addWidget(self._find_le, 1)
        self._btn_find_next = QPushButton("Next")
        self._btn_find_next.setFixedWidth(46)
        self._btn_find_next.setFixedHeight(24)
        fr.addWidget(self._btn_find_next)
        find_panel_lay.addLayout(fr)

        rr = QHBoxLayout()
        rr.setSpacing(4)
        rr.addWidget(QLabel("Replace:"))
        self._replace_le = QLineEdit()
        self._replace_le.setPlaceholderText("Replacement…")
        rr.addWidget(self._replace_le, 1)
        self._btn_replace_all = QPushButton("All")
        self._btn_replace_all.setFixedWidth(38)
        self._btn_replace_all.setFixedHeight(24)
        rr.addWidget(self._btn_replace_all)
        find_panel_lay.addLayout(rr)

        self._find_panel.hide()
        layout.addWidget(self._find_panel)

        # ── Table ─────────────────────────────────────────────────────── #
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["#", "Start", "End", "Text"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(self._COL_IDX, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self._COL_START, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self._COL_END, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self._COL_TEXT, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(80)
        # Delegate for per-keystroke live preview updates
        self._live_delegate = _LiveDelegate(self._table)
        self._table.setItemDelegate(self._live_delegate)
        layout.addWidget(self._table, 1)

        # ── Export buttons — single row ───────────────────────────────── #
        export_row = QHBoxLayout()
        export_row.setSpacing(4)
        self._btn_save_srt = QPushButton(".srt")
        self._btn_save_srt.setEnabled(False)
        self._btn_save_srt.setFixedHeight(24)
        self._btn_save_srt.setToolTip("Save subtitles as SRT")
        export_row.addWidget(self._btn_save_srt)
        self._btn_save_vtt = QPushButton(".vtt")
        self._btn_save_vtt.setToolTip("Save subtitles as WebVTT")
        self._btn_save_vtt.setEnabled(False)
        self._btn_save_vtt.setFixedHeight(24)
        export_row.addWidget(self._btn_save_vtt)
        self._btn_embed = QPushButton("Embed")
        self._btn_embed.setToolTip("Add subtitles as a selectable track — no re-encode")
        self._btn_embed.setEnabled(False)
        self._btn_embed.setFixedHeight(24)
        export_row.addWidget(self._btn_embed)
        self._btn_burn = QPushButton("Burn")
        self._btn_burn.setObjectName("btn_primary")
        self._btn_burn.setToolTip("Bake subtitles into the picture — re-encodes video")
        self._btn_burn.setEnabled(False)
        self._btn_burn.setFixedHeight(24)
        export_row.addWidget(self._btn_burn)
        self._btn_pgn = QPushButton("♟")
        self._btn_pgn.setFixedSize(24, 24)
        self._btn_pgn.setToolTip("Import PGN chess game as subtitles")
        export_row.addWidget(self._btn_pgn)
        layout.addLayout(export_row)

        # ── Connections ───────────────────────────────────────────────── #
        self._btn_generate.clicked.connect(self._start_generation)
        self._btn_chunk.clicked.connect(self._auto_chunk)
        self._btn_find_toggle.toggled.connect(self._find_panel.setVisible)
        self._find_le.returnPressed.connect(self._find_next)
        self._btn_find_next.clicked.connect(self._find_next)
        self._btn_replace_all.clicked.connect(self._replace_all)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._table.itemChanged.connect(self._on_table_changed)
        self._live_delegate.editing_changed.connect(self._on_table_changed)
        self._btn_save_srt.clicked.connect(self._save_srt)
        self._btn_save_vtt.clicked.connect(self._save_vtt)
        self._btn_embed.clicked.connect(lambda: self._do_export(burn_in=False))
        self._btn_burn.clicked.connect(lambda: self._do_export(burn_in=True))
        self._btn_pgn.clicked.connect(self._import_pgn)

    # ------------------------------------------------------------------ #
    #  Style panel helpers                                                 #
    # ------------------------------------------------------------------ #

    def _toggle_style_panel(self, checked: bool) -> None:
        self._style_panel.setVisible(checked)
        arrow = "▼" if checked else "▶"
        preset = self._style_panel.active_preset_name()
        self._style_toggle.setText(f"{arrow}   Style: {preset}")

    def _on_style_changed(self, style) -> None:
        preset = self._style_panel.active_preset_name()
        arrow = "▼" if self._style_toggle.isChecked() else "▶"
        self._style_toggle.setText(f"{arrow}   Style: {preset}")
        self.style_preview_changed.emit(style)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_video_path(self, path: str) -> None:
        self._video_path = path
        self._drag_offset_playres = (0.0, 0.0)
        self._word_rows = []
        self._video_native_size = (1920, 1080)
        self._btn_generate.setEnabled(bool(path))

    def set_native_video_size(self, w: int, h: int) -> None:
        """Receive the video's native pixel dimensions from the player."""
        self._video_native_size = (w, h)

    def set_drag_offset(self, dx: float, dy: float) -> None:
        """Called by main window when the user drags the subtitle in the preview."""
        self._drag_offset_playres = (dx, dy)

    def sync_to_position(self, ms: int) -> None:
        """Scroll the subtitle table to highlight the row active at *ms*."""
        if self._populating or self._table.rowCount() == 0:
            return
        if self._table.hasFocus():
            return
        rows = self._read_table_rows()
        for i, (start, end, _) in enumerate(rows):
            if start <= ms < end:
                if self._table.currentRow() != i:
                    self._table.blockSignals(True)
                    self._table.setCurrentCell(i, self._COL_TEXT)
                    self._table.blockSignals(False)
                    self._table.scrollTo(self._table.model().index(i, self._COL_TEXT))
                return

    def _set_status(self, msg: str) -> None:
        """Show status label with msg; hide it if msg is empty."""
        self._lbl_status.setText(msg)
        self._lbl_status.setVisible(bool(msg))

    def update_segments(self, segs: list[tuple[int, int, str]]) -> None:
        """Called by the main window whenever splits change.

        segs: list of (start_ms, end_ms, display_label) per segment.
        """
        self._segments_info = segs
        prev = self._scope_cb.currentIndex()
        self._scope_cb.blockSignals(True)
        self._scope_cb.clear()
        self._scope_cb.addItem("All")
        for _s, _e, label in segs:
            self._scope_cb.addItem(label)
        idx = prev if prev < self._scope_cb.count() else 0
        self._scope_cb.setCurrentIndex(idx)
        self._scope_cb.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  Generation                                                          #
    # ------------------------------------------------------------------ #

    def _start_generation(self) -> None:
        # If already running, act as a stop button
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            return
        if not self._video_path:
            return
        model = self._model_cb.currentText()
        lang_text = self._lang_cb.currentText()
        language = None if lang_text == "Auto" else lang_text

        # Determine time range from scope selector
        scope_idx = self._scope_cb.currentIndex()
        start_ms, end_ms = 0, None
        if scope_idx > 0 and scope_idx <= len(self._segments_info):
            start_ms, end_ms, _ = self._segments_info[scope_idx - 1]

        self._btn_generate.setText("✕ Stop")
        self._progress.show()

        self._worker = _TranscribeWorker(
            self._video_path, model, language, start_ms, end_ms
        )
        self._worker.status.connect(self._set_status)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    def _on_cancelled(self) -> None:
        self._progress.hide()
        self._btn_generate.setText("⚙ Generate")
        self._btn_generate.setEnabled(True)
        self._set_status("Transcription cancelled")

    def _on_done(self, segments: list) -> None:
        self._progress.hide()
        self._btn_generate.setText("⚙ Generate")
        self._btn_generate.setEnabled(True)

        rows = []
        word_rows = []
        for seg in segments:
            if seg.text.strip():
                rows.append((int(seg.start * 1000), int(seg.end * 1000), seg.text.strip()))
                word_rows.append([
                    (int(ws * 1000), int(we * 1000), wt.strip())
                    for ws, we, wt in seg.words
                ])
        self._set_status(f"{len(rows)} subtitle entries generated")
        self._populate_table(rows)
        self._word_rows = word_rows
        self.subtitles_updated.emit(rows)
        self.word_rows_updated.emit(word_rows)
        self._btn_save_srt.setEnabled(True)
        self._btn_save_vtt.setEnabled(True)
        self._btn_embed.setEnabled(True)
        self._btn_burn.setEnabled(True)
        self._btn_chunk.setEnabled(True)

    def _on_error(self, msg: str) -> None:
        self._progress.hide()
        self._btn_generate.setText("⚙ Generate")
        self._btn_generate.setEnabled(True)
        self._set_status(f"Error: {msg}")
        QMessageBox.critical(self, "Subtitle Generation Error", msg)

    # ------------------------------------------------------------------ #
    #  Table helpers                                                       #
    # ------------------------------------------------------------------ #

    def _populate_table(self, rows: list[tuple]) -> None:
        self._populating = True
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for i, (start_ms, end_ms, text) in enumerate(rows):
            self._table.insertRow(i)

            num = QTableWidgetItem(str(i + 1))
            num.setFlags(num.flags() & ~Qt.ItemFlag.ItemIsEditable)
            num.setForeground(QColor(150, 150, 150))
            self._table.setItem(i, self._COL_IDX, num)

            self._table.setItem(i, self._COL_START, QTableWidgetItem(_ms_to_srt(start_ms)))
            self._table.setItem(i, self._COL_END, QTableWidgetItem(_ms_to_srt(end_ms)))
            self._table.setItem(i, self._COL_TEXT, QTableWidgetItem(text))

        self._table.blockSignals(False)
        self._populating = False

    def _read_table_rows(self) -> list[tuple]:
        rows = []
        # If a cell is currently being edited its QTableWidgetItem still holds
        # the old text.  Ask the delegate for the live editor text instead.
        live = self._live_delegate.live_text()  # (row, text) or None
        live_row = live[0] if live else None
        live_text = live[1] if live else None

        for r in range(self._table.rowCount()):
            start = _srt_to_ms(self._table.item(r, self._COL_START).text())
            end = _srt_to_ms(self._table.item(r, self._COL_END).text())
            if r == live_row and live_text is not None:
                text = live_text
            else:
                text = self._table.item(r, self._COL_TEXT).text()
            rows.append((start, end, text))
        return rows

    def _on_table_changed(self) -> None:
        """Re-emit subtitle rows whenever the user edits a cell.
        Also rebuilds word-level timing for any row whose text was changed
        so the preview word-effect animation stays in sync."""
        if self._populating or self._table.rowCount() == 0:
            return

        rows = self._read_table_rows()
        self.subtitles_updated.emit(rows)

        # Keep _word_rows in sync with edited text so the overlay draws the
        # right words (not the original Whisper transcription).
        if self._word_rows:
            updated = False
            for i, (start, end, text) in enumerate(rows):
                if i >= len(self._word_rows):
                    break
                wr_text = " ".join(w.strip() for _, _, w in self._word_rows[i])
                if wr_text != text.strip():
                    words = text.split()
                    dur = max(1, end - start)
                    if words:
                        per_word = dur / len(words)
                        self._word_rows[i] = [
                            (int(start + j * per_word),
                             int(start + (j + 1) * per_word), w)
                            for j, w in enumerate(words)
                        ]
                    else:
                        self._word_rows[i] = []
                    updated = True
            if updated:
                self.word_rows_updated.emit(list(self._word_rows))

    def on_subtitle_moved(self, row: int, new_start_ms: int, new_end_ms: int) -> None:
        """Called when the user drags/resizes a subtitle block on the timeline."""
        if row < 0 or row >= self._table.rowCount():
            return
        self._populating = True
        try:
            self._table.item(row, self._COL_START).setText(_ms_to_srt(new_start_ms))
            self._table.item(row, self._COL_END).setText(_ms_to_srt(new_end_ms))
        finally:
            self._populating = False
        # Push updated rows to the live preview without going through _on_table_changed
        rows = self._read_table_rows()
        self.subtitles_updated.emit(rows)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        # Jump to start time when double-clicking the index or start column
        if col in (self._COL_IDX, self._COL_START):
            rows = self._read_table_rows()
            if 0 <= row < len(rows):
                self.jump_to.emit(rows[row][0])

    # ------------------------------------------------------------------ #
    #  SRT content                                                         #
    # ------------------------------------------------------------------ #

    def _build_srt(self) -> str:
        lines = []
        for i, (start, end, text) in enumerate(self._read_table_rows(), 1):
            if text.strip():
                lines += [str(i), f"{_ms_to_srt(start)} --> {_ms_to_srt(end)}", text, ""]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Export                                                              #
    # ------------------------------------------------------------------ #

    def _save_srt(self) -> None:
        default = (
            os.path.splitext(self._video_path)[0] + ".srt"
            if self._video_path
            else "subtitles.srt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save SRT", default, "SRT Files (*.srt)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._build_srt())
            self._set_status(f"Saved → {os.path.basename(path)}")

    def _do_export(self, burn_in: bool) -> None:
        if self._table.rowCount() == 0:
            return

        # Determine export segment bounds from the scope selector
        scope_idx = self._scope_cb.currentIndex()
        export_start_ms = 0
        export_end_ms: int | None = None
        if scope_idx > 0 and scope_idx <= len(self._segments_info):
            export_start_ms, export_end_ms, _ = self._segments_info[scope_idx - 1]

        # Collect rows and offset timestamps so they're relative to the trimmed clip
        rows = self._read_table_rows()
        if export_start_ms > 0:
            rows = [
                (max(0, s - export_start_ms), max(0, e - export_start_ms), t)
                for s, e, t in rows
            ]
            # Also adjust word-level timestamps so per-word ASS lines stay in sync
            word_rows_export = [
                [(max(0, ws - export_start_ms), max(0, we - export_start_ms), wt)
                 for ws, we, wt in wr]
                for wr in self._word_rows
            ] if self._word_rows else None
        else:
            word_rows_export = self._word_rows if self._word_rows else None

        if burn_in:
            # Use styled ASS so TikTok/Instagram effects are preserved
            style = self._style_panel.current_style()
            vw, vh = self._video_native_size
            ass_content = build_ass_content(
                rows, style,
                play_res_x=vw, play_res_y=vh,
                drag_offset=self._drag_offset_playres if self._drag_offset_playres != (0.0, 0.0) else None,
                word_rows=word_rows_export,
            )
            tmp = tempfile.NamedTemporaryFile(
                suffix=".ass", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write(ass_content)
            tmp.close()
            self.export_with_subs.emit(
                tmp.name, True,
                export_start_ms, export_end_ms if export_end_ms is not None else -1,
            )
        else:
            # Soft-track embed — SRT/mov_text only (ASS not supported in MP4 soft track)
            srt_lines: list[str] = []
            for i, (start, end, text) in enumerate(rows, 1):
                if text.strip():
                    srt_lines += [str(i), f"{_ms_to_srt(start)} --> {_ms_to_srt(end)}", text, ""]
            tmp = tempfile.NamedTemporaryFile(
                suffix=".srt", delete=False, mode="w", encoding="utf-8"
            )
            tmp.write("\n".join(srt_lines))
            tmp.close()
            self.export_with_subs.emit(
                tmp.name, False,
                export_start_ms, export_end_ms if export_end_ms is not None else -1,
            )

    # ------------------------------------------------------------------ #
    #  Auto-chunk                                                          #
    # ------------------------------------------------------------------ #

    def _auto_chunk(self) -> None:
        """Split long subtitle lines into short chunks for TikTok-style pacing."""
        rows = self._read_table_rows()
        if not rows:
            return
        max_words = int(self._chunk_cb.currentText())
        new_rows: list[tuple] = []
        new_word_rows: list[list] = []
        for orig_idx, (start_ms, end_ms, text) in enumerate(rows):
            words = text.split()
            orig_timing = self._word_rows[orig_idx] if orig_idx < len(self._word_rows) else []
            if len(words) <= max_words:
                new_rows.append((start_ms, end_ms, text))
                if orig_timing:
                    new_word_rows.append(orig_timing)
                else:
                    # Synthesize even-spaced timing
                    n = len(words)
                    step = max(1, (end_ms - start_ms) // n) if n else 1
                    new_word_rows.append([(start_ms + k * step, start_ms + (k + 1) * step, w)
                                          for k, w in enumerate(words)])
                continue
            duration = end_ms - start_ms
            total_words = len(words)
            chunks = [words[i : i + max_words] for i in range(0, total_words, max_words)]
            t = start_ms
            for j, chunk_words in enumerate(chunks):
                chunk_text = " ".join(chunk_words)
                chunk_dur = int(duration * len(chunk_words) / total_words)
                # Compute word-index bounds first so we can align chunk_end
                # to the actual start of the next chunk's first word (prevents
                # per-word Dialogue lines from overlapping across rows).
                w0 = j * max_words
                w1 = w0 + len(chunk_words)
                if j == len(chunks) - 1:
                    chunk_end = end_ms
                elif orig_timing and w1 < len(orig_timing):
                    chunk_end = orig_timing[w1][0]  # align to real word boundary
                else:
                    chunk_end = t + max(50, chunk_dur)
                new_rows.append((t, chunk_end, chunk_text))
                if orig_timing and w0 < len(orig_timing):
                    new_word_rows.append(orig_timing[w0:w1])
                else:
                    # Synthesize even-spaced timing from chunk time budget
                    n_cw = len(chunk_words)
                    step = max(1, (chunk_end - t) // n_cw) if n_cw else 1
                    synth = [(t + k * step, t + (k + 1) * step, w)
                             for k, w in enumerate(chunk_words)]
                    new_word_rows.append(synth)
                t = chunk_end
        self._populate_table(new_rows)
        self._word_rows = new_word_rows
        self.subtitles_updated.emit(new_rows)
        self.word_rows_updated.emit(new_word_rows)
        self._set_status(f"Auto-chunked → {len(new_rows)} subtitle entries")

    # ------------------------------------------------------------------ #
    #  Public navigation / edit API (keyboard shortcuts)                  #
    # ------------------------------------------------------------------ #

    def select_next_subtitle(self) -> None:
        """Select the next subtitle row and seek the player to its start."""
        n = self._table.rowCount()
        if n == 0:
            return
        row = self._table.currentRow()
        next_row = (row + 1) % n
        self._table.setCurrentCell(next_row, self._COL_TEXT)
        rows = self._read_table_rows()
        if 0 <= next_row < len(rows):
            self.jump_to.emit(rows[next_row][0])

    def select_prev_subtitle(self) -> None:
        """Select the previous subtitle row and seek the player to its start."""
        n = self._table.rowCount()
        if n == 0:
            return
        row = self._table.currentRow()
        prev_row = (row - 1) % n
        self._table.setCurrentCell(prev_row, self._COL_TEXT)
        rows = self._read_table_rows()
        if 0 <= prev_row < len(rows):
            self.jump_to.emit(rows[prev_row][0])

    def delete_selected_subtitle(self) -> None:
        """Delete the currently selected subtitle row."""
        row = self._table.currentRow()
        if row < 0:
            return
        self._table.removeRow(row)
        for i in range(self._table.rowCount()):
            item = self._table.item(i, self._COL_IDX)
            if item:
                item.setText(str(i + 1))
        updated = self._read_table_rows() if self._table.rowCount() > 0 else []
        self.subtitles_updated.emit(updated)

    def nudge_selected(self, delta_ms: int) -> None:
        """Shift the start and end time of the selected subtitle by delta_ms."""
        row = self._table.currentRow()
        if row < 0:
            return
        rows = self._read_table_rows()
        if row >= len(rows):
            return
        start, end, _ = rows[row]
        new_start = max(0, start + delta_ms)
        new_end = max(new_start + 50, end + delta_ms)
        self._populating = True
        self._table.blockSignals(True)
        start_item = self._table.item(row, self._COL_START)
        end_item = self._table.item(row, self._COL_END)
        if start_item:
            start_item.setText(_ms_to_srt(new_start))
        if end_item:
            end_item.setText(_ms_to_srt(new_end))
        self._table.blockSignals(False)
        self._populating = False
        self.subtitles_updated.emit(self._read_table_rows())
        self.jump_to.emit(new_start)

    def add_subtitle_at(self, position_ms: int) -> None:
        """Insert a blank 2-second subtitle at *position_ms* (player time in ms)."""
        rows = self._read_table_rows()
        # Find insertion index (first row whose start > position_ms)
        insert_idx = len(rows)
        for i, (start, _end, _text) in enumerate(rows):
            if start > position_ms:
                insert_idx = i
                break
        # Clamp end time so it does not overlap the next subtitle
        end_ms = position_ms + 2000
        if insert_idx < len(rows):
            end_ms = min(end_ms, rows[insert_idx][0])
        end_ms = max(position_ms + 200, end_ms)

        new_rows = rows[:insert_idx] + [(position_ms, end_ms, "")] + rows[insert_idx:]
        self._populate_table(new_rows)
        self.subtitles_updated.emit(new_rows)
        self._btn_save_srt.setEnabled(True)
        self._btn_save_vtt.setEnabled(True)
        self._btn_embed.setEnabled(True)
        self._btn_burn.setEnabled(True)
        self._btn_chunk.setEnabled(True)
        # Select new row and open for immediate text entry
        self._table.setCurrentCell(insert_idx, self._COL_TEXT)
        item = self._table.item(insert_idx, self._COL_TEXT)
        if item:
            self._table.editItem(item)

    # ------------------------------------------------------------------ #
    #  Find & Replace                                                      #
    # ------------------------------------------------------------------ #

    def _find_next(self) -> None:
        """Select the next subtitle row whose text contains the search string."""
        query = self._find_le.text().lower()
        if not query:
            return
        n = self._table.rowCount()
        if n == 0:
            return
        start = (self._table.currentRow() + 1) % n
        for offset in range(n):
            row = (start + offset) % n
            item = self._table.item(row, self._COL_TEXT)
            if item and query in item.text().lower():
                self._table.setCurrentCell(row, self._COL_TEXT)
                rows = self._read_table_rows()
                if 0 <= row < len(rows):
                    self.jump_to.emit(rows[row][0])
                return
        self._set_status("Not found")

    def _replace_all(self) -> None:
        """Replace all occurrences of the find string with the replacement string."""
        query = self._find_le.text()
        replacement = self._replace_le.text()
        if not query:
            return
        count = 0
        self._populating = True
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self._COL_TEXT)
            if item and query in item.text():
                item.setText(item.text().replace(query, replacement))
                count += 1
        self._table.blockSignals(False)
        self._populating = False
        if count:
            self.subtitles_updated.emit(self._read_table_rows())
        self._set_status(f"Replaced {count} occurrence(s)")

    # ------------------------------------------------------------------ #
    #  WebVTT export                                                       #
    # ------------------------------------------------------------------ #

    def _build_vtt(self) -> str:
        lines = ["WEBVTT", ""]
        for i, (start, end, text) in enumerate(self._read_table_rows(), 1):
            if text.strip():
                lines += [str(i), f"{_ms_to_vtt(start)} --> {_ms_to_vtt(end)}", text, ""]
        return "\n".join(lines)

    def _save_vtt(self) -> None:
        default = (
            os.path.splitext(self._video_path)[0] + ".vtt"
            if self._video_path
            else "subtitles.vtt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save WebVTT", default, "WebVTT Files (*.vtt)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._build_vtt())
            self._set_status(f"Saved \u2192 {os.path.basename(path)}")

    # ------------------------------------------------------------------ #
    #  Chess PGN import                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_pgn_moves(content: str) -> list[str]:
        """Extract algebraic notation moves from PGN content."""
        import re  # noqa: PLC0415
        # Remove headers
        text = re.sub(r'\[.*?\]', '', content, flags=re.DOTALL)
        # Remove comments (including clock annotations)
        text = re.sub(r'\{[^}]*\}', '', text)
        # Remove variations iteratively
        while '(' in text:
            text = re.sub(r'\([^()]*\)', '', text)
        # Remove game results and NAG markers
        text = re.sub(r'\b(1-0|0-1|1/2-1/2|\*)\b|\$\d+', '', text)
        # Remove move numbers (e.g. "1.", "1...", "15.")
        text = re.sub(r'\d+\.+', '', text)
        # Keep only tokens that look like algebraic notation
        move_re = re.compile(
            r'^(O-O-O[+#]?|O-O[+#]?'
            r'|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](=[KQRBN])?[+#?!]*)$'
        )
        return [t for t in text.split() if move_re.match(t)]

    def _import_pgn(self) -> None:
        """Import a PGN chess game file and create subtitle rows for each move."""
        from PyQt6.QtWidgets import (  # noqa: PLC0415
            QDialog, QDialogButtonBox, QDoubleSpinBox,
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PGN File", "",
            "PGN Files (*.pgn);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception as exc:
            QMessageBox.critical(self, "PGN Import Error", str(exc))
            return

        moves = self._parse_pgn_moves(content)
        if not moves:
            QMessageBox.warning(
                self, "PGN Import",
                "No moves found in the PGN file.\n"
                "Make sure the file contains valid algebraic notation.",
            )
            return

        # Configuration dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("PGN Import Settings")
        dlg_lay = QVBoxLayout(dlg)
        dlg_lay.setSpacing(8)

        row_a = QHBoxLayout()
        row_a.addWidget(QLabel("Game starts at:"))
        offset_sp = QDoubleSpinBox()
        offset_sp.setRange(0, 86400)
        offset_sp.setValue(0.0)
        offset_sp.setSuffix(" s")
        row_a.addWidget(offset_sp)
        dlg_lay.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.addWidget(QLabel("Seconds per move:"))
        spm_sp = QDoubleSpinBox()
        spm_sp.setRange(0.5, 300.0)
        spm_sp.setValue(5.0)
        spm_sp.setSuffix(" s")
        row_b.addWidget(spm_sp)
        dlg_lay.addLayout(row_b)

        dlg_lay.addWidget(QLabel(
            f"<small>{len(moves)} moves found — will create {len(moves)} subtitle entries</small>"
        ))
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlg_lay.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        game_start_s = offset_sp.value()
        secs_per_move = spm_sp.value()
        rows = []
        for i, move in enumerate(moves):
            move_num = i // 2 + 1
            notation = (
                f"{move_num}. {move}" if i % 2 == 0
                else f"{move_num}... {move}"
            )
            start_ms = int((game_start_s + i * secs_per_move) * 1000)
            end_ms = int(start_ms + secs_per_move * 1000)
            rows.append((start_ms, end_ms, notation))

        self._populate_table(rows)
        self.subtitles_updated.emit(rows)
        self.word_rows_updated.emit([[] for _ in rows])
        self._btn_save_srt.setEnabled(True)
        self._btn_save_vtt.setEnabled(True)
        self._btn_embed.setEnabled(True)
        self._btn_burn.setEnabled(True)
        self._btn_chunk.setEnabled(True)
        self._set_status(f"Imported {len(rows)} chess moves from PGN")
