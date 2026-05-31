# CutVideos — Vision & Feature Roadmap

## Overview

CutVideos is evolving from a subtitle utility into a fast, creator-focused vertical video editor optimized for:

- TikTok
- Instagram Reels
- YouTube Shorts
- Chess creators
- Educational creators
- Talking-head videos

The goal is not to compete with full professional editors like Premiere or DaVinci Resolve.

The goal is to become:

> The fastest AI-powered subtitle and short-form video editor for creators.

Especially:
- Local-first
- Extremely fast
- Minimal friction
- Optimized for subtitles and retention
- Specialized for chess and educational content

---

# Core Philosophy

The editing workflow must feel:

- Instant
- Visual
- Draggable
- Keyboard-first
- Template-driven
- “What You See Is What You Upload”

Users should be able to:
1. Drop a video
2. Generate subtitles
3. Apply a style
4. Make quick edits
5. Export for TikTok

In minutes.

---

# Major Planned Features

# 1. Canvas-Based Editing System

## Goal

Replace static subtitle rendering with a true interactive editing canvas.

## New Architecture

```text
Video Canvas
├── Video Layer
├── Subtitle Layer
├── Effects Layer
├── Sticker/Image Layer
├── Safe Zone Guides
└── Interaction Layer
```

## Features

- Drag subtitles freely
- Resize subtitles visually
- Rotate subtitle blocks
- Bounding box editing
- Snap-to-center guides
- Multiple subtitle regions
- Layer selection system

---

# 2. Draggable Subtitle System ✅

## Implemented

- ✅ Click subtitle
- ✅ Drag anywhere (live repositioning)
- ✅ Double-click to reset position
- ✅ Live visual feedback
- 🔲 Resize with handles
- 🔲 Rotate slightly
- 🔲 Snap guides / magnetic alignment
- 🔲 Safe-zone snapping

---

# 3. Visual Timeline Editor ✅ (Phase 2)

## Implemented

- ✅ Subtitle segments displayed on timeline track
- ✅ Zoom timeline (Cmd+Scroll; double-click to reset)
- ✅ Pan when zoomed (plain scroll)
- ✅ Silence detection → auto split points
- 🔲 Drag edges to resize subtitle timing
- 🔲 Audio waveform visualization
- 🔲 Timeline snapping
- 🔲 Multi-select editing

---

# 4. Keyboard-First Workflow ✅

| Action | Shortcut | Status |
|---|---|---|
| Play/Pause | Space | ✅ |
| Split Subtitle | S | ✅ |
| Cut Clip | C | ✅ |
| Next Subtitle | Down Arrow | ✅ |
| Previous Subtitle | Up Arrow | ✅ |
| Nudge Timing Left | Alt + Left | ✅ |
| Nudge Timing Right | Alt + Right | ✅ |
| Add Subtitle at Playhead | Enter | ✅ |
| Zoom Timeline | Cmd + Scroll | ✅ |
| Delete Subtitle | Backspace | ✅ |

---

# 5. Smart Subtitle Chunking ✅

## Goal

Generate TikTok-optimized subtitle pacing automatically.

## Implemented

- ✅ Smart phrase splitting (Auto-chunk button)
- ✅ Max-words-per-chunk selector (2–6 words)
- ✅ Proportional timing across chunks
- 🔲 Reading speed optimization
- 🔲 Retention-focused pacing heuristics

---

# 6. Animated Subtitle Presets ✅

| Preset | Style | Status |
|---|---|---|
| TikTok | Bold white outline | ✅ |
| TikTok Box | Yellow on dark box | ✅ |
| Reels | Clean drop shadow | ✅ |
| YouTube | White on black box | ✅ |
| Neon | Cyan glow | ✅ |
| Impact | Bold uppercase | ✅ |
| Minimal | Thin clean | ✅ |
| Top Bar | Upper placement | ✅ |
| Alex Hormozi | Aggressive emphasis | ✅ |
| Podcast | Minimal clean | ✅ |
| MrBeast | Punch scaling | ✅ |
| Gaming | Neon bounce | ✅ |
| Cinematic | Smooth fade | ✅ |
| Chess Streamer | Elegant minimal | ✅ |

## Planned Animations

- Pop scale
- Bounce
- Slide-in
- Motion blur
- Glow pulse
- Opacity fade
- Rotation punch
- Dynamic word scaling

---

# 7. Word Emphasis AI ✅

## Implemented

- ✅ `ai_emphasis` word-effect mode
- ✅ Heuristic detection: ALL CAPS words, numbers/percentages,
  emotional emphasis terms, chess terminology (blunder/brilliant/checkmate…)
- ✅ Emphasized words rendered in highlight colour; others in primary colour
- ✅ Selectable in the Style panel alongside Highlight and Appear modes
- 🔲 ML-powered detection (loud words, emotional peaks)
- 🔲 Size increase / pop animations per word

---

# 8. TikTok / Reels Safe Zones ✅

## Implemented

- ✅ TikTok safe-zone overlay (top navigation + bottom controls)
- ✅ Instagram Reels safe-zone overlay
- ✅ YouTube Shorts safe-zone overlay
- ✅ Semi-transparent danger zone fills + dashed safe-region border
- ✅ Platform label on overlay
- ✅ Toggle combo box in preview player (Off / TikTok / Reels / Shorts)

---

# 9. AI Camera & Zoom Effects

## Planned Features

- Face tracking
- Auto punch zooms
- Smart reframing
- Vertical auto-crop
- Dynamic speaker framing

---

# 10. Chess-Specific Features

## Planned Features

- PGN synchronization
- Move overlays
- Square highlights
- Tactical alerts
- Evaluation swing detection
- Animated arrows

---

# 11. One-Click Social Export ✅

## Implemented

### TikTok Export ✅
- ✅ 1080×1920 scale+pad (letterbox black)
- ✅ H.264 CRF 22 fast preset
- ✅ Loudness normalization to −14 LUFS (EBU R128)
- ✅ AAC 192 kbps audio

### Reels Export ✅
Optimized for Instagram (same pipeline as TikTok).

### Shorts Export ✅
Optimized for YouTube Shorts (same pipeline).

### UI ✅
- ✅ Platform picker (TikTok / Reels / Shorts) + Export button in Edit tab
- ✅ Background worker with progress status

---

# 12. AI Content Pipeline

## Workflow

1. Import long video
2. Detect exciting moments
3. Generate subtitles
4. Auto-cut clips
5. Apply style preset
6. Export shorts

---

# 13. Modern Creative UI

## Inspiration

- CapCut
- DaVinci Resolve
- Figma
- OBS Studio

## UI Improvements

- Larger preview
- Floating panels
- Dockable windows
- Cinematic dark theme
- Layer system
- Live animation controls

---

# 14. Rendering & Engine Improvements

## Planned Direction

Move toward:
- Qt Graphics Scene
OR
- QML Canvas Rendering

## Benefits

- Real-time transforms
- Animation engine
- Keyframe system
- Better performance
- Layer compositing

---

# 15. Ultimate Product Direction

## Vision

CutVideos becomes:

> The fastest local AI subtitle editor for short-form creators.

## Competitive Positioning

Competing against:
- CapCut
- Captions.ai
- Submagic

Advantages:
- Local processing
- Faster workflow
- More customizable
- Chess-focused features
- Creator-focused UX

---

# Suggested Development Priority

## Phase 1 — Workflow Foundation ✅ COMPLETE

- ✅ Draggable subtitles (live preview)
- ✅ Visual timeline (segments + subtitle track + zoom)
- ✅ Full keyboard shortcut set
- ✅ Smart subtitle chunking (auto-chunk)
- ✅ Safe-zone overlays (TikTok/Reels/Shorts)
- ✅ One-click social export

## Phase 2 — Viral Subtitle Features ✅ COMPLETE

- ✅ 14 animated subtitle presets
- ✅ Word Emphasis AI (ai_emphasis mode)
- ✅ Timeline subtitle track visualisation
- ✅ Timeline zoom (Cmd+Scroll)
- ✅ Silence detection → auto split points
- ✅ Enter key: add subtitle at playhead
- 🔲 Motion effects (keyframe animation)
- 🔲 Pop/bounce animations per word

## Phase 3 — AI & Chess Features ✅ (In Progress)

- ✅ WebVTT export (.vtt — for web video players)
- ✅ Find & Replace in subtitle table
- ✅ Auto-split at regular time intervals (configurable spinbox)
- ✅ PGN chess import → subtitle rows with move notation
- 🔲 Chess overlays (board squares, arrows)
- 🔲 Auto clip extraction
- 🔲 Tactical moment detection
- 🔲 AI zooms

## Phase 4 — Clip Editor (In Progress)

### Step 1 — Cut & Remove 🔲
- Split points create visual clip segments on the video track
- Click segment → mark as deleted (greyed out / excluded)
- On export → FFmpeg concat skips excluded segments
- Keyboard shortcut to toggle segment inclusion

### Step 2 — Reorder Clips 🔲
- Drag clip segments on the video track to change playback order
- Timeline redraws sequence live
- FFmpeg concat respects the new order on export

### Step 3 — Join & Export 🔲
- Export joined clip as a single video file
- Optionally run transcription + subtitle pipeline on the joined clip

### Step 4 — Subtitle Translation 🔲
- Translate existing subtitle rows to a target language
- `deep-translator` backend (Google Translate, no API key)
- Worker thread pattern, per-row progress
- Language dropdown in SubtitleEditorWidget

### Step 5 — Transitions (Last) 🔲
- Cross-fade, fade-to-black between clip segments
- UI handles between segments to pick transition type/duration
- FFmpeg `xfade` filter with precise offset calculation

---

# Final Product Goal

The ideal experience:

```text
Drop video
→ AI transcribes
→ AI styles subtitles
→ Quick visual edits
→ Export
→ Upload to TikTok
```

In under 5 minutes.
