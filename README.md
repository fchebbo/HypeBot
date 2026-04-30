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

HypeBot downloads Smash Ultimate tournament VODs from YouTube or Twitch, automatically detects KO moments using flash detection, and cuts polished 9:16 vertical clips ready for YouTube Shorts, TikTok, or Instagram Reels.

---

## Table of Contents
- [How it works](#how-it-works)
- [Setup — Windows](#setup--windows)
- [Setup — Mac](#setup--mac)
- [Running HypeBot](#running-hypebot)
- [Using HypeBot](#using-hypebot)

---

## How it works

1. You paste a YouTube or Twitch VOD URL
2. HypeBot downloads the VOD and scans it frame-by-frame for Smash Ultimate's signature KO flash
3. It cuts a clip around each KO — a 9:16 vertical version (Shorts-ready) and a 16:9 original
4. You review clips in the browser, flag the best ones, add text overlays, and render finals

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
3. Click **RENDER** — HypeBot burns the text onto the clip and saves it as a final
4. Finals appear at the bottom of the page under their own section, ready to download and upload

### Archive a session

When you're done with a VOD and don't need it cluttering the review screen:

1. Select the session tab
2. Click **ARCHIVE** in the top-right of the review section
3. The session moves to `clips/archived/` and disappears from the list

To restore an archived session, click the **ARCHIVED (N)** button that appears above the review section and hit **RESTORE** next to the one you want back.
