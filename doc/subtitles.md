We need to redesign the subtitle rendering and animation system in CutVideos to support modern TikTok / Reels / Shorts subtitle styles similar to CapCut, Submagic, Captions.ai, and viral creator content.

The current subtitle system is too static. We already support subtitle rendering, styling, word timestamps, and real-time preview, but we now want highly dynamic animated subtitles optimized for retention and social media engagement.

The new system must support:

# Core Goal

Subtitles should feel alive and synchronized with speech.

As the person speaks:

* words appear in sync
* active words animate
* important words become larger
* emphasis words can become yellow
* subtitles slightly scale/pop with the voice

The experience should resemble modern TikTok captions.

---

# Required Features

## 1. Active Word Highlighting

Using word-level timestamps from faster-whisper:

* The currently spoken word becomes:

  * yellow (configurable)
  * larger
  * slightly animated
  * optionally glowing

Example:

Normal words:
WHITE

Active spoken word:
BIG YELLOW + SCALE EFFECT

The active word should update in real time while the video plays.

---

# 2. Word-by-Word Subtitle Reveal

Instead of displaying the full subtitle immediately:

Words should appear progressively as they are spoken.

Example:

Time 0.0:
"Today"

Time 0.3:
"Today we"

Time 0.6:
"Today we are"

etc.

This must use the exact word timestamps from whisper.

---

# 3. TikTok-Style Pop Animation

When a word becomes active:

* slightly scale up
* then smoothly scale down
* very fast animation (~120–200ms)

This creates the energetic TikTok subtitle effect.

Animation ideas:

* scale pop
* bounce
* glow pulse
* opacity fade-in

Animations must remain smooth during playback.

---

# 4. Smart Emphasis System

We want an optional AI emphasis system.

The system should automatically detect:

* emotional words
* louder words
* exciting moments
* chess terminology
* strong expressions

Examples:

* "INSANE"
* "SACRIFICE"
* "CHECKMATE"

Those words can automatically:

* become yellow
* become larger
* receive stronger animation

But NOT every word should be emphasized.

The emphasis must feel natural and selective.

---

# 5. Modern Subtitle Layout

We want TikTok-style subtitle positioning:

* centered horizontally
* near bottom-middle safe zone
* large readable font
* thick outline
* mobile-first sizing

Must support:

* drag subtitles freely
* reposition visually
* save positions

---

# 6. Real-Time Preview

The preview inside the editor must exactly match export rendering.

No difference between:

* preview
* exported video

Animations and active word rendering must appear live while editing.

---

# 7. Performance Requirements

The system must remain smooth:

* during playback
* during scrubbing
* during subtitle editing

Even with:

* animations
* word-level rendering
* glow/shadow effects

We should optimize rendering carefully.

---

# 8. Suggested Technical Direction

The current ASS-based approach may become limiting.

Please evaluate:

* QGraphicsScene
* QML scene rendering
* GPU-accelerated subtitle layers

We likely need:

* per-word rendering
* animation timelines
* transform support
* scaling
* opacity animation

ASS alone may not be sufficient for modern subtitle effects.

---

# 9. Future Extensibility

The system should later support:

* presets (Hormozi, Podcast, Gaming, Chess)
* kinetic typography
* animated subtitle templates
* motion presets
* keyframes
* subtitle transitions

Architecture should be modular and extensible.

---

# Final Vision

We want subtitles that feel:

* modern
* viral
* dynamic
* expressive
* synchronized with speech

NOT static movie subtitles.

The goal is to make CutVideos feel like:

* CapCut
* Captions.ai
* Submagic

But:

* local
* faster
* customizable
* creator-focused
* optimized for chess and educational creators.
