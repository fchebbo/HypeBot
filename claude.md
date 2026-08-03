# HypeBot — Claude Code Briefing

## What is HypeBot?
HypeBot is a Python tool that automatically generates YouTube Shorts highlight clips from Super Smash Bros. Ultimate tournament VODs. It downloads a VOD from YouTube or Twitch, detects KO moments using flash detection, and cuts polished 9:16 vertical clips with a blurred background effect — ready to upload directly to YouTube Shorts, TikTok, or Instagram Reels. Beyond the core clipper, it's grown into a full post-production suite: hook text, slow-motion replays, montages, stitched multi-clip stories, audio "dankify" processing, beat-synced edits, compilation reels, and a permanent curated archive.

The target audience is the FGC (Fighting Game Community). The inspiration is channels like Yeet Smash that produce short, hype, digestible Smash clips. HypeBot powers SoCal Smash on YouTube.

---

## Project Structure

```
HypeBot/
├── server.py          # Flask web server (primary UI — browser based). ~1480 lines, 40+ routes
├── renderer.py         # All FFmpeg render functions — text, replay, montage, dankify, hype reel, beat sync, etc. ~2200 lines
├── detector.py         # VOD download + KO detection + clip cutting engine
├── app.py              # Tkinter desktop app — legacy prototype, kept for reference, not the production path
├── main.py             # Unused PyCharm boilerplate stub — not part of the app, safe to ignore/delete
├── templates/
│   ├── index.html          # Main UI — generate, review, flag/skip, add text, manual clip
│   ├── montage.html         # Montage from vertical clips
│   ├── montage_original.html# Montage from 16:9 original clips
│   ├── replay.html          # "Did You Catch It?" slow-motion replay
│   ├── hookslomo.html       # Hook + slo-mo on a single clip (above text + zoom)
│   ├── stitch.html          # Stitch two clips' KO hooks into one Short
│   ├── dankify.html         # Audio compression / punch-up
│   ├── fadetotext.html      # Fade-to-text transition effect
│   ├── hypereel.html        # Multi-clip compilation reel w/ title, logo, outro music
│   ├── beat_sync.html       # Beat-synced edit against a music track
│   └── archive.html         # Browse/run the permanent archive
├── downloads/           # Downloaded VODs stored here (gitignored)
├── clips/               # Generated clips stored here (gitignored)
│   └── [video title]/
│       ├── vertical/        # 9:16 blurred background Shorts (primary output)
│       ├── original/        # 16:9 re-encoded clips (review + regular YouTube)
│       ├── finals/          # Rendered clips with hook text burned in
│       ├── montage/         # Montage outputs
│       ├── replay/          # Replay tool outputs
│       ├── dankify/         # Dankify outputs
│       └── (stitch, hype_reels, etc. — created per-tool as needed)
├── archive/              # Permanent curated library, gitignored, grouped by month (YYYY-MM)
├── Props/                # Logos, music, and other assets used by render tools
├── ARCHIVE_DESIGN.md     # Archive system design doc (implemented — see Current State)
├── BATCH_PROCESSING.md   # Design brief — NOT implemented, see below
├── YOUTUBE_UPLOAD.md     # Design brief — NOT implemented, see below
└── claude.md             # This file
```

---

## Tech Stack
- **Python 3.13**
- **yt-dlp** — VOD downloading from YouTube and Twitch
- **OpenCV (cv2)** — frame-by-frame brightness analysis for flash detection
- **FFmpeg** — video cutting, scaling, blurring, encoding (external binary, not a pip package)
- **Flask** — web server for browser UI
- **Pillow / numpy** — text overlay rendering and frame analysis
- **Tkinter** — desktop UI (`app.py`, legacy, not the production path)

---

## How the Pipeline Works

1. **Download** — yt-dlp downloads the VOD to `downloads/[title].mp4`
2. **Cache check** — if `downloads/[title]_ko_cache.json` exists, skip scan
3. **Flash detection** — OpenCV scans frames (every 4th frame, `FRAME_SKIP=4`) for two independent signals: a full-screen **white victory flash** and a **red hit-flash** (fires at the actual KO hit, not the victory screen). See "Flash Detection" below.
4. **KO identification** — events from both detectors are merged if they land within `RED_MERGE_WINDOW_SEC` of each other; duration filters reject short flashes (character-select, etc.)
5. **Timestamp calculation** — white-flash events use `KO_OFFSET_SEC` (6s back from the victory flash); red-flash events use the much smaller `RED_KO_OFFSET_SEC` (0.5s), since the red flash fires at the moment of the hit
6. **Cache save** — KO events saved to JSON so repeat runs skip the scan
7. **Clip cutting** — FFmpeg cuts two outputs per KO **as two separate sequential calls** (never combined — see Known Issues):
   - `vertical/` — 9:16 with blurred background (Shorts ready)
   - `original/` — 16:9 re-encoded clean cut
8. **Output** — clips organized into `clips/[video title]/vertical/` and `clips/[video title]/original/`
9. From there, clips flow into the review UI and any of the post-production tools listed below.

---

## Key Constants in detector.py

```python
# White (victory) flash detection
MIN_FLASH_DURATION_SEC = 0.3
MAX_FLASH_DURATION_SEC = 1.5
FRAME_SKIP             = 4      # grab() skips without decoding — safe to go higher
KO_OFFSET_SEC          = 6.0
CLIP_BEFORE_SEC        = 10.0
CLIP_AFTER_SEC         = 3.0
FFMPEG_TIMEOUT         = 120
BLUR_STRENGTH          = 20     # background blur for vertical clips (10-30 recommended)

SCAN_LOG_INTERVAL      = 5000   # frames between scan progress updates in browser
SCAN_RESIZE_W          = 320    # resize frames to this width before brightness check
BRIGHT_PIXEL_THRESHOLD = 185    # min per-channel brightness to count as "white"
BRIGHT_PIXEL_SPREAD    = 40     # max channel spread — filters colored (non-white) flashes
BRIGHT_PIXEL_RATIO     = 0.55   # fraction of true-white pixels required to trigger
FLASH_SPIKE            = 0.30   # jump above rolling baseline required to trigger
ROLLING_WINDOW         = 40     # decoded frames tracked for baseline (~3-4s at FRAME_SKIP=4)

# Red hit-flash detection (fires at the KO hit itself, not the victory screen)
RED_PIXEL_THRESHOLD_R       = 180
RED_PIXEL_THRESHOLD_GB      = 110   # max green/blue — 110 also catches orange-red bursts
RED_PIXEL_RATIO             = 0.13
RED_KO_OFFSET_SEC           = 0.5
MIN_RED_FLASH_SEC           = 0.3
MAX_RED_FLASH_SEC           = 1.8
RED_MERGE_WINDOW_SEC        = 10.0  # red event within this window of a white event = same KO
RED_FLASH_GAP_TOLERANCE_SEC = 0.2   # brief sub-threshold dips don't end an in-progress flash
```

Note: `BRIGHTNESS_THRESHOLD` (the single flat brightness cutoff from earlier versions) is retired — detection is now ratio-of-white-pixels based, with the red hit-flash detector layered on top.

---

## Feature Set / Tool Pages

All are Flask routes serving their own page + a `/run-*` POST endpoint that renders in a background thread and streams progress via the shared `/logs` SSE stream.

| Page | Route | What it does |
|---|---|---|
| Main / Review | `/` | Generate from URL or file, review clips, flag/skip, add hook text, manual clip cutting |
| Hook + Slo-Mo | `/hook-slowmo` | Burns above-text onto a clip and applies a slow-motion window with optional zoom and transition |
| Replay | `/replay` | "Did You Catch It?" — plays a clip once at full speed, then replays with a slow-motion zoom on the key moment, with crossfade and optional KO-hook trim |
| Stitch | `/stitch` | Combines the KO hooks of two clips into one Short (e.g. a 0-to-death opener + a close-out) |
| Dankify | `/dankify` | Audio compression/processing for a punchier sound |
| Montage | `/montage` | Assembles multiple vertical clips into one Short with transitions, top text, logo overlay |
| Montage (Original) | `/montage-original` | Same as Montage but sourced from 16:9 original clips |
| Fade to Text | `/fadetotext` | Standalone fade-to-text transition effect on a clip |
| Hype Reel | `/hype-reel` | Multi-clip compilation reel with title text, logo, and outro music, built from original clips |
| Beat Sync | `/beat-sync` | Syncs a clip's hit moments to a music track's beat times, with configurable effects |
| Archive | `/archive` | Browse and run the permanent curated archive (see below) |

Supporting routes: `/browse`, `/browse-image` (file pickers), `/clips-list`, `/review-state/<session>`, `/generate-thumbs/<session>` (auto-generates review thumbnails), `/manual-clip`, `/clips-serve/<file>`, `/open-folder`, `/copy-clip`, `/outro-music`, `/sessions-with-originals`, `/original-clips/<session>`, `/hype-reels-serve/<file>`.

---

## Vertical Clip Format
- **Canvas:** 9:16 (e.g. 606x1080 for 1080p source)
- **Background:** source frame scaled to fill canvas + heavy boxblur
- **Foreground:** source frame scaled to fit canvas width, sharp, centered vertically
- **Result:** blurred background fills top/bottom bars, gameplay is crisp in center
- This matches the aesthetic of successful FGC Shorts channels

---

## Flash Detection — How It Works
Smash Ultimate gives two usable signals per KO:

1. **White victory flash** — a full-screen white flash on the victory screen, ~6 seconds after the actual KO. Lasts ~0.73–0.80s, consistent enough to filter reliably (character-select flashes are ~0.07s and get rejected by `MIN_FLASH_DURATION_SEC`).
2. **Red hit-flash** — a brief red/orange flash at the moment of the finishing hit itself, well before the victory screen. Useful because it locates the actual KO moment directly instead of working backward from the victory screen.

The detector scans brightness/color per frame (every `FRAME_SKIP`-th frame, resized to `SCAN_RESIZE_W` for speed), tracks a rolling baseline, and flags sustained spikes above threshold for each signal independently. A red event and a white event within `RED_MERGE_WINDOW_SEC` of each other are treated as the same KO. This dual-signal approach is more robust than the original white-flash-only detector.

---

## Current State (as of this session — 2026-08)
- ✅ VOD downloading works (YouTube + Twitch via yt-dlp)
- ✅ Dual-signal (white + red flash) KO detection, with caching
- ✅ Clip cutting (two separate sequential FFmpeg calls per clip — vertical + original)
- ✅ Vertical 9:16 blurred background effect
- ✅ Flask web UI at localhost:5000, full review flow (flag/skip/filter, thumbnails, manual clip add)
- ✅ Hook text rendering → finals
- ✅ Full post-production suite shipped: Hook+Slo-Mo, Replay, Stitch, Dankify, Montage, Montage (Original), Fade to Text, Hype Reel, Beat Sync
- ✅ Auto thumbnail generation (`/generate-thumbs`)
- ✅ Archive system — monthly curated export grouped by venue, including a per-venue **restore** function to pull archived material back into `clips/`
- ⚠️ yt-dlp shows JS runtime warning (non-blocking, cosmetic only)
- ❌ **Batch processing** — `BATCH_PROCESSING.md` is a design brief only. No `/run-batch` route or batch pipeline exists in `server.py`. One VOD at a time currently.
- ❌ **YouTube upload from the UI** — `YOUTUBE_UPLOAD.md` is a design brief only. No `youtube_auth.py`, `youtube_upload.py`, or `/upload-youtube` route exist. Uploads are still manual via YouTube Studio.

---

## Known Issues / Gotchas
- **Dual FFmpeg output hangs** — running two outputs in a single FFmpeg call causes it to freeze. Always use two separate sequential FFmpeg calls instead. This applies throughout `renderer.py`, not just the core pipeline.
- **Fast seek artifacts** — `-ss` before `-i` is fast but can cause slight timestamp drift. Current approach uses `-ss` before `-i` with re-encoding, which works fine in practice.
- **Stream layout variance** — some VODs have webcam overlays baked in. The vertical crop shows the full frame (including webcams) scaled down, which is acceptable for now.
- **Cache with 0 events** — if a scan returns 0 events it still saves a cache. On re-run it detects the empty cache and re-scans.
- **`main.py` is dead code** — untouched PyCharm "Hello World" boilerplate, not wired into the app at all.

---

## Phase Roadmap

### Phase 1 — COMPLETE ✅
Core pipeline: download → detect → cut → output vertical Shorts

### Phase 2 — COMPLETE ✅
Clip review UI, hook text rendering, and the full post-production tool suite (montage, montage-original, replay, hook-slowmo, stitch, dankify, fadetotext, hype reel, beat sync), plus auto-thumbnails and the archive system with venue-based restore.

### Phase 3 — PLANNED (specs written, not built)
- **Batch processing** — submit up to 5 VOD URLs, process sequentially. Full implementation brief in `BATCH_PROCESSING.md`.
- **YouTube upload from the UI** — upload a final clip directly with scheduled release + auto-pinned comment. Full implementation brief in `YOUTUBE_UPLOAD.md`, including one-time Google Cloud OAuth setup steps.
- Timed captions, zoom punch effects beyond what Hook+Slo-Mo already offers, sound effects, intro/outro branding — no design docs yet, ideas only.

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
- Always run FFmpeg as two separate calls (e.g. vertical + original) — never combined
- `detector.py` is backend-only (download, detect, cut) — no UI code in it
- `renderer.py` holds every FFmpeg-based render function for the post-production tools — no route/UI code in it
- `server.py` is the production path (Flask); `app.py` is legacy Tkinter kept for reference; `main.py` is an unused stub
- Python virtual environment is at `.venv/`
- FFmpeg is at `C:\ffmpeg-master-latest-win64-gpl-shared\bin`
- Node.js v24.15.0 is installed
- Developer is a Java dev comfortable with Python, using PyCharm + Git Bash
- `BATCH_PROCESSING.md` and `YOUTUBE_UPLOAD.md` are forward-looking implementation briefs, not documentation of existing behavior — don't assume their routes/files exist without checking `server.py` first
