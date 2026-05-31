import subprocess
import json
import os
import re
import threading
from typing import List, Callable


def _run_ffmpeg(*args) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-y"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_ffmpeg_progress(
    args: list,
    total_s: float,
    on_progress: Callable[[int], None],
) -> tuple:
    """Run FFmpeg with progress callbacks (0-100).

    Parses out_time_us= lines from FFmpeg's -progress output.
    Returns (returncode, stderr_text).
    """
    cmd = ["ffmpeg", "-y"] + list(args) + ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stderr_chunks: list = []

    def _drain_stderr() -> None:
        stderr_chunks.append(proc.stderr.read())

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    for line in proc.stdout:  # type: ignore[union-attr]
        if line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1].strip())
                if total_s > 0:
                    pct = min(99, int(us / (total_s * 1_000_000) * 100))
                    on_progress(pct)
            except ValueError:
                pass

    proc.wait()
    t.join()
    stderr = stderr_chunks[0] if stderr_chunks else ""
    if proc.returncode == 0:
        on_progress(100)
    return proc.returncode, stderr


def check_ffmpeg() -> None:
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg not found. Install it with:\n  brew install ffmpeg"
        )


def get_video_info(path: str) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr}")
    return json.loads(result.stdout)


def get_duration_ms(path: str) -> int:
    info = get_video_info(path)
    duration = float(info["format"]["duration"])
    return int(duration * 1000)


def trim_video(
    input_path: str,
    start_ms: int,
    end_ms: int,
    output_path: str,
) -> None:
    """Trim a video segment using stream copy — zero quality loss."""
    result = _run_ffmpeg(
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-i", input_path,
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg trim failed:\n{result.stderr}")


def split_video(
    input_path: str,
    split_points_ms: List[int],
    output_dir: str,
    base_name: str = "segment",
) -> List[str]:
    """Split a video at the given millisecond positions.

    Uses stream copy on every segment so there is no re-encoding and no
    quality loss.  Returns the list of output file paths.
    """
    duration_ms = get_duration_ms(input_path)
    all_points = [0] + sorted(split_points_ms) + [duration_ms]
    ext = os.path.splitext(input_path)[1]

    os.makedirs(output_dir, exist_ok=True)
    output_paths: List[str] = []

    for i in range(len(all_points) - 1):
        start = all_points[i]
        end = all_points[i + 1]
        out_path = os.path.join(output_dir, f"{base_name}_{i + 1:03d}{ext}")
        trim_video(input_path, start, end, out_path)
        output_paths.append(out_path)

    return output_paths


def add_subtitles(
    input_path: str,
    srt_path: str,
    output_path: str,
    burn_in: bool = False,
    start_s: float = 0.0,
    end_s: float | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Embed or burn subtitles into a video.

    burn_in=False  → soft subtitle track, no re-encode (output must be .mp4)
    burn_in=True   → subtitles baked into the video frames (re-encodes video)
    start_s/end_s  → when set, only process that time range of the input
    on_progress    → optional callback(pct: int) called with 0-100 during export
    """
    seek_args = ["-ss", str(start_s)] if start_s > 0 else []
    dur_s = (end_s - start_s) if end_s is not None else None
    dur_args = ["-t", str(dur_s)] if dur_s is not None else []
    total_s = dur_s if dur_s is not None else get_duration_ms(input_path) / 1000.0

    if burn_in:
        escaped = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        args = [
            *seek_args, "-i", input_path,
            *dur_args, "-vf", f"subtitles='{escaped}'", "-c:a", "copy", output_path,
        ]
    else:
        args = [
            *seek_args, "-i", input_path, "-i", srt_path,
            *dur_args, "-c", "copy", "-c:s", "mov_text",
            "-metadata:s:s:0", "language=eng", output_path,
        ]

    if on_progress is not None:
        rc, stderr = _run_ffmpeg_progress(args, total_s, on_progress)
    else:
        result = _run_ffmpeg(*args)
        rc, stderr = result.returncode, result.stderr

    if rc != 0:
        raise RuntimeError(f"FFmpeg subtitle export failed:\n{stderr}")


def burn_ass_subtitles(
    input_path: str,
    ass_path: str,
    output_path: str,
    start_s: float = 0.0,
    end_s: float | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Burn a styled ASS subtitle file into the video (re-encodes video track).

    Requires FFmpeg built with libass (default in Homebrew builds).
    start_s/end_s  → when set, only process that time range of the input
    on_progress    → optional callback(pct: int) called with 0-100 during export
    """
    escaped = ass_path.replace(":", "\\:").replace("'", "\\'")
    seek_args = ["-ss", str(start_s)] if start_s > 0 else []
    dur_s = (end_s - start_s) if end_s is not None else None
    dur_args = ["-t", str(dur_s)] if dur_s is not None else []
    total_s = dur_s if dur_s is not None else get_duration_ms(input_path) / 1000.0
    args = [
        *seek_args, "-i", input_path,
        *dur_args, "-vf", f"ass='{escaped}'", "-c:a", "copy", output_path,
    ]
    if on_progress is not None:
        rc, stderr = _run_ffmpeg_progress(args, total_s, on_progress)
    else:
        result = _run_ffmpeg(*args)
        rc, stderr = result.returncode, result.stderr
    if rc != 0:
        raise RuntimeError(f"FFmpeg ASS burn failed:\n{stderr}")


def export_social(
    input_path: str,
    output_path: str,
    platform: str = "TikTok",
    normalize_audio: bool = True,
) -> None:
    """Export a video optimised for short-form vertical social platforms.

    Scales/pads to 1080×1920 (9:16), re-encodes with H.264, and normalises
    audio loudness to -14 LUFS (the streaming standard for TikTok/Reels).
    """
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    cmd = [
        "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
    ]
    if normalize_audio:
        cmd += ["-af", "loudnorm=I=-14:LRA=11:TP=-1.5"]
    cmd += ["-c:a", "aac", "-b:a", "192k", output_path]

    result = _run_ffmpeg(*cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{platform} social export failed:\n{result.stderr}")


def detect_silences(
    input_path: str,
    noise_threshold: float = -40.0,
    min_duration: float = 0.5,
) -> list[tuple[float, float]]:
    """Detect silent regions in a video using FFmpeg silencedetect.

    Returns a list of (start_seconds, end_seconds) tuples, one per silent
    region whose duration meets or exceeds *min_duration* seconds.
    """
    cmd = [
        "ffmpeg", "-i", input_path,
        "-af", f"silencedetect=noise={noise_threshold}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([\d.]+)", line)
            if m:
                start = float(m.group(1))
        elif "silence_end:" in line and start is not None:
            m = re.search(r"silence_end:\s*([\d.]+)", line)
            if m:
                silences.append((start, float(m.group(1))))
                start = None
    return silences


def burn_image_overlays(
    input_path: str,
    overlays: list,
    output_path: str,
    x: int = 10,
    y: int = 10,
    size_pct: int = 30,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Composite image overlays onto a video using FFmpeg.

    Each entry in *overlays* is a (start_ms, end_ms, image_path) tuple.
    The image is scaled to *size_pct* % of the video width and placed at
    pixel offset (*x*, *y*) from the top-left corner.

    Requires re-encode of the video track.
    """
    if not overlays:
        raise ValueError("No overlays provided")

    # Probe video width to compute absolute scale
    info = get_video_info(input_path)
    video_w = next(
        (s["width"] for s in info["streams"] if s["codec_type"] == "video"),
        1920,
    )
    scale_w = max(1, int(video_w * size_pct / 100))
    total_s = get_duration_ms(input_path) / 1000.0

    # Build inputs: main video first, then one -i per image
    inputs: list[str] = ["-i", input_path]
    for _, _, img_path in overlays:
        inputs += ["-i", img_path]

    # Build filter_complex string
    # Stream [0:v] is the video; [1:v], [2:v], … are the images
    parts: list[str] = []
    prev = "[0:v]"
    for idx, (start_ms, end_ms, _) in enumerate(overlays):
        img_idx  = idx + 1
        scaled   = f"[sc{idx}]"
        blended  = f"[bl{idx}]"
        t_s      = start_ms / 1000.0
        t_e      = end_ms   / 1000.0
        parts.append(f"[{img_idx}:v]scale={scale_w}:-1{scaled}")
        parts.append(
            f"{prev}{scaled}overlay={x}:{y}:enable='between(t,{t_s:.3f},{t_e:.3f})'{blended}"
        )
        prev = blended

    # Strip trailing label brackets — last output is the final video stream
    filter_complex = ";".join(parts)
    # Rename last output to [vout]
    filter_complex = filter_complex[: filter_complex.rfind("[")] + "[vout]"

    args = [
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "copy",
        output_path,
    ]

    if on_progress is not None:
        rc, stderr = _run_ffmpeg_progress(args, total_s, on_progress)
    else:
        result = _run_ffmpeg(*args)
        rc, stderr = result.returncode, result.stderr

    if rc != 0:
        raise RuntimeError(f"FFmpeg overlay burn failed:\n{stderr}")


def concat_segments(
    input_path: str,
    segments_ms: list[tuple[int, int]],
    output_path: str,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Concatenate specific segments of a video into a single output file.

    segments_ms: list of (start_ms, end_ms) pairs in playback order.
    Uses stream-copy trim + concat demuxer — no re-encode, no quality loss.
    """
    import tempfile

    if not segments_ms:
        raise ValueError("No segments provided")

    ext = os.path.splitext(input_path)[1]
    n = len(segments_ms)
    total_kept_s = max(1.0, sum(e - s for s, e in segments_ms) / 1000.0)

    with tempfile.TemporaryDirectory() as tmp:
        # Step 1: stream-copy trim each segment to a temp file
        seg_paths: list[str] = []
        for idx, (start_ms, end_ms) in enumerate(segments_ms):
            seg_path = os.path.join(tmp, f"seg_{idx:03d}{ext}")
            trim_video(input_path, start_ms, end_ms, seg_path)
            seg_paths.append(seg_path)
            if on_progress:
                on_progress(int((idx + 1) / n * 50))

        # Step 2: write concat list
        list_path = os.path.join(tmp, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for sp in seg_paths:
                f.write(f"file '{sp}'\n")

        # Step 3: concat with stream copy
        concat_args = [
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", output_path,
        ]
        if on_progress is not None:
            rc, stderr = _run_ffmpeg_progress(
                concat_args,
                total_kept_s,
                lambda pct: on_progress(50 + pct // 2),
            )
        else:
            result = _run_ffmpeg(*concat_args)
            rc, stderr = result.returncode, result.stderr

        if rc != 0:
            raise RuntimeError(f"FFmpeg concat failed:\n{stderr}")
