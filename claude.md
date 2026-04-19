# HypeBot — Claude Code Briefing

## What is HypeBot?
HypeBot is a Python tool that automatically generates YouTube Shorts highlight clips from Super Smash Bros. Ultimate tournament VODs. It downloads a VOD from YouTube or Twitch, detects the final KO moment of each game using flash detection, and cuts polished 9:16 vertical clips with a blurred background effect — ready to upload directly to YouTube Shorts, TikTok, or Instagram Reels.

The target audience is the FGC (Fighting Game Community). The inspiration is channels like Yeet Smash that produce short, hype, digestible Smash clips.

---

## Project Structure

```
HypeBot/
├── server.py         # Flask web server (primary UI — browser based)
├── app.py            # Tkinter desktop app (kept for reference, not primary)
├── detector.py       # Core detection + clip cutting engine
├── templates/
│   └── index.html    # HypeBot web UI (served by Flask)
├── downloads/        # Downloaded VODs stored here (gitignored)
├── clips/            # Generated clips stored here (gitignored)
│   └── [video title]/
│       ├── vertical/ # 9:16 blurred background Shorts (primary output)
│       └── original/ # 16:9 re-encoded clips (review + regular YouTube)
└── CLAUDE.md         # This file
```

---

## Tech Stack
- **Python 3.13**
- **yt-dlp** — VOD downloading from YouTube and Twitch
- **OpenCV (cv2)** — frame-by-frame brightness analysis for flash detection
- **FFmpeg** — video cutting, scaling, blurring, encoding
- **Flask** — web server for browser UI
- **Tkinter** — desktop UI (secondary, kept for reference)

---

## How the Pipeline Works

1. **Download** — yt-dlp downloads the VOD to `downloads/[title].mp4`
2. **Cache check** — if `downloads/[title]_ko_cache.json` exists, skip scan
3. **Flash detection** — OpenCV scans every 2nd frame for brightness spikes
4. **KO identification** — flashes longer than 0.3s are confirmed KO victory screens
5. **Timestamp calculation** — KO timestamp = victory flash timestamp - 6 seconds
6. **Cache save** — KO events saved to JSON so repeat runs skip the scan
7. **Clip cutting** — FFmpeg cuts two outputs per KO:
   - `vertical/` — 9:16 with blurred background (Shorts ready)
   - `original/` — 16:9 re-encoded clean cut
8. **Output** — clips organized into `clips/[video title]/vertical/` and `clips/[video title]/original/`

---

## Key Constants in detector.py

```python
BRIGHTNESS_THRESHOLD = 220    # Brightness level to trigger flash detection
MIN_FLASH_DURATION_SEC = 0.3  # Minimum flash duration (filters character select screens)
FRAME_SKIP = 2                # Analyze every Nth frame (performance optimization)
KO_OFFSET_SEC = 6.0           # Seconds before victory flash = actual KO timestamp
CLIP_BEFORE_SEC = 10.0        # Seconds of footage before KO to include
CLIP_AFTER_SEC = 3.0          # Seconds of footage after KO to include
BLUR_STRENGTH = 20            # Boxblur intensity for vertical clip background
FFMPEG_TIMEOUT = 120          # Max seconds per FFmpeg call before timeout
```

---

## Vertical Clip Format
- **Canvas:** 9:16 (e.g. 606x1080 for 1080p source)
- **Background:** source frame scaled to fill canvas + heavy boxblur
- **Foreground:** source frame scaled to fit canvas width, sharp, centered vertically
- **Result:** blurred background fills top/bottom bars, gameplay is crisp in center
- This matches the aesthetic of successful FGC Shorts channels

---

## Flash Detection — How It Works
Smash Ultimate has a distinctive full-screen white flash on every final stock KO. This flash:
- Lasts ~0.73–0.80 seconds (very consistent)
- Is preceded ~6 seconds later by a victory screen
- Is much longer than false positives (character select flashes = ~0.07s)

The detector scans brightness per frame, identifies sustained white flashes above threshold, filters by duration, and works backward 6 seconds to find the actual KO moment.

---

## Current State (as of this session)
- ✅ VOD downloading works (YouTube + Twitch via yt-dlp)
- ✅ Flash detection works reliably on tested VODs
- ✅ KO event caching works (JSON cache next to VOD file)
- ✅ Clip cutting works (two separate FFmpeg calls per clip — dual output in single call causes hanging)
- ✅ Vertical 9:16 blurred background effect works and looks great
- ✅ Flask web UI works at localhost:5000
- ✅ Clips organized by video title into subfolders
- ✅ Re-download skipped if VOD already in downloads folder
- ⚠️ yt-dlp shows JS runtime warning (non-blocking, cosmetic only)

---

## Known Issues / Gotchas
- **Dual FFmpeg output hangs** — running two outputs in a single FFmpeg call causes it to freeze. Always use two separate sequential FFmpeg calls instead.
- **Fast seek artifacts** — `-ss` before `-i` is fast but can cause slight timestamp drift. Current approach uses `-ss` before `-i` with re-encoding which works fine in practice.
- **Stream layout variance** — some VODs have webcam overlays baked in. The vertical crop shows the full frame (including webcams) scaled down, which is acceptable for now.
- **Cache with 0 events** — if a scan returns 0 events it still saves a cache. On re-run it detects empty cache and re-scans.

---

## Phase Roadmap

### Phase 1 — COMPLETE ✅
Core pipeline: download → detect → cut → output vertical Shorts

### Phase 2 — IN PROGRESS 🔨
**Clip Review + Hook Line UI (browser based)**
- Watch generated clips inside HypeBot browser UI
- Load clips from previous sessions
- Per-clip hook line (bold text burned onto the Short — top or bottom bar)
- Render final Short with hook line applied
- Goal: paste URL → generate → review → add hook → render → upload

### Phase 3 — PLANNED
- Timed captions (text appears/disappears at specific moments)
- Slow motion on kill frame
- Zoom punch effect
- Sound effects
- Intro/outro HypeBot branding
- Batch processing (multiple URLs)
- Thumbnail auto-generation

---

## Distribution Plan
- **Now:** personal tool for local FGC content
- **Near term:** regionals and majors, clipping notable players
- **Future options:**
  - Open source on GitHub (already at https://github.com/fchebbo/HypeBot)
  - Productize / hosted SaaS on AWS or Oracle VM
  - The Flask architecture already supports moving from localhost to hosted

---

## Development Notes
- Always run FFmpeg as two separate calls (vertical + original) — never combined
- The `detector.py` module is backend-only — no UI code in it
- `server.py` is the production path, `app.py` is legacy Tkinter kept for reference
- Python virtual environment is at `.venv/`
- FFmpeg is at `C:\ffmpeg-master-latest-win64-gpl-shared\bin`
- Node.js v24.15.0 is installed
- Developer is a Java dev comfortable with Python, using PyCharm + Git Bash