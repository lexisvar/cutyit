from typing import List, Optional, Tuple


# --------------------------------------------------------------------------- #
#  SRT utilities                                                               #
# --------------------------------------------------------------------------- #

def _fmt_srt_time(seconds: float) -> str:
    """Convert a float seconds value to SRT timestamp HH:MM:SS,mmm."""
    total_ms = int(seconds * 1000)
    h = total_ms // 3_600_000
    m = (total_ms % 3_600_000) // 60_000
    s = (total_ms % 60_000) // 1_000
    ms = total_ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments) -> str:
    """Convert a list of faster-whisper segment objects to an SRT string."""
    lines: List[str] = []
    idx = 1
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_fmt_srt_time(seg.start)} --> {_fmt_srt_time(seg.end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    return "\n".join(lines)


def save_srt(segments, output_path: str) -> None:
    """Save faster-whisper segments as an .srt file."""
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(segments_to_srt(segments))


# --------------------------------------------------------------------------- #
#  Model wrapper                                                               #
# --------------------------------------------------------------------------- #

AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]


class SubtitleGenerator:
    """Lazy-loading wrapper around faster-whisper's WhisperModel."""

    def __init__(self) -> None:
        self._model = None
        self._loaded_size: Optional[str] = None

    def load_model(self, model_size: str = "base") -> None:
        if self._loaded_size == model_size:
            return
        from faster_whisper import WhisperModel  # noqa: PLC0415
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._loaded_size = model_size

    def transcribe(
        self,
        video_path: str,
        model_size: str = "base",
        language: Optional[str] = None,
    ) -> Tuple[list, object]:
        """Run transcription and return (segments, info).

        Segments are faster-whisper NamedTuple objects with .start, .end, .text.
        """
        self.load_model(model_size)
        kwargs = {"beam_size": 5}
        if language:
            kwargs["language"] = language
        segments, info = self._model.transcribe(video_path, **kwargs)
        return list(segments), info
