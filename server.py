from flask import Flask, request, jsonify, render_template, Response
import os
import threading
import queue
import yt_dlp
from detector import detect_ko_events, cut_clips

app = Flask(__name__)

# Global log queue for streaming logs to the browser
log_queue = queue.Queue()


def log(msg):
    print(msg)
    log_queue.put(msg)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # Run pipeline in background thread
    thread = threading.Thread(target=run_pipeline, args=(url,), daemon=True)
    thread.start()

    return jsonify({"status": "started"})


@app.route("/logs")
def logs():
    """Server-Sent Events endpoint — streams log lines to the browser in real time."""
    def stream():
        while True:
            try:
                msg = log_queue.get(timeout=30)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield "data: __keepalive__\n\n"
    return Response(stream(), mimetype="text/event-stream")


def run_pipeline(url):
    try:
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
        events = detect_ko_events(video_path)

        if not events:
            log("⚠️  No KO events detected.")
            log("__done__")
            return

        safe_title = safe_folder_name(video_title)
        clips_dir = os.path.join("clips", safe_title)
        log(f"\n✂️  Cutting {len(events)} clip(s)...")
        cut_clips(video_path, events, output_dir=clips_dir)

        log(f"\n✅  Done! Clips saved to: {os.path.abspath(clips_dir)}")
        log("__done__")

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


def safe_folder_name(title):
    invalid = r'\/:*?"<>|'
    safe = ''.join(c for c in title if c not in invalid)
    return safe.strip()[:80]


if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    app.run(debug=True, port=5000, threaded=True)
