from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import json
import os
import re
import shutil
import threading
import queue
import subprocess
import yt_dlp
from detector import detect_ko_events, cut_clips
from renderer import render_with_text

app = Flask(__name__)
log_queue = queue.Queue()


def log(msg):
    print(msg)
    log_queue.put(msg)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file"}), 400
    os.makedirs("downloads", exist_ok=True)
    safe_name = os.path.basename(f.filename)
    dest = os.path.join(os.path.abspath("downloads"), safe_name)
    f.save(dest)
    return jsonify({"path": dest})


@app.route("/browse")
def browse():
    ps = (
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$d = New-Object System.Windows.Forms.OpenFileDialog; '
        '$d.Filter = "Video Files|*.mp4;*.mkv;*.avi;*.mov|All Files|*.*"; '
        '$d.Title = "Select VOD"; '
        'if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $d.FileName }'
    )
    try:
        r = subprocess.run(['powershell', '-STA', '-Command', ps],
                           capture_output=True, timeout=60, encoding='utf-8')
        path = r.stdout.strip()
        return jsonify({'path': path or None})
    except Exception as e:
        return jsonify({'path': None, 'error': str(e)})


@app.route("/clips-list")
def clips_list():
    root = os.path.abspath('clips')
    sessions = []
    if not os.path.exists(root):
        return jsonify({'sessions': []})
    for name in sorted(os.listdir(root), reverse=True):
        session_path = os.path.join(root, name)
        if not os.path.isdir(session_path):
            continue
        if name == 'archived':
            continue
        vert_dir   = os.path.join(session_path, 'vertical')
        orig_dir   = os.path.join(session_path, 'original')
        finals_dir = os.path.join(session_path, 'finals')

        # Load persisted review states
        review_path = os.path.join(session_path, 'review.json')
        review_states = {}
        if os.path.exists(review_path):
            try:
                with open(review_path) as f:
                    review_states = json.load(f)
            except Exception:
                pass

        clips = []
        if os.path.exists(vert_dir):
            for f in sorted(os.listdir(vert_dir), key=_clip_num):
                if not f.endswith('.mp4'):
                    continue
                base    = f.replace('_vertical.mp4', '')
                orig_f  = base + '_original.mp4'
                final_f = base + '_final.mp4'
                has_final = os.path.exists(os.path.join(finals_dir, final_f)) if os.path.exists(finals_dir) else False
                state   = 'done' if has_final else review_states.get(base, 'default')
                clips.append({
                    'name':     base,
                    'vertical': f'{name}/vertical/{f}',
                    'original': f'{name}/original/{orig_f}' if os.path.exists(os.path.join(orig_dir, orig_f)) else None,
                    'state':    state,
                })

        finals = []
        if os.path.exists(finals_dir):
            for f in sorted(os.listdir(finals_dir), key=_clip_num):
                if f.endswith('.mp4'):
                    finals.append(f'{name}/finals/{f}')

        if clips or finals:
            sessions.append({'title': name, 'clips': clips, 'finals': finals})

    archived = []
    archived_root = os.path.join(root, 'archived')
    if os.path.exists(archived_root):
        for name in sorted(os.listdir(archived_root), reverse=True):
            if os.path.isdir(os.path.join(archived_root, name)):
                archived.append(name)

    return jsonify({'sessions': sessions, 'archived': archived})


@app.route("/review-state/<path:session>", methods=["POST"])
def set_review_state(session):
    data      = request.get_json()
    clip_name = data.get("clip", "").strip()
    state     = data.get("state", "default")

    if not clip_name:
        return jsonify({"error": "No clip specified"}), 400

    clips_root  = os.path.abspath("clips")
    review_path = os.path.join(clips_root, session, "review.json")

    states = {}
    if os.path.exists(review_path):
        try:
            with open(review_path) as f:
                states = json.load(f)
        except Exception:
            pass

    if state == "default":
        states.pop(clip_name, None)
    else:
        states[clip_name] = state

    with open(review_path, "w") as f:
        json.dump(states, f, indent=2)

    return jsonify({"ok": True})


@app.route("/unarchive/<path:session>", methods=["POST"])
def unarchive_session(session):
    clips_root = os.path.abspath("clips")
    src = os.path.join(clips_root, "archived", session)
    if not os.path.exists(src):
        return jsonify({"error": "Session not found"}), 404
    shutil.move(src, os.path.join(clips_root, session))
    return jsonify({"ok": True})


@app.route("/archive/<path:session>", methods=["POST"])
def archive_session(session):
    clips_root = os.path.abspath("clips")
    src = os.path.join(clips_root, session)
    if not os.path.exists(src):
        return jsonify({"error": "Session not found"}), 404
    dest_dir = os.path.join(clips_root, "archived")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.move(src, os.path.join(dest_dir, session))
    return jsonify({"ok": True})


@app.route("/render-text", methods=["POST"])
def render_text_route():
    data = request.get_json()
    clip_rel  = data.get("clip", "").strip()
    above     = data.get("above", "").strip()
    below     = data.get("below", "").strip()

    if not clip_rel:
        return jsonify({"error": "No clip specified"}), 400

    clips_root = os.path.abspath("clips")
    clip_path  = os.path.join(clips_root, clip_rel.replace("/", os.sep))
    if not os.path.exists(clip_path):
        return jsonify({"error": "Clip not found"}), 404

    parts      = clip_rel.replace("\\", "/").split("/")
    session    = parts[0]
    orig_name  = parts[-1]
    final_name = orig_name.replace("_vertical.mp4", "_final.mp4")
    if final_name == orig_name:
        final_name = os.path.splitext(orig_name)[0] + "_final.mp4"

    finals_dir  = os.path.join(clips_root, session, "finals")
    output_path = os.path.join(finals_dir, final_name)
    output_rel  = f"{session}/finals/{final_name}"

    logs = []
    def capture(msg):
        logs.append(msg)
        print(msg)

    ok = render_with_text(clip_path, above, below, output_path, log_fn=capture)

    if ok:
        return jsonify({"ok": True, "path": output_rel, "logs": logs})
    return jsonify({"ok": False, "logs": logs}), 500


@app.route("/clips-serve/<path:filename>")
def serve_clip(filename):
    return send_from_directory(os.path.abspath('clips'), filename)


@app.route("/run", methods=["POST"])
def run():
    data = request.get_json()
    url = data.get("url", "").strip()
    local_path = data.get("path", "").strip()
    if not url and not local_path:
        return jsonify({"error": "No URL or path provided"}), 400
    threading.Thread(target=run_pipeline, args=(url, local_path), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/logs")
def logs():
    def stream():
        while True:
            try:
                msg = log_queue.get(timeout=30)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield "data: __keepalive__\n\n"
    return Response(stream(), mimetype="text/event-stream")


def run_pipeline(url, local_path=''):
    try:
        if local_path:
            if not os.path.exists(local_path):
                log(f"❌  File not found: {local_path}")
                log("__done__")
                return
            video_path = local_path
            video_title = os.path.splitext(os.path.basename(local_path))[0]
            log(f"📂  Local file: {video_title}")
        else:
            os.makedirs("downloads", exist_ok=True)
            log("🔎  Fetching video info...")
            video_title, expected_filename = get_video_info(url)
            if not video_title:
                log("❌  Could not fetch video info.")
                log("__done__")
                return
            log(f"📺  Title: {video_title}")
            cached_path = os.path.join("downloads", expected_filename)
            if os.path.exists(cached_path):
                log("✅  Already downloaded — skipping re-download.")
                video_path = cached_path
            else:
                log("📥  Downloading VOD...")
                video_path = download_vod(url)
                if not video_path:
                    log("❌  Download failed.")
                    log("__done__")
                    return

        log("\n🔍  Scanning for KO flashes...")
        events = detect_ko_events(video_path, log_fn=log)

        if not events:
            log("⚠️  No KO events detected.")
            log("__done__")
            return

        safe_title = safe_folder_name(video_title)
        clips_dir = os.path.join("clips", safe_title)
        cut_clips(video_path, events, output_dir=clips_dir, log_fn=log)

        log(f"\n✅  Done! Clips saved to: {os.path.abspath(clips_dir)}")
        log(f"__done__:{safe_title}")

    except Exception as e:
        log(f"\n❌  Error: {e}")
        log("__done__")


def get_video_info(url):
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            safe = ydl.prepare_filename(info).replace('\\', '/').split('/')[-1]
            if not safe.endswith('.mp4'):
                safe = os.path.splitext(safe)[0] + '.mp4'
            return title, safe
    except Exception as e:
        log(f"⚠️  Could not fetch info: {e}")
        return None, None


def download_vod(url):
    class YTLogger:
        def debug(self, msg):
            if msg.startswith('[download]'):
                log(msg)
        def info(self, msg):
            log(msg)
        def warning(self, msg):
            log(f"⚠️  {msg}")
        def error(self, msg):
            log(f"❌  {msg}")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'logger': YTLogger(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace('\\', '/').split('/')[-1]
        if not filename.endswith('.mp4'):
            filename = os.path.splitext(filename)[0] + '.mp4'

    video_path = os.path.join("downloads", filename)
    if os.path.exists(video_path):
        return video_path
    downloads = os.listdir("downloads")
    if downloads:
        return os.path.join("downloads", downloads[0])
    return None


def _clip_num(filename):
    m = re.search(r'clip_(\d+)_', filename)
    return int(m.group(1)) if m else 0


def safe_folder_name(title):
    invalid = r'\/:*?"<>|'
    cleaned = ''.join(c for c in title if c not in invalid).strip()[:80]
    return cleaned.rstrip('. ')


if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    app.run(debug=True, port=5000, threaded=True)
