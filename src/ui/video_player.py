from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QSizePolicy,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, pyqtSignal, QUrl


def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class VideoPlayerWidget(QWidget):
    """Video display + transport controls (seek bar, play/pause, volume)."""

    duration_changed = pyqtSignal(int)    # ms
    position_changed = pyqtSignal(int)    # ms

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
        layout.setSpacing(4)

        # Video surface
        self._video_widget = QVideoWidget()
        self._video_widget.setMinimumHeight(240)
        self._video_widget.setStyleSheet("background-color: #000;")
        self._video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._player.setVideoOutput(self._video_widget)
        layout.addWidget(self._video_widget, 1)

        # Seek bar
        self._seek_bar = QSlider(Qt.Orientation.Horizontal)
        self._seek_bar.setRange(0, 0)
        self._seek_bar.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; }"
            "QSlider::sub-page:horizontal { background: #4a9eff; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: #fff; width: 12px; height: 12px;"
            "  margin: -4px 0; border-radius: 6px; }"
        )
        layout.addWidget(self._seek_bar)

        # Transport row
        row = QHBoxLayout()
        row.setSpacing(8)

        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedSize(36, 32)
        self._btn_play.setToolTip("Play / Pause  (Space)")
        row.addWidget(self._btn_play)

        self._lbl_time = QLabel("00:00 / 00:00")
        self._lbl_time.setStyleSheet("color: #ccc; font-family: monospace; font-size: 12px;")
        row.addWidget(self._lbl_time)

        row.addStretch()

        row.addWidget(QLabel("🔊"))
        self._vol_bar = QSlider(Qt.Orientation.Horizontal)
        self._vol_bar.setRange(0, 100)
        self._vol_bar.setValue(70)
        self._vol_bar.setFixedWidth(80)
        self._vol_bar.setToolTip("Volume")
        row.addWidget(self._vol_bar)

        layout.addLayout(row)

    def _connect_signals(self) -> None:
        self._player.durationChanged.connect(self._on_duration)
        self._player.positionChanged.connect(self._on_position)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(
            lambda err, msg: print(f"[MediaPlayer] {err}: {msg}")
        )

        self._btn_play.clicked.connect(self.toggle_play)

        self._seek_bar.sliderPressed.connect(lambda: setattr(self, "_user_seeking", True))
        self._seek_bar.sliderReleased.connect(self._on_seek_released)
        self._seek_bar.sliderMoved.connect(self._on_seek_moved)

        self._vol_bar.valueChanged.connect(lambda v: self._audio.setVolume(v / 100.0))

    # ------------------------------------------------------------------ #
    #  Slots                                                               #
    # ------------------------------------------------------------------ #

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
    #  Public API                                                          #
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
