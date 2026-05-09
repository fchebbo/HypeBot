# YouTube Upload Feature — Implementation Brief

## Note to developer

You have been granted full Manager access to the SoCal Smash YouTube channel and Google Cloud project. This means you are responsible for the full setup end-to-end — Google Cloud project creation, enabling the API, OAuth credentials, and wiring it into the app. You do not need to loop in the channel owner for any of the setup steps.

---

## What this feature does

After a clip is rendered as a final in HypeBot, the user should be able to fill in a title, description, and scheduled release time — then hit **Upload to YouTube** directly from the browser UI. No manual YouTube Studio needed.

---

## How it fits into the existing app

HypeBot is a Flask web app (`server.py`) with a browser UI (`templates/index.html`). Clips are rendered via the **Render** button on each clip card and saved to `clips/[session]/finals/`. The upload button will live on each final clip card, appearing after a final has been rendered.

---

## Tech stack for this feature

- **YouTube Data API v3** — Google's official API for uploading videos and setting metadata
- **Google OAuth 2.0** — required to authenticate as the channel owner
- **`google-api-python-client`** — official Python client library
- **`google-auth-oauthlib`** — handles the OAuth flow

Install via:
```
pip install google-api-python-client google-auth-oauthlib
```

Add both to `requirements.txt`.

---

## One-time Google Cloud setup (you do this, not the code)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "HypeBot")
3. Enable the **YouTube Data API v3**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop App**
6. Download the credentials JSON — save it as `client_secrets.json` in the project root
7. Add `client_secrets.json` to `.gitignore` — never commit this file

---

## Authentication flow

The first time a user uploads, HypeBot opens a browser window for Google OAuth consent. After the user approves, Google returns a token that gets saved locally to `token.json`. All future uploads reuse this token silently (it auto-refreshes).

Create a new file `youtube_auth.py`:

```python
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
CLIENT_SECRETS = 'client_secrets.json'
TOKEN_FILE = 'token.json'


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return creds
```

---

## Upload logic

Create a new file `youtube_upload.py`:

```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from youtube_auth import get_credentials


def upload_video(file_path, title, description, scheduled_time=None, log_fn=print):
    """
    Upload a video to YouTube.

    scheduled_time: ISO 8601 string e.g. '2026-05-10T18:00:00Z'
                    If None, video uploads as private with no schedule.
    Returns the YouTube video ID on success, None on failure.
    """
    try:
        creds = get_credentials()
        youtube = build('youtube', 'v3', credentials=creds)

        status = {
            'privacyStatus': 'private',
            'selfDeclaredMadeForKids': False,
        }
        if scheduled_time:
            status['privacyStatus'] = 'private'
            status['publishAt'] = scheduled_time

        body = {
            'snippet': {
                'title': title,
                'description': description,
                'categoryId': '20',  # Gaming
            },
            'status': status,
        }

        media = MediaFileUpload(file_path, mimetype='video/mp4', resumable=True)

        log_fn(f"📤  Uploading to YouTube: {title}")
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status_update, response = request.next_chunk()
            if status_update:
                pct = int(status_update.progress() * 100)
                log_fn(f"  📊  Upload progress: {pct}%")

        video_id = response['id']
        log_fn(f"✅  Uploaded: https://youtube.com/shorts/{video_id}")
        return video_id

    except Exception as e:
        log_fn(f"❌  Upload failed: {e}")
        return None
```

---

## New Flask route in server.py

Add this route to `server.py`:

```python
from youtube_upload import upload_video

@app.route("/upload-youtube", methods=["POST"])
def upload_youtube():
    data         = request.get_json()
    clip_rel     = data.get("clip", "").strip()       # e.g. "SessionName/finals/clip_1_final.mp4"
    title        = data.get("title", "").strip()
    description  = data.get("description", "").strip()
    scheduled_at = data.get("scheduled_at", None)     # ISO 8601 string or null

    if not clip_rel or not title:
        return jsonify({"error": "clip and title are required"}), 400

    clips_root = os.path.abspath("clips")
    file_path  = os.path.join(clips_root, clip_rel.replace("/", os.sep))
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    def do_upload():
        video_id = upload_video(file_path, title, description, scheduled_at, log_fn=log)
        if video_id:
            log(f"__youtube_uploaded__:{clip_rel}:{video_id}")
        else:
            log("__youtube_upload_failed__")

    threading.Thread(target=do_upload, daemon=True).start()
    return jsonify({"status": "started"})
```

---

## UI changes in index.html

On each **final** clip card, add an **Upload** button that opens a small inline form:

```
[ Title input                    ]
[ Description textarea           ]
[ Schedule date/time picker      ]
[ UPLOAD TO YOUTUBE ]
```

The form POSTs to `/upload-youtube`. Progress is streamed back via the existing `/logs` SSE endpoint (same as clip generation). When `__youtube_uploaded__` appears in the log, mark the clip card with a "Uploaded ✓" badge and store the video ID.

The date/time picker should default to **tomorrow at a sensible time** (e.g. noon) so the user doesn't have to think about it.

---

## Files to create

| File | Purpose |
|------|---------|
| `youtube_auth.py` | OAuth credential management |
| `youtube_upload.py` | Upload logic |
| `client_secrets.json` | Google OAuth credentials (user provides, never commit) |
| `token.json` | Auto-generated after first auth (never commit) |

## Files to modify

| File | Change |
|------|--------|
| `server.py` | Add `/upload-youtube` route |
| `templates/index.html` | Add upload form + button to final clip cards |
| `requirements.txt` | Add `google-api-python-client` and `google-auth-oauthlib` |
| `.gitignore` | Add `client_secrets.json` and `token.json` |

---

## Things to watch out for

- **`client_secrets.json` must never be committed to git** — add to `.gitignore` immediately
- **First run requires a browser window** for OAuth consent — this only happens once, token is saved after
- **Quota limits** — YouTube API has a daily upload quota. At 1 video/day this is nowhere near the limit, but worth knowing
- **`publishAt` requires the video to be `private`** — the API will reject `public` + `publishAt` combined
- **Resumable upload** — the `MediaFileUpload(resumable=True)` handles large files gracefully, don't remove it
- **`categoryId: '20'`** is Gaming — correct for this use case
