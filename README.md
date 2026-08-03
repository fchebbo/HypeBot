<div align="center">
  <img src="static/favicon.png" width="120" alt="HypeBot"/>

  # HYPEBOT
  ### Turns VODs into content clip gold.

  ![Python](https://img.shields.io/badge/Python-3.13-blue?style=flat-square&logo=python&logoColor=white)
  ![Flask](https://img.shields.io/badge/Flask-web%20UI-black?style=flat-square&logo=flask)
  ![FFmpeg](https://img.shields.io/badge/FFmpeg-video%20engine-green?style=flat-square&logo=ffmpeg)
  ![Smash Ultimate](https://img.shields.io/badge/Smash-Ultimate-red?style=flat-square)

  **[GitHub](https://github.com/fchebbo/HypeBot)** · Powering **[SoCal Smash](https://www.youtube.com/@SoCalSmash)** on YouTube
</div>

---

HypeBot downloads Smash Ultimate tournament VODs from YouTube or Twitch, automatically detects KO moments using flash detection, and cuts polished 9:16 vertical clips ready for YouTube Shorts, TikTok, or Instagram Reels. From there, a full post-production suite — hook text, slow-motion replays, montages, stitched clips, audio punch-up, beat-synced edits, compilation reels, and a permanent archive — takes clips the rest of the way to upload-ready.

---

## Quickstart

**No programming experience needed. Follow these steps top to bottom — about 20 minutes the first time, then 10 seconds every time after.**

---

### 1. Install Git &nbsp;*(~2 min)*
Git is the tool that downloads the HypeBot code from the internet.

1. Go to **[git-scm.com/download/win](https://git-scm.com/download/win)** and download the installer
2. Run it — click **Next** through every screen, all defaults are fine

---

### 2. Install Python &nbsp;*(~3 min)*
Python is the language HypeBot is written in.

1. Go to **[python.org/downloads](https://www.python.org/downloads/)** and download **Python 3.13**
2. Run the installer
3. ⚠️ **On the first screen, check the box that says "Add Python to PATH"** before clicking anything else. If you skip this, nothing will work.
4. Click **Install Now**

---

### 3. Install FFmpeg &nbsp;*(~7 min)*
FFmpeg is the video engine HypeBot uses to cut and encode clips. You'll never open it directly — it runs silently in the background.

1. Go to **[ffmpeg.org/download.html](https://ffmpeg.org/download.html)**, click the Windows logo, then click **Windows builds from gyan.dev**
2. Download **ffmpeg-release-essentials.zip**
3. Extract the zip — you'll get a folder with a long name like `ffmpeg-7.x-essentials_build`
4. Rename that folder to `ffmpeg` and move it to `C:\ffmpeg`
5. Now tell Windows where to find it:
   - Press the **Windows key**, search for **"Edit the system environment variables"**, and open it
   - Click **Environment Variables** (bottom right of the window)
   - Under **System variables**, click **Path**, then click **Edit**
   - Click **New** and type exactly: `C:\ffmpeg\bin`
   - Click **OK** on all three open dialogs
6. To confirm it worked: open a new **Command Prompt** (search "cmd" in the Start menu), type `ffmpeg -version`, and press Enter. If you see version information, you're good.

---

### 4. Download HypeBot &nbsp;*(~1 min)*

1. Open **Command Prompt** (search "cmd" in the Start menu)
2. Choose where HypeBot will live — your Desktop is fine. Type the following, replacing `YourName` with your actual Windows username:
   ```
   cd C:\Users\YourName\Desktop
   ```
3. Download HypeBot:
   ```
   git clone https://github.com/fchebbo/HypeBot.git
   ```
4. A folder called `HypeBot` now exists on your Desktop

---

### 5. First-time setup &nbsp;*(~4 min)*
**You only do this once.**

1. In Command Prompt, move into the HypeBot folder:
   ```
   cd HypeBot
   ```
2. Create a virtual environment (an isolated Python sandbox just for HypeBot):
   ```
   python -m venv .venv
   ```
3. Activate it:
   ```
   .venv\Scripts\activate
   ```
   You'll see `(.venv)` appear at the start of the line — that means it's active.
4. Install HypeBot's dependencies:
   ```
   pip install -r requirements.txt
   ```
   A lot of text will scroll by. Wait for it to finish — it takes a minute or two.

---

### 6. Run HypeBot

**Every time you want to use HypeBot:**

1. Open **Command Prompt**
2. Run these two lines (replace `YourName` with your Windows username):
   ```
   cd C:\Users\YourName\Desktop\HypeBot
   .venv\Scripts\activate
   ```
3. Start it:
   ```
   python server.py
   ```
4. Open your browser and go to **[http://localhost:5000](http://localhost:5000)**

HypeBot is running. To stop it when you're done, click into the Command Prompt window and press **Ctrl + C**.

---

> Steps 1–5 are one-time only. From now on, all you ever need is step 6.

---

## Table of Contents
- [How it works](#how-it-works)
- [Setup — Windows](#setup--windows)
- [Setup — Mac](#setup--mac)
- [Running HypeBot](#running-hypebot)
- [Using HypeBot](#using-hypebot)
  - Generate clips, review, add text, manual clips
  - Hook + Slo-Mo, Montage (+ Original), Slow-motion Replay, Stitch, Dankify
  - Fade to Text, Hype Reel, Beat Sync
  - Archive your library

---

## How it works

1. You paste a YouTube or Twitch VOD URL
2. HypeBot downloads the VOD and scans it frame-by-frame for Smash Ultimate's signature KO flash — both the white victory-screen flash and the red flash that fires at the finishing hit itself, for more reliable timing
3. It cuts a clip around each KO — a 9:16 vertical version (Shorts-ready) and a 16:9 original
4. You review clips in the browser, flag the best ones, add text overlays, and render finals
5. Optionally, run flagged clips through Hook + Slo-Mo, Replay, Stitch, Dankify, Montage, Hype Reel, or Beat Sync to build out more elaborate content
6. Periodically archive your best material into a permanent, curated library

---

## Setup — Windows

Welcome! This guide assumes you're starting from scratch. Take it one step at a time.

### 1. Create a GitHub account
If you don't have one, go to [github.com](https://github.com) and sign up. You'll need this to access the code.

### 2. Install Git
Git is the tool that lets you download and manage code from GitHub.

1. Go to [git-scm.com/download/win](https://git-scm.com/download/win)
2. Download and run the installer — the default options are fine
3. Open **Command Prompt** (search for it in the Start menu) and type:
   ```
   git --version
   ```
   You should see a version number. If you do, Git is installed.

### 3. Install Python
Python is the programming language HypeBot is written in.

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download the latest **Python 3.13** release
3. Run the installer — **important:** check the box that says **"Add Python to PATH"** before clicking Install
4. Verify it worked by opening Command Prompt and typing:
   ```
   python --version
   ```
   You should see `Python 3.13.x`.

### 4. Install PyCharm
PyCharm is a code editor built for Python. The free Community Edition is all you need.

1. Go to [jetbrains.com/pycharm/download](https://www.jetbrains.com/pycharm/download/)
2. Download **PyCharm Community Edition** and install it

### 5. Clone the repository
"Cloning" means downloading a local copy of the code from GitHub.

1. Open Command Prompt and navigate to wherever you want the project to live, e.g.:
   ```
   cd C:\Users\YourName\Projects
   ```
2. Clone the repo:
   ```
   git clone https://github.com/fchebbo/HypeBot.git
   ```
3. This creates a `HypeBot` folder. Open PyCharm, choose **Open**, and select that folder.

### 6. Set up a virtual environment
A virtual environment is an isolated Python installation just for this project. This keeps HypeBot's dependencies separate from anything else on your machine.

In PyCharm:
1. Go to **File → Settings → Project: HypeBot → Python Interpreter**
2. Click the gear icon → **Add Interpreter → Add Local Interpreter**
3. Choose **Virtualenv Environment**, leave the defaults, and click **OK**
4. PyCharm will create a `.venv` folder inside the project — this is the virtual environment

### 7. Install Python dependencies
Dependencies are the third-party libraries HypeBot relies on (Flask for the web server, OpenCV for video analysis, etc.). The `requirements.txt` file lists them all.

In PyCharm, open the **Terminal** tab at the bottom and run:
```
pip install -r requirements.txt
```
This will install everything HypeBot needs. It may take a minute.

### 8. Install FFmpeg
FFmpeg is the tool that actually cuts and encodes the video clips. It runs behind the scenes every time HypeBot creates a clip.

1. Go to [ffmpeg.org/download.html](https://ffmpeg.org/download.html) → click the Windows logo → **Windows builds from gyan.dev**
2. Download the latest **ffmpeg-release-full.7z** (or the `.zip` version if you don't have 7-Zip)
3. Extract it — you'll get a folder like `ffmpeg-7.x-full_build`
4. Move that folder somewhere permanent, e.g. `C:\ffmpeg`
5. Add FFmpeg to your PATH so HypeBot can find it:
   - Search for **"Environment Variables"** in the Start menu
   - Click **Environment Variables**
   - Under **System variables**, select **Path** and click **Edit**
   - Click **New** and add the path to FFmpeg's `bin` folder, e.g. `C:\ffmpeg\bin`
   - Click OK on all dialogs
6. Open a **new** Command Prompt and verify:
   ```
   ffmpeg -version
   ```
   You should see version info. If you do, you're good.

---

## Setup — Mac

### 1. Create a GitHub account
If you don't have one, go to [github.com](https://github.com) and sign up.

### 2. Install Homebrew
Homebrew is a package manager for Mac — it makes installing developer tools much easier.

Open **Terminal** (find it in Applications → Utilities) and run:
```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Follow the prompts. This may take a few minutes.

### 3. Install Git
Git likely came pre-installed on your Mac, but the Homebrew version is more up-to-date:
```
brew install git
```
Verify:
```
git --version
```

### 4. Install Python
```
brew install python@3.13
```
Verify:
```
python3 --version
```

### 5. Install PyCharm
1. Go to [jetbrains.com/pycharm/download](https://www.jetbrains.com/pycharm/download/)
2. Download **PyCharm Community Edition** for Mac and install it

### 6. Clone the repository
In Terminal, navigate to where you want the project:
```
cd ~/Projects
```
Then clone:
```
git clone https://github.com/fchebbo/HypeBot.git
```
Open PyCharm, choose **Open**, and select the `HypeBot` folder.

### 7. Set up a virtual environment
In PyCharm:
1. Go to **PyCharm → Settings → Project: HypeBot → Python Interpreter**
2. Click the gear icon → **Add Interpreter → Add Local Interpreter**
3. Choose **Virtualenv Environment**, leave the defaults, click **OK**

### 8. Install Python dependencies
In the PyCharm **Terminal** tab:
```
pip3 install -r requirements.txt
```

### 9. Install FFmpeg
FFmpeg handles all the video cutting and encoding.
```
brew install ffmpeg
```
Verify:
```
ffmpeg -version
```

---

## Running HypeBot

Once setup is complete, starting HypeBot is simple.

In the PyCharm Terminal (make sure your virtual environment is active — you'll see `(.venv)` at the start of the prompt):

```
python server.py
```

You should see:
```
* Running on http://127.0.0.1:5000
```

Open your browser and go to:
```
http://localhost:5000
```

HypeBot is running.

---

## Using HypeBot

### Generate clips from a VOD

1. On the main screen, make sure the **URL** tab is selected
2. Paste a YouTube or Twitch VOD URL into the input field and click **GENERATE**

   > Try this Twitch VOD to test: `https://www.twitch.tv/videos/2684133482`

3. The log panel will show progress — downloading, scanning for KOs, cutting clips
4. When it finishes, the review section will appear automatically

### Review your clips

Each clip gets its own card showing the vertical 9:16 preview. You can:

- **VERT / 16:9** — toggle between the vertical Short and the original widescreen cut
- **⭐ Flag** — mark clips you want to use
- **✕ Skip** — mark clips you want to ignore
- **Filter bar** — quickly show only Flagged, Unreviewed, or Skipped clips

### Add text and render a final

1. Click **ADD TEXT** on any clip
2. Type your hook line in the **ABOVE** or **BELOW** field (or both)
3. Optionally enable **KO Hook** to stitch a short replay of the finish before the full clip, with a transition effect between them
4. Use **Extend clip** or **Cut end** to trim the clip length
5. Click **RENDER** — HypeBot burns the text onto the clip and saves it as a final
6. Finals appear at the bottom of the page under their own section, ready to download and upload

### Add clips manually

If a VOD had no detected KO events, or you want to cut a specific moment that wasn't caught automatically:

1. Select the session from the dropdown
2. Scroll to **Add clip manually** at the bottom of the review panel
3. Enter a **Start** and **End** timestamp (format: `1:23:45`)
4. Click **CUT** — HypeBot cuts both a vertical and original version as normal

> If the VOD had 0 detected clips it will still appear in the session list as long as it was processed by HypeBot.

### Hook + Slo-Mo

A quicker single-clip tool for burning above-text onto a clip with a slow-motion window on the key moment.

1. Go to `http://localhost:5000/hook-slowmo`
2. Select a clip — a preview player appears
3. Set the slow-motion window (start/end) and speed, and optionally enable **Zoom**
4. Add above-text (one or two lines) and pick a transition
5. Click **RENDER** — saved to `clips/[session]/finals/` as `..._hookslomo.mp4`

### Create a montage

The montage tool assembles multiple clips into a single Short with transitions between them.

1. Go to `http://localhost:5000/montage`
2. Select a session and add clips to the timeline using **+ ADD CLIP**
3. Set a global transition or override it per clip
4. Add optional top text and a logo overlay
5. Click **RENDER MONTAGE** — when done, the result plays inline
6. Saved to `clips/[session]/montage/`

> **Montage (Original)** — `http://localhost:5000/montage-original` is the same tool, but built from 16:9 original clips instead of vertical ones. Useful for regular (non-Shorts) YouTube uploads.

### Create a slow-motion replay

The replay tool takes a single clip and produces a "Did You Catch It?" Short — the clip plays once at full speed, then plays again with a slow-motion zoom on the key moment.

1. Go to `http://localhost:5000/replay`
2. Select the session and clip from the dropdowns — a preview player appears so you can watch first
3. Optionally check **Use KO hook only** to trim the clip to just the last few seconds
4. Set **Moment start** — how many seconds into the clip the key moment happens (this is where the slowmo begins)
5. Tune **Slowmo duration**, **Speed**, **Zoom**, and **Crossfade** to taste
6. Set the **top text** shown during the first play (e.g. "DID YOU CATCH IT?") and optionally different text for the replay
7. Click **RENDER REPLAY** — when done, the result plays inline
8. Saved to `clips/[session]/replay/`

### Stitch two clips together

The stitch tool combines the KO hook from two clips into a single Short — great for telling a full game story (e.g. a 0-to-death opener followed by the close-out).

1. Go to `http://localhost:5000/stitch`
2. Select the session both clips belong to
3. Pick **Clip 1** and **Clip 2** from the dropdowns — a preview player appears for each
4. Set the **hook offset** for each clip (how many seconds from the end to include)
5. Customize the **transition text** (defaults to "Later...")
6. Add **above/below text** for each clip independently
7. Click **RENDER STITCH** — when done, the result plays inline
8. Saved to `clips/[session]/stitch/`

### Dankify a clip

Dankify applies audio compression and processing to a clip for a punchier, more impactful sound.

1. Go to `http://localhost:5000/dankify`
2. Select the session and clip, set the hook start point
3. Click **DANKIFY** — saved to `clips/[session]/dankify/`

### Fade to Text

A standalone tool for applying a fade-to-text transition effect on a clip.

1. Go to `http://localhost:5000/fadetotext`
2. Select the session and clip, set the timing and the text
3. Click **RENDER** — saved as a final in `clips/[session]/finals/`

### Build a Hype Reel

A larger compilation format — strings several clips together with a title card, logo, and outro music, built from the 16:9 original clips.

1. Go to `http://localhost:5000/hype-reel`
2. Select a session with original clips, then add 2 or more clips to the reel
3. Set the title text, hook offset and transition per clip, and pick a logo and outro music track (from `Props/`)
4. Click **RENDER HYPE REEL** — when done, the result plays inline
5. Saved to `clips/[session]/hype_reels/`

### Beat Sync

Syncs a clip's KO hit moments to the beat of a music track, with a configurable visual effect on each beat.

1. Go to `http://localhost:5000/beat-sync`
2. Select the session, clip, and audio track
3. Enter the hit times (from the clip) and beat times (from the track), pick an effect and timing offsets
4. Click **RENDER** — the result plays inline when done

### Archive your library

The archive is a permanent, curated export of your best clips — the source of truth for upload-ready content. Run it monthly to consolidate everything worth keeping before clearing out `clips/` and `downloads/`.

**What gets archived:**
- Vertical clips that are flagged or have a rendered final
- Their 16:9 originals
- All finals, montages, replays, dankify, and stitch outputs

**How to run it:**

1. Go to `http://localhost:5000/archive`
2. Click **RUN ARCHIVE** — a preview shows exactly what will be copied and the estimated size
3. Confirm — files are copied (never moved) to `archive/YYYY-MM/`
4. Browse the result: clips are grouped by venue, thumbnails load as you scroll
5. Once you're satisfied, manually delete `clips/` and `downloads/` to reclaim disk space

If you need something back out of the archive, use **restore by venue** on the archive page — it copies a venue's clips, finals, montages, dankify, replay, and stitch outputs from the selected month back into `clips/`.

The archive page supports lazy-loaded thumbnails, click-to-play, collapsible venue sections, and one-click copy of the VOD source URL.
