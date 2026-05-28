# Cutyit

Cutyit is a macOS video editor built around one workflow: open a clip, transcribe it with Whisper, edit the subtitles, and export. Everything happens locally — no cloud, no account, no subscription.

The subtitle editor has a live preview that updates as you type, word-level animation (highlighted word follows the speaker in real time), and a style system with presets that match what you'd see on TikTok or Reels. When you're done, you can burn the subtitles in permanently or keep them as a soft track.

---

## Download

Grab the latest `.dmg` from [Releases](https://github.com/lexisvar/cutyvideo/releases), drag Cutyit to Applications, and open it. The first run will ask for permission to open an app from the internet — that's standard Gatekeeper behavior.

---

## What it does

**Video editing**
- Split a video at any point into segments using the timeline or by typing a timecode
- Detect silence automatically and use that as a splitting guide
- Export individual segments as lossless stream copies (no re-encode, no quality loss)

**Transcription**
- Runs [faster-whisper](https://github.com/SYSTRAN/faster-whisper) locally on your machine — nothing gets sent anywhere
- Word-level timestamps from the start, so every word can be animated independently
- Supports all Whisper model sizes (`tiny` through `large-v3`) and over 100 languages
- Can transcribe the full video or just a selected segment

**Subtitle editor**
- Table view with editable start time, end time, and text per line
- Preview updates on every keystroke — what you see in the player is exactly what gets exported
- Drag subtitles to reposition on screen

**Styles**
Eight built-in presets (TikTok, Reels, YouTube, Neon, Impact, Minimal, Instagram, TikTok Box) plus full manual control over font, size, colors, outline, shadow, box background, alignment, and margins.

**Word effects**
- *Highlight*: the current spoken word changes color in sync with the audio
- *Appear*: words materialize one by one as the speaker says them

**Export**
- Burn subtitles permanently into the video via FFmpeg + libass
- Embed as a soft SRT track inside an MKV container
- Save standalone `.srt` or `.vtt` files

---

## Building from source

You'll need Python 3.10+ and FFmpeg installed (`brew install ffmpeg`).

```bash
git clone git@github.com:lexisvar/cutyvideo.git
cd cutyvideo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The first time you run a transcription, faster-whisper downloads the selected model to `~/.cache/huggingface/`. The `small` model is ~465 MB and a good starting point — accurate enough for most content and fast on Apple Silicon.

---

## Building a signed .app

```bash
bash scripts/build_mac.sh
```

This uses PyInstaller to bundle the app, then deep-signs it with the Developer ID Application certificate from your keychain. The output is a signed `.dmg` in `dist/`.

To also notarize (required for distribution outside the App Store):

```bash
APPLE_ID=you@example.com APP_PASSWORD=xxxx-xxxx-xxxx-xxxx bash scripts/build_mac.sh --notarize
```

`APP_PASSWORD` is an [app-specific password](https://support.apple.com/en-us/102654) from appleid.apple.com, not your Apple ID password.

---

## Model sizes

| Model | Download size | Notes |
|---|---|---|
| tiny | ~75 MB | Fast, lower accuracy |
| base | ~145 MB | Good for clear speech |
| small | ~465 MB | Default, solid all-around |
| medium | ~1.5 GB | Noticeably better on accents |
| large-v3 | ~3.1 GB | Best quality |

On an M-series Mac, a 2-minute clip transcribes in roughly 10–20 seconds with `small`.

---

## Requirements

- macOS 12 or later (Apple Silicon and Intel)
- FFmpeg — `brew install ffmpeg`
- Python 3.10+ (only needed if running from source)

---

## License

MIT
