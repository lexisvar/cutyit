"""Subtitle style data model, presets, ASS generator, and style-editor widget."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QFrame, QColorDialog, QGroupBox, QScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QBrush, QPen


# ═══════════════════════════════════════════════════════════════════════════ #
#  Word Emphasis AI  (shared with subtitle_overlay)                           #
# ═══════════════════════════════════════════════════════════════════════════ #

_EMPHASIS_WORDS: frozenset[str] = frozenset([
    # Universal intensity
    "never", "always", "every", "everyone", "everything", "nothing", "nobody",
    "biggest", "largest", "smallest", "fastest", "best", "worst", "greatest",
    "huge", "massive", "incredible", "amazing", "terrible", "awful", "perfect",
    "impossible", "unstoppable", "legendary", "epic", "insane", "crazy",
    "absolutely", "literally", "actually", "exactly", "definitely", "certainly",
    "million", "billion", "thousand", "zero",
    # Action / emotional
    "stop", "look", "listen", "remember", "forget", "know", "think",
    "love", "hate", "fear", "trust", "win", "lose", "fight", "die",
    # Chess-specific
    "blunder", "brilliant", "sacrifice", "checkmate", "attack", "defend",
    "winning", "losing", "draw", "fork", "pin", "skewer", "discovered",
    "zwischenzug", "tempo", "initiative", "resign", "gambit",
])


def _should_emphasize(word: str) -> bool:
    """Heuristic: True if *word* should receive visual emphasis."""
    clean = re.sub(r"[^\w]", "", word)
    if not clean:
        return False
    if word.isupper() and len(clean) >= 3:
        return True
    if word.rstrip().endswith(("!", "?")):
        return True
    if re.match(r"^\d+([.,]\d+)?%?$", clean):
        return True
    if clean.lower() in _EMPHASIS_WORDS:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════ #
#  Data model                                                                 #
# ═══════════════════════════════════════════════════════════════════════════ #

@dataclass
class SubtitleStyle:
    """All properties needed to generate a styled ASS subtitle track."""

    name: str = "Custom"

    # Font
    font_family: str = "Arial"
    font_size: int = 52
    bold: bool = False
    italic: bool = False

    # Colors — (R, G, B, A)  all 0-255
    primary_color: tuple = (255, 255, 255, 255)   # text fill
    outline_color: tuple = (0, 0, 0, 255)          # outline / shadow base
    back_color: tuple = (0, 0, 0, 160)             # box background

    # Effects
    outline_width: float = 2.5
    shadow_depth: float = 0.0
    border_style: int = 1      # 1 = outline+shadow,  3 = opaque box
    spacing: float = 0.0

    # Position  (ASS numpad: 7 8 9 / 4 5 6 / 1 2 3)
    alignment: int = 2         # 2 = bottom-center

    # Margins from video edges (px in ASS coordinate space)
    margin_left: int = 20
    margin_right: int = 20
    margin_vertical: int = 50

    # Word-by-word effect
    word_effect: str = "none"               # "none" | "highlight" | "appear" | "ai_emphasis"
    highlight_color: tuple = (255, 215, 0, 255)   # gold

    def clone(self) -> "SubtitleStyle":
        return copy.deepcopy(self)


# ═══════════════════════════════════════════════════════════════════════════ #
#  Built-in presets                                                           #
# ═══════════════════════════════════════════════════════════════════════════ #

PRESETS: dict[str, SubtitleStyle] = {
    "TikTok": SubtitleStyle(
        name="TikTok",
        font_family="Arial Black",
        font_size=64,
        bold=True,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 255),
        back_color=(0, 0, 0, 0),
        outline_width=3.5,
        shadow_depth=0.0,
        border_style=1,
        alignment=2,
        margin_vertical=80,
        word_effect="highlight",
        highlight_color=(255, 220, 0, 255),
    ),
    "TikTok Box": SubtitleStyle(
        name="TikTok Box",
        font_family="Arial Black",
        font_size=58,
        bold=True,
        primary_color=(255, 243, 0, 255),     # bright yellow
        outline_color=(20, 20, 20, 255),
        back_color=(10, 10, 10, 220),
        outline_width=2.0,
        shadow_depth=0.0,
        border_style=3,                        # opaque box
        alignment=2,
        margin_vertical=70,
        word_effect="highlight",
        highlight_color=(255, 243, 0, 255),
    ),
    "Reels": SubtitleStyle(
        name="Reels",
        font_family="Helvetica Neue",
        font_size=54,
        bold=True,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 210),
        back_color=(0, 0, 0, 0),
        outline_width=2.5,
        shadow_depth=3.0,
        border_style=1,
        alignment=2,
        margin_vertical=90,
        word_effect="highlight",
        highlight_color=(255, 90, 180, 255),
    ),
    "YouTube": SubtitleStyle(
        name="YouTube",
        font_family="Arial",
        font_size=44,
        bold=False,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 255),
        back_color=(0, 0, 0, 200),
        outline_width=0.0,
        shadow_depth=0.0,
        border_style=3,
        alignment=2,
        margin_vertical=40,
    ),
    "Neon": SubtitleStyle(
        name="Neon",
        font_family="Arial Black",
        font_size=58,
        bold=True,
        primary_color=(0, 255, 180, 255),
        outline_color=(0, 60, 40, 255),
        back_color=(0, 0, 0, 0),
        outline_width=3.0,
        shadow_depth=5.0,
        border_style=1,
        alignment=2,
        margin_vertical=70,
    ),
    "Impact": SubtitleStyle(
        name="Impact",
        font_family="Impact",
        font_size=66,
        bold=False,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 255),
        back_color=(0, 0, 0, 0),
        outline_width=5.5,
        shadow_depth=0.0,
        border_style=1,
        alignment=2,
        margin_vertical=60,
    ),
    "Minimal": SubtitleStyle(
        name="Minimal",
        font_family="Helvetica",
        font_size=40,
        bold=False,
        primary_color=(240, 240, 240, 200),
        outline_color=(0, 0, 0, 200),
        back_color=(0, 0, 0, 0),
        outline_width=1.5,
        shadow_depth=1.0,
        border_style=1,
        alignment=2,
        margin_vertical=30,
    ),
    "Top Bar": SubtitleStyle(
        name="Top Bar",
        font_family="Arial Black",
        font_size=52,
        bold=True,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 255),
        back_color=(0, 0, 0, 0),
        outline_width=3.0,
        shadow_depth=0.0,
        border_style=1,
        alignment=8,           # top-center
        margin_vertical=40,
    ),
    "Hormozi": SubtitleStyle(
        name="Hormozi",
        font_family="Arial Black",
        font_size=68,
        bold=True,
        primary_color=(255, 255, 255, 255),
        outline_color=(0, 0, 0, 255),
        back_color=(0, 0, 0, 0),
        outline_width=4.0,
        shadow_depth=0.0,
        border_style=1,
        alignment=2,
        margin_vertical=80,
        word_effect="highlight",
        highlight_color=(255, 230, 0, 255),
    ),
    "MrBeast": SubtitleStyle(
        name="MrBeast",
        font_family="Impact",
        font_size=72,
        bold=False,
        primary_color=(255, 255, 0, 255),
        outline_color=(20, 20, 20, 255),
        back_color=(0, 0, 0, 0),
        outline_width=5.0,
        shadow_depth=4.0,
        border_style=1,
        alignment=2,
        margin_vertical=75,
    ),
    "Gaming": SubtitleStyle(
        name="Gaming",
        font_family="Arial Black",
        font_size=60,
        bold=True,
        primary_color=(0, 255, 180, 255),
        outline_color=(0, 40, 30, 255),
        back_color=(0, 0, 0, 200),
        outline_width=3.5,
        shadow_depth=6.0,
        border_style=3,
        alignment=2,
        margin_vertical=70,
        word_effect="highlight",
        highlight_color=(255, 50, 150, 255),
    ),
    "Podcast": SubtitleStyle(
        name="Podcast",
        font_family="Helvetica Neue",
        font_size=42,
        bold=False,
        primary_color=(230, 230, 230, 230),
        outline_color=(0, 0, 0, 180),
        back_color=(15, 15, 15, 200),
        outline_width=0.0,
        shadow_depth=2.0,
        border_style=3,
        alignment=2,
        margin_vertical=30,
    ),
    "Cinematic": SubtitleStyle(
        name="Cinematic",
        font_family="Georgia",
        font_size=38,
        bold=False,
        italic=True,
        primary_color=(255, 255, 240, 220),
        outline_color=(0, 0, 0, 200),
        back_color=(0, 0, 0, 0),
        outline_width=1.5,
        shadow_depth=4.0,
        border_style=1,
        alignment=2,
        margin_vertical=35,
    ),
    "Chess": SubtitleStyle(
        name="Chess",
        font_family="Georgia",
        font_size=44,
        bold=False,
        primary_color=(255, 245, 220, 245),
        outline_color=(30, 20, 10, 230),
        back_color=(20, 15, 10, 210),
        outline_width=2.0,
        shadow_depth=2.0,
        border_style=3,
        alignment=2,
        margin_vertical=40,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════ #
#  ASS file generator                                                         #
# ═══════════════════════════════════════════════════════════════════════════ #

def _to_ass_color(r: int, g: int, b: int, a: int) -> str:
    """Convert RGBA (0-255) → ASS &HAABBGGRR&  (alpha inverted: 0=opaque)."""
    return f"&H{255 - a:02X}{b:02X}{g:02X}{r:02X}&"


def build_ass_content(
    rows: list[tuple[int, int, str]],
    style: SubtitleStyle,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    drag_offset: tuple[float, float] | None = None,
    word_rows: list[list[tuple[int, int, str]]] | None = None,
) -> str:
    """Build a complete .ass file string from (start_ms, end_ms, text) rows.

    drag_offset: (dx, dy) in PlayRes units.  When non-zero the position of
    every subtitle is shifted by that amount via an inline \\pos tag.
    word_rows:   Optional per-sentence word timing.  When provided and
    style.word_effect is 'highlight', 'appear', or 'ai_emphasis', generates
    word-level Dialogue lines that match the live preview behaviour.
    """

    def _t(ms: int) -> str:
        cs = ms // 10
        h = cs // 360_000
        m = (cs % 360_000) // 6_000
        s = (cs % 6_000) // 100
        c = cs % 100
        return f"{h}:{m:02d}:{s:02d}.{c:02d}"

    pc = _to_ass_color(*style.primary_color)
    sc = _to_ass_color(0, 0, 0, 0)   # secondary unused (highlight done via \1c per-word lines)
    oc = _to_ass_color(*style.outline_color)
    bc = _to_ass_color(*style.back_color)
    bv = -1 if style.bold else 0
    iv = -1 if style.italic else 0

    # Scale all size/distance values by the same factor the preview uses:
    #   scale = min(video_w / 1920, video_h / 1080)
    # This ensures font size, margins, outline, and shadow look identical in
    # the export to what is shown in the player regardless of video orientation.
    ref_scale = min(play_res_x / 1920.0, play_res_y / 1080.0)
    e_font   = max(1, round(style.font_size       * ref_scale))
    e_mv     = max(0, round(style.margin_vertical * ref_scale))
    e_ml     = max(0, round(style.margin_left     * ref_scale))
    e_mr     = max(0, round(style.margin_right    * ref_scale))
    e_outl   = style.outline_width * ref_scale
    e_shad   = style.shadow_depth  * ref_scale
    e_spc    = style.spacing       * ref_scale

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,"
        f"{style.font_family},{e_font},"
        f"{pc},{sc},{oc},{bc},"
        f"{bv},{iv},0,0,"
        f"100,100,{e_spc:.1f},0,"
        f"{style.border_style},{e_outl:.1f},{e_shad:.1f},"
        f"{style.alignment},"
        f"{e_ml},{e_mr},{e_mv},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    # Pre-compute optional \pos tag from drag offset.
    # drag_offset values are stored in the app's "1920×1080 reference" PlayRes space.
    # Convert them to native PlayRes (play_res_x × play_res_y) coordinates.
    pos_tag = ""
    if drag_offset and (drag_offset[0] != 0.0 or drag_offset[1] != 0.0):
        dx_ref, dy_ref = drag_offset
        # Convert from 1920×1080 reference to native PlayRes
        dx = dx_ref * (play_res_x / 1920.0)
        dy = dy_ref * (play_res_y / 1080.0)
        a = style.alignment
        # Base reference point using scaled margins
        if a in (7, 8, 9):
            base_y = e_mv
        elif a in (4, 5, 6):
            base_y = play_res_y / 2.0
        else:
            base_y = play_res_y - e_mv
        if a in (1, 4, 7):
            base_x = e_ml
        elif a in (3, 6, 9):
            base_x = play_res_x - e_mr
        else:
            base_x = play_res_x / 2.0
        pos_x = int(base_x + dx)
        pos_y = int(base_y + dy)
        pos_tag = f"{{\\pos({pos_x},{pos_y})}}"

    for row_idx, (start_ms, end_ms, text) in enumerate(rows):
        if not text.strip():
            continue
        wrow: list[tuple[int, int, str]] = (
            word_rows[row_idx]
            if (word_rows and row_idx < len(word_rows))
            else []
        )

        if wrow and style.word_effect == "appear":
            # Progressive reveal: generate one Dialogue line per word showing
            # all words spoken so far.  Each line ends when the next word begins.
            for i, (ws, _we, _wt) in enumerate(wrow):
                ws_d = max(start_ms, ws)
                if ws_d >= end_ms:
                    continue
                line_end = min(wrow[i + 1][0] if i + 1 < len(wrow) else end_ms, end_ms)
                if ws_d >= line_end:
                    continue
                line_text = " ".join(w.strip() for _, _, w in wrow[: i + 1])
                lines.append(
                    f"Dialogue: 0,{_t(ws_d)},{_t(line_end)},Default,,0,0,0,,{pos_tag}{line_text}"
                )

        elif wrow and style.word_effect == "highlight":
            # One Dialogue line per word-active period.
            # Inline \1c tags colour ONLY the active word; \blur mimics the
            # preview glow.  All word text is stripped so Whisper leading
            # spaces don't produce double-gaps when joined.
            hr, hg, hb, ha = style.highlight_color
            pr, pg, pb, pa = style.primary_color
            h_col = _to_ass_color(hr, hg, hb, ha)
            p_col = _to_ass_color(pr, pg, pb, pa)
            n = len(wrow)
            # Glow blur — same order of magnitude as the 4-pass glow in preview
            blur = max(1.5, round(5.0 * ref_scale, 1))

            # Pre-word static line (full line in primary before first word)
            pre_end = min(wrow[0][0], end_ms)
            if pre_end > start_ms:
                txt = " ".join(f"{{\\1c{p_col}}}{w.strip()}" for _, _, w in wrow)
                lines.append(
                    f"Dialogue: 0,{_t(start_ms)},{_t(pre_end)},Default,,0,0,0,,{pos_tag}{txt}"
                )

            for i, (ws, _we, _) in enumerate(wrow):
                # Clamp to row bounds — prevents overlap with adjacent rows
                # when Whisper word timestamps don't align with segment bounds.
                ws_d = max(start_ms, ws)
                if ws_d >= end_ms:
                    continue
                w_end = min(wrow[i + 1][0] if i + 1 < n else end_ms, end_ms)
                if ws_d >= w_end:
                    continue
                parts = []
                for j, (_, _, w) in enumerate(wrow):
                    wt = w.strip()
                    if j == i:
                        # Active: highlight colour + glow blur; reset both after
                        parts.append(
                            f"{{\\1c{h_col}\\blur{blur}}}{wt}"
                            f"{{\\blur0\\1c{p_col}}}"
                        )
                    else:
                        parts.append(f"{{\\1c{p_col}}}{wt}")
                lines.append(
                    f"Dialogue: 0,{_t(ws_d)},{_t(w_end)},Default,,0,0,0,,{pos_tag}{' '.join(parts)}"
                )

        elif wrow and style.word_effect == "ai_emphasis":
            # Per-word primary-colour override for emphasised words.
            hr, hg, hb, _ = style.highlight_color
            pr, pg, pb, _ = style.primary_color
            hc = _to_ass_color(hr, hg, hb, 255)
            pc_tag = _to_ass_color(pr, pg, pb, 255)
            parts = []
            for _, _, w in wrow:
                wt = w.strip()
                if _should_emphasize(wt):
                    parts.append(f"{{\\1c{hc}}}{wt}{{\\1c{pc_tag}}}")
                else:
                    parts.append(f"{{\\1c{pc_tag}}}{wt}")
            lines.append(
                f"Dialogue: 0,{_t(start_ms)},{_t(end_ms)},Default,,0,0,0,,{pos_tag}{' '.join(parts)}"
            )

        else:
            # Static full-line render
            lines.append(
                f"Dialogue: 0,{_t(start_ms)},{_t(end_ms)},Default,,0,0,0,,{pos_tag}{text.strip()}"
            )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════ #
#  Helper widgets                                                             #
# ═══════════════════════════════════════════════════════════════════════════ #

class _ColorButton(QPushButton):
    """Button that shows a color swatch and opens a color-picker on click."""

    color_changed = pyqtSignal(tuple)   # (R, G, B, A)

    def __init__(self, color: tuple = (255, 255, 255, 255), parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(36, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        r, g, b, a = self._color
        self.setStyleSheet(
            f"background-color: rgba({r},{g},{b},{a});"
            "border: 1px solid #777; border-radius: 3px;"
        )

    def _pick(self) -> None:
        r, g, b, a = self._color
        col = QColorDialog.getColor(
            QColor(r, g, b, a), self, "Pick Color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel
            | QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if col.isValid():
            self._color = (col.red(), col.green(), col.blue(), col.alpha())
            self._refresh()
            self.color_changed.emit(self._color)

    def color(self) -> tuple:
        return self._color

    def set_color(self, c: tuple) -> None:
        self._color = c
        self._refresh()


# ─────────────────────────────────────────────────────────────────────────── #

_CARD_W, _CARD_H = 84, 62

class _PresetCard(QFrame):
    """Painted mini-preview card for a style preset."""

    clicked = pyqtSignal(str)

    def __init__(self, name: str, style: SubtitleStyle, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._style = style
        self._selected = False
        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def set_selected(self, v: bool) -> None:
        self._selected = v
        self.update()

    def paintEvent(self, _) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = _CARD_W, _CARD_H

        # Video-frame background
        p.fillRect(0, 0, w, h, QColor(18, 18, 18))

        # Selection border
        pen_color = QColor(74, 158, 255) if self._selected else QColor(65, 65, 65)
        pen_width = 2 if self._selected else 1
        p.setPen(QPen(pen_color, pen_width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 5, 5)

        # ── Mini subtitle preview ──────────────────────────────────── #
        s = self._style
        pr, pg, pb, _ = s.primary_color
        text_col = QColor(pr, pg, pb)
        or_, og, ob, _ = s.outline_color

        # Vertical position based on alignment
        if s.alignment in (7, 8, 9):   # top
            text_y = 8
        elif s.alignment in (4, 5, 6): # mid
            text_y = h // 2 - 8
        else:                           # bottom (1,2,3)
            text_y = h - 22

        text_rect = QRect(6, text_y, w - 12, 16)

        # Box background
        if s.border_style == 3:
            br, bg2, bb, ba = s.back_color
            p.fillRect(text_rect.adjusted(-2, 0, 2, 0), QColor(br, bg2, bb, min(ba, 200)))

        # Text font
        font = QFont(s.font_family, 8)
        font.setBold(s.bold)
        font.setItalic(s.italic)
        p.setFont(font)

        # Outline (simplified: draw offset copies)
        if s.outline_width > 0:
            p.setPen(QPen(QColor(or_, og, ob), max(1, int(s.outline_width * 0.4))))
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                p.drawText(text_rect.adjusted(dx, dy, dx, dy),
                           Qt.AlignmentFlag.AlignCenter, self._name)

        # Shadow
        if s.shadow_depth > 0:
            p.setPen(QPen(QColor(or_, og, ob, 180), 1))
            p.drawText(text_rect.adjusted(2, 2, 2, 2),
                       Qt.AlignmentFlag.AlignCenter, self._name)

        # Main text
        p.setPen(text_col)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._name)

        p.end()

    def mousePressEvent(self, _) -> None:  # noqa: N802
        self.clicked.emit(self._name)


# ═══════════════════════════════════════════════════════════════════════════ #
#  Position grid constants                                                    #
# ═══════════════════════════════════════════════════════════════════════════ #

_ALIGN_SYMBOL = {
    7: "↖", 8: "↑", 9: "↗",
    4: "←", 5: "✛", 6: "→",
    1: "↙", 2: "↓", 3: "↘",
}
_ALIGN_GRID = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]

_GROUP_CSS = (
    "QGroupBox { color: #aaa; border: 1px solid #3d3d3d; border-radius: 5px;"
    "  margin-top: 10px; padding-top: 6px; font-size: 11px; font-weight: bold; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
)


# ═══════════════════════════════════════════════════════════════════════════ #
#  Main style-editor widget                                                   #
# ═══════════════════════════════════════════════════════════════════════════ #

class SubtitleStyleWidget(QWidget):
    """Full subtitle style editor: presets, position, font, colors, effects."""

    style_changed = pyqtSignal(object)   # emits a SubtitleStyle clone

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._style = PRESETS["TikTok"].clone()
        self._cards: dict[str, _PresetCard] = {}
        self._align_btns: dict[int, QPushButton] = {}
        self._build_ui()
        self._select_preset("TikTok", emit=False)

    # ------------------------------------------------------------------ #
    #  Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(5)

        # ── Preset cards (horizontal scroll) ─────────────────────────── #
        lbl = QLabel("PRESETS")
        lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        root.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setFixedHeight(_CARD_H + 6)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for name, style in PRESETS.items():
            card = _PresetCard(name, style)
            card.clicked.connect(self._select_preset)
            self._cards[name] = card
            row.addWidget(card)
        row.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # ── Position + Font ───────────────────────────────────────────── #
        pf_row = QHBoxLayout()
        pf_row.setSpacing(5)

        # Position 3×3
        pos_box = QGroupBox("Position")
        pos_box.setStyleSheet(_GROUP_CSS)
        pos_grid = QGridLayout(pos_box)
        pos_grid.setSpacing(3)
        pos_grid.setContentsMargins(6, 10, 6, 4)
        for r, row_vals in enumerate(_ALIGN_GRID):
            for c, a in enumerate(row_vals):
                btn = QPushButton(_ALIGN_SYMBOL[a])
                btn.setFixedSize(26, 26)
                btn.setCheckable(True)
                btn.setStyleSheet(
                    "QPushButton { background:#2e2e2e; border:1px solid #555;"
                    "  border-radius:3px; font-size:13px; color:#ccc; }"
                    "QPushButton:hover { background:#3a3a3a; }"
                    "QPushButton:checked { background:#1a5fa0; border-color:#4a9eff; color:#fff; }"
                )
                btn.clicked.connect(lambda _, av=a: self._on_align(av))
                self._align_btns[a] = btn
                pos_grid.addWidget(btn, r, c)
        pf_row.addWidget(pos_box)

        # Font
        fnt_box = QGroupBox("Font")
        fnt_box.setStyleSheet(_GROUP_CSS)
        fnt_lay = QVBoxLayout(fnt_box)
        fnt_lay.setSpacing(3)
        fnt_lay.setContentsMargins(6, 10, 6, 4)

        self._font_cb = QComboBox()
        self._font_cb.addItems([
            "Arial", "Arial Black", "Helvetica", "Helvetica Neue",
            "Impact", "Georgia", "Verdana", "Trebuchet MS",
            "Times New Roman", "Futura", "Comic Sans MS",
        ])
        self._font_cb.setStyleSheet("font-size: 11px;")
        self._font_cb.currentTextChanged.connect(
            lambda v: self._set("font_family", v)
        )

        sz_row = QHBoxLayout()
        sz_row.addWidget(QLabel("Size:"))
        self._size_sp = QSpinBox()
        self._size_sp.setRange(14, 140)
        self._size_sp.setValue(52)
        self._size_sp.setFixedWidth(56)
        self._size_sp.valueChanged.connect(lambda v: self._set("font_size", v))
        sz_row.addWidget(self._size_sp)
        sz_row.addStretch()

        bi_row = QHBoxLayout()
        self._bold_cb = QCheckBox("Bold")
        self._bold_cb.toggled.connect(lambda v: self._set("bold", v))
        self._ital_cb = QCheckBox("Italic")
        self._ital_cb.toggled.connect(lambda v: self._set("italic", v))
        bi_row.addWidget(self._bold_cb)
        bi_row.addWidget(self._ital_cb)
        bi_row.addStretch()

        fnt_lay.addWidget(self._font_cb)
        fnt_lay.addLayout(sz_row)
        fnt_lay.addLayout(bi_row)
        pf_row.addWidget(fnt_box)

        root.addLayout(pf_row)

        # ── Colors ───────────────────────────────────────────────────── #
        col_box = QGroupBox("Colors")
        col_box.setStyleSheet(_GROUP_CSS)
        col_grid = QGridLayout(col_box)
        col_grid.setSpacing(4)
        col_grid.setContentsMargins(8, 10, 8, 6)

        self._txt_col = _ColorButton((255, 255, 255, 255))
        self._out_col = _ColorButton((0, 0, 0, 255))
        self._box_col = _ColorButton((0, 0, 0, 160))
        self._txt_col.color_changed.connect(lambda c: self._set("primary_color", c))
        self._out_col.color_changed.connect(lambda c: self._set("outline_color", c))
        self._box_col.color_changed.connect(lambda c: self._set("back_color", c))

        col_grid.addWidget(QLabel("Text"), 0, 0)
        col_grid.addWidget(self._txt_col, 0, 1)
        col_grid.addWidget(QLabel("Outline"), 0, 2)
        col_grid.addWidget(self._out_col, 0, 3)
        col_grid.addWidget(QLabel("Box"), 1, 0)
        col_grid.addWidget(self._box_col, 1, 1)

        root.addWidget(col_box)

        # ── Effects + Word Effect (merged group) ─────────────────────── #
        fx_box = QGroupBox("Effects")
        fx_box.setStyleSheet(_GROUP_CSS)
        fx_grid = QGridLayout(fx_box)
        fx_grid.setSpacing(4)
        fx_grid.setContentsMargins(8, 12, 8, 6)

        self._outline_sp = QDoubleSpinBox()
        self._outline_sp.setRange(0, 12)
        self._outline_sp.setSingleStep(0.5)
        self._outline_sp.setValue(2.5)
        self._outline_sp.setFixedWidth(54)
        self._outline_sp.valueChanged.connect(lambda v: self._set("outline_width", v))

        self._shadow_sp = QDoubleSpinBox()
        self._shadow_sp.setRange(0, 12)
        self._shadow_sp.setSingleStep(0.5)
        self._shadow_sp.setValue(0.0)
        self._shadow_sp.setFixedWidth(54)
        self._shadow_sp.valueChanged.connect(lambda v: self._set("shadow_depth", v))

        self._bstyle_cb = QComboBox()
        self._bstyle_cb.addItems(["Outline", "Box"])
        self._bstyle_cb.setFixedWidth(76)
        self._bstyle_cb.setToolTip(
            "Outline: text outline + shadow\n"
            "Box: opaque filled box behind text"
        )
        self._bstyle_cb.currentIndexChanged.connect(
            lambda i: self._set("border_style", 1 if i == 0 else 3)
        )

        self._margin_sp = QSpinBox()
        self._margin_sp.setRange(0, 400)
        self._margin_sp.setValue(50)
        self._margin_sp.setFixedWidth(54)
        self._margin_sp.valueChanged.connect(lambda v: self._set("margin_vertical", v))

        self._word_effect_cb = QComboBox()
        self._word_effect_cb.addItems(["None", "Highlight", "Appear", "AI Emphasis"])
        self._word_effect_cb.setToolTip(
            "None: full subtitle line\n"
            "Highlight: active word pops + glows in highlight color\n"
            "Appear: words appear one by one as spoken\n"
            "AI Emphasis: key words are auto-highlighted"
        )
        self._word_effect_cb.currentTextChanged.connect(
            lambda v: self._set("word_effect", v.lower().replace(" ", "_"))
        )

        self._highlight_col = _ColorButton((255, 215, 0, 255))
        self._highlight_col.color_changed.connect(lambda c: self._set("highlight_color", c))

        fx_grid.addWidget(QLabel("Outline px:"), 0, 0)
        fx_grid.addWidget(self._outline_sp,      0, 1)
        fx_grid.addWidget(QLabel("Shadow:"),      0, 2)
        fx_grid.addWidget(self._shadow_sp,        0, 3)
        fx_grid.addWidget(QLabel("Box style:"),   1, 0)
        fx_grid.addWidget(self._bstyle_cb,        1, 1)
        fx_grid.addWidget(QLabel("Margin V:"),    1, 2)
        fx_grid.addWidget(self._margin_sp,        1, 3)
        fx_grid.addWidget(QLabel("Animation:"),   2, 0)
        fx_grid.addWidget(self._word_effect_cb,   2, 1)
        fx_grid.addWidget(QLabel("Glow color:"),  2, 2)
        fx_grid.addWidget(self._highlight_col,    2, 3)

        root.addWidget(fx_box)
        root.addStretch()

    # ------------------------------------------------------------------ #
    #  Logic                                                               #
    # ------------------------------------------------------------------ #

    def _select_preset(self, name: str, emit: bool = True) -> None:
        for n, card in self._cards.items():
            card.set_selected(n == name)
        if name in PRESETS:
            self._style = PRESETS[name].clone()
            self._load_to_ui()
            if emit:
                self.style_changed.emit(self._style.clone())

    def _load_to_ui(self) -> None:
        s = self._style

        def _bs(w, fn):
            w.blockSignals(True); fn(); w.blockSignals(False)

        _bs(self._font_cb, lambda: self._font_cb.setCurrentIndex(
            max(0, self._font_cb.findText(s.font_family))))
        _bs(self._size_sp, lambda: self._size_sp.setValue(s.font_size))
        _bs(self._bold_cb, lambda: self._bold_cb.setChecked(s.bold))
        _bs(self._ital_cb, lambda: self._ital_cb.setChecked(s.italic))

        self._txt_col.set_color(s.primary_color)
        self._out_col.set_color(s.outline_color)
        self._box_col.set_color(s.back_color)

        _bs(self._outline_sp, lambda: self._outline_sp.setValue(s.outline_width))
        _bs(self._shadow_sp, lambda: self._shadow_sp.setValue(s.shadow_depth))
        _bs(self._bstyle_cb, lambda: self._bstyle_cb.setCurrentIndex(
            0 if s.border_style == 1 else 1))
        _bs(self._margin_sp, lambda: self._margin_sp.setValue(s.margin_vertical))

        _WE_MAP = {"none": "None", "highlight": "Highlight", "appear": "Appear", "ai_emphasis": "AI Emphasis"}
        _bs(self._word_effect_cb,
            lambda: self._word_effect_cb.setCurrentText(_WE_MAP.get(s.word_effect, "None")))
        self._highlight_col.set_color(s.highlight_color)

        for a, btn in self._align_btns.items():
            btn.setChecked(a == s.alignment)

    def _on_align(self, a: int) -> None:
        for av, btn in self._align_btns.items():
            btn.setChecked(av == a)
        self._style.alignment = a
        self._deselect_presets()
        self.style_changed.emit(self._style.clone())

    def _set(self, attr: str, value) -> None:
        setattr(self._style, attr, value)
        self._deselect_presets()
        self.style_changed.emit(self._style.clone())

    def _deselect_presets(self) -> None:
        for card in self._cards.values():
            card.set_selected(False)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def current_style(self) -> SubtitleStyle:
        return self._style.clone()

    def active_preset_name(self) -> str:
        for name, card in self._cards.items():
            if card._selected:
                return name
        return "Custom"
