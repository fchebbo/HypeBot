from flask import Flask, request, jsonify, render_template, Response, send_from_directory
import json
import os
import re
import shutil
import tempfile
import time
import threading
import queue
import subprocess
import yt_dlp
from detector import detect_ko_events, cut_clips, cut_extended_vertical, cut_manual_clip, get_clip_duration, verify_video_integrity
from renderer import render_with_text, render_stitch, render_replay, render_montage, render_dankify, render_fade_to_text, render_hype_reel, render_beat_sync, render_hook_slowmo

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


@app.route("/browse-image")
def browse_image():
    ps = (
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; '
        'Add-Type -AssemblyName System.Windows.Forms; '
        '$d = New-Object System.Windows.Forms.OpenFileDialog; '
        '$d.Filter = "Image Files|*.png;*.jpg;*.jpeg;*.webp;*.bmp|All Files|*.*"; '
        '$d.Title = "Select Logo / Branding Image"; '
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
    for name in sorted(os.listdir(root)):
        session_path = os.path.join(root, name)
        if not os.path.isdir(session_path):
            continue
        vert_dir   = os.path.join(session_path, 'vertical')
        orig_dir   = os.path.join(session_path, 'original')
        finals_dir = os.path.join(session_path, 'finals')

        # Load session metadata
        meta = {"venue": None, "source": None}
        meta_path = os.path.join(session_path, 'meta.json')
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
            except Exception:
                pass

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
                thumb_f = base + '_thumb.jpg'
                clips.append({
                    'name':     base,
                    'vertical': f'{name}/vertical/{f}',
                    'original': f'{name}/original/{orig_f}' if os.path.exists(os.path.join(orig_dir, orig_f)) else None,
                    'thumb':    f'{name}/vertical/{thumb_f}' if os.path.exists(os.path.join(vert_dir, thumb_f)) else None,
                    'state':    state,
                })

        finals = []
        if os.path.exists(finals_dir):
            for f in sorted(os.listdir(finals_dir), key=_clip_num):
                if f.endswith('.mp4'):
                    finals.append(f'{name}/finals/{f}')

        has_vod = bool(meta.get("vod_path") and os.path.exists(meta.get("vod_path", "")))
        if clips or finals or has_vod:
            sessions.append({'title': name, 'clips': clips, 'finals': finals, 'meta': meta})

    return jsonify({'sessions': sessions})


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



@app.route("/generate-thumbs/<path:session>", methods=["POST"])
def generate_thumbs(session):
    clips_root = os.path.abspath("clips")
    vert_dir = os.path.join(clips_root, session, "vertical")
    if not os.path.exists(vert_dir):
        return jsonify({"error": "Session not found"}), 404

    generated = 0
    for f in os.listdir(vert_dir):
        if not f.endswith("_vertical.mp4"):
            continue
        base = f.replace("_vertical.mp4", "")
        thumb_path = os.path.join(vert_dir, f"{base}_thumb.jpg")
        if os.path.exists(thumb_path):
            continue
        clip_path = os.path.join(vert_dir, f)
        result = subprocess.run([
            "ffmpeg", "-y", "-ss", "5",
            "-i", clip_path,
            "-vframes", "1", "-q:v", "4",
            thumb_path,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if result.returncode == 0:
            generated += 1

    return jsonify({"ok": True, "generated": generated})



@app.route("/render-text", methods=["POST"])
def render_text_route():
    data = request.get_json()
    clip_rel    = data.get("clip", "").strip()
    above       = data.get("above", "").strip()
    below       = data.get("below", "").strip()
    hook            = bool(data.get("hook", False))
    hook_offset     = float(data.get("hook_offset", 2.8))
    hook_transition = data.get("hook_transition", "none").strip()
    hook_only       = bool(data.get("hook_only", False))
    hook_above      = data.get("hook_above", "").strip() or None
    hook_below      = data.get("hook_below", "").strip() or None
    # Main text falls back to hook text when left blank
    if not above and hook_above:
        above = hook_above
    if not below and hook_below:
        below = hook_below
    cut_end_sec     = float(data.get("cut_end_sec", 0.0))
    extend_sec      = float(data.get("extend_sec", 0.0))
    prepend_sec     = float(data.get("prepend_sec", 0.0))
    normalize_audio = bool(data.get("normalize_audio", False))
    zoom            = bool(data.get("zoom", False))
    zoom_from_original = bool(data.get("zoom_from_original", False))
    zoom_end_mode   = data.get("zoom_end_mode", "none").strip()
    zoom_end_sec    = float(data.get("zoom_end_sec", 0.0))
    FG_ZOOM         = float(data.get("zoom_factor") or 1.5)

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

    render_source = clip_path
    tmp_extended  = None

    if extend_sec > 0 or prepend_sec > 0 or zoom:
        meta_path = os.path.join(clips_root, session, "meta.json")
        ko_ts     = _parse_ko_ts_from_filename(orig_name)
        vod_path  = None
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
            vod_path = meta.get("vod_path")

        explicit_start    = None
        explicit_base_dur = None
        if ko_ts is None:
            clip_base      = orig_name.replace("_vertical.mp4", "")
            clips_meta_path = os.path.join(clips_root, session, "clips_meta.json")
            if os.path.exists(clips_meta_path):
                try:
                    with open(clips_meta_path) as f:
                        clips_meta = json.load(f)
                    entry = clips_meta.get(clip_base)
                    if entry:
                        explicit_start    = entry["start_sec"]
                        explicit_base_dur = entry["end_sec"] - entry["start_sec"]
                except Exception:
                    pass

        can_cut = vod_path and os.path.exists(vod_path) and (ko_ts is not None or explicit_start is not None)

        orig_dir       = os.path.join(os.path.dirname(os.path.dirname(clip_path)), "original")
        orig_fname     = os.path.basename(clip_path).replace("_vertical.mp4", "_original.mp4")
        orig_clip_path = os.path.join(orig_dir, orig_fname)

        use_original_source = zoom_from_original or not can_cut

        if use_original_source:
            if os.path.exists(orig_clip_path):
                if zoom_from_original:
                    capture("📽️  Zooming from 16:9 original clip (user selected).")
                else:
                    capture("📽️  VOD unavailable — using 16:9 original as zoom source.")
                tmp_extended = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
                ok_cut = cut_extended_vertical(
                    orig_clip_path, None, extend_sec, tmp_extended,
                    log_fn=capture,
                    fg_zoom=FG_ZOOM if zoom else 1.0,
                    explicit_start=0.0,
                    base_duration=get_clip_duration(orig_clip_path),
                    zoom_end_mode=zoom_end_mode if zoom else "none",
                    zoom_end_sec=zoom_end_sec,
                    prepend_sec=prepend_sec,
                )
                if ok_cut:
                    render_source = tmp_extended
                else:
                    capture("⚠️  Cut from original failed — using standard clip.")
            elif zoom_from_original:
                capture("⚠️  Original clip not found — falling back to VOD source for zoom.")
                use_original_source = False
            else:
                capture("⚠️  VOD not found — zoom/extend unavailable for this session.")

        if not use_original_source and can_cut:
            tmp_extended = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            ok_cut = cut_extended_vertical(
                vod_path, ko_ts, extend_sec, tmp_extended,
                log_fn=capture,
                fg_zoom=FG_ZOOM if zoom else 1.0,
                explicit_start=explicit_start,
                base_duration=explicit_base_dur,
                zoom_end_mode=zoom_end_mode if zoom else "none",
                zoom_end_sec=zoom_end_sec,
                prepend_sec=prepend_sec,
            )
            if ok_cut:
                render_source = tmp_extended
            else:
                capture("⚠️  Cut failed — using standard clip.")
        elif not use_original_source and not can_cut:
            capture("⚠️  No timestamp found for this clip — re-cut it via Manual Cut to enable zoom/extend.")

    try:
        ok = render_with_text(render_source, above, below, output_path, log_fn=capture, hook=hook, hook_offset=hook_offset, normalize_audio=normalize_audio, hook_transition=hook_transition, cut_end_sec=cut_end_sec, hook_only=hook_only, fg_zoom=FG_ZOOM if zoom else 1.0, hook_above=hook_above, hook_below=hook_below)
    finally:
        if tmp_extended and os.path.exists(tmp_extended):
            try:
                os.unlink(tmp_extended)
            except Exception:
                pass

    if ok:
        return jsonify({"ok": True, "path": output_rel, "logs": logs})
    return jsonify({"ok": False, "logs": logs}), 500


@app.route("/hook-slowmo")
def hook_slowmo_page():
    return render_template("hookslomo.html")


@app.route("/run-hook-slowmo", methods=["POST"])
def run_hook_slowmo():
    data          = request.get_json()
    clip_rel      = data.get("clip", "").strip()
    hook_offset   = float(data.get("hook_offset", 3.0))
    slowmo_factor = float(data.get("slowmo_factor", 0.5))
    zoom          = bool(data.get("zoom", False))
    above_text    = data.get("above_text",   "").strip()
    above_text_2  = data.get("above_text_2", "").strip()
    slowmo_start  = float(data.get("slowmo_start", 0.0))
    slowmo_end    = float(data.get("slowmo_end",   hook_offset))
    transition    = data.get("transition", "cut").strip()

    if not clip_rel:
        return jsonify({"error": "clip is required"}), 400

    clips_root = os.path.abspath("clips")
    clip_path  = os.path.join(clips_root, clip_rel.replace("/", os.sep))
    if not os.path.exists(clip_path):
        return jsonify({"error": "Clip not found"}), 404

    parts      = clip_rel.replace("\\", "/").split("/")
    session    = parts[0]
    orig_name  = parts[-1]
    final_name = orig_name.replace("_vertical.mp4", "_hookslomo.mp4")
    if final_name == orig_name:
        final_name = os.path.splitext(orig_name)[0] + "_hookslomo.mp4"

    finals_dir  = os.path.join(clips_root, session, "finals")
    output_path = os.path.join(finals_dir, final_name)
    output_rel  = f"{session}/finals/{final_name}"

    logs = []
    def capture(msg):
        logs.append(msg)
        log(msg)

    def do_render():
        ok = render_hook_slowmo(clip_path, hook_offset, slowmo_factor, output_path, zoom=zoom, above_text=above_text, above_text_2=above_text_2, slowmo_start=slowmo_start, slowmo_end=slowmo_end, transition=transition, log_fn=capture)
        if ok:
            log(f"__hookslomo_done__:{output_rel}")
        else:
            log("__hookslomo_failed__")

    threading.Thread(target=do_render, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/replay")
def replay_page():
    return render_template("replay.html")


@app.route("/run-replay", methods=["POST"])
def run_replay():
    data         = request.get_json()
    session      = data.get("session", "").strip()
    clip_rel     = data.get("clip", "").strip()
    top_text     = data.get("top_text", "DID YOU CATCH IT?").strip()
    replay_text  = data.get("replay_text", "").strip()
    c4_time      = float(data.get("c4_time", 1.0))
    slowmo_input = float(data.get("slowmo_input", 1.5))
    slowmo_factor= float(data.get("slowmo_factor", 0.5))
    zoom_factor  = float(data.get("zoom_factor", 1.5))
    crossfade_dur  = float(data.get("crossfade_dur", 0.5))
    ko_hook        = bool(data.get("ko_hook", False))
    ko_hook_offset = float(data.get("ko_hook_offset", 6.0))

    if not session or not clip_rel:
        return jsonify({"error": "session and clip are required"}), 400

    clips_root = os.path.abspath("clips")
    clip_path  = os.path.join(clips_root, session, "vertical", clip_rel)
    if not os.path.exists(clip_path):
        return jsonify({"error": "Clip not found"}), 404

    base       = clip_rel.replace("_vertical.mp4", "")
    out_name   = f"{base}_replay.mp4"
    output_dir = os.path.join(clips_root, session, "replay")
    output_path= os.path.join(output_dir, out_name)
    output_rel = f"{session}/replay/{out_name}"

    def do_replay():
        ok = render_replay(
            clip_path, top_text, replay_text, c4_time, slowmo_input,
            slowmo_factor, zoom_factor, crossfade_dur,
            output_path, log_fn=log,
            ko_hook=ko_hook, ko_hook_offset=ko_hook_offset,
        )
        if ok:
            log(f"__replay_done__:{output_rel}")
        else:
            log("__replay_failed__")

    threading.Thread(target=do_replay, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/stitch")
def stitch_page():
    return render_template("stitch.html")


@app.route("/run-stitch", methods=["POST"])
def run_stitch():
    data            = request.get_json()
    session         = data.get("session", "").strip()
    clip1_rel       = data.get("clip1", "").strip()
    clip2_rel       = data.get("clip2", "").strip()
    above1          = data.get("above1", "").strip()
    below1          = data.get("below1", "").strip()
    hook_offset1    = float(data.get("hook_offset1", 2.8))
    above2          = data.get("above2", "").strip()
    below2          = data.get("below2", "").strip()
    hook_offset2    = float(data.get("hook_offset2", 2.8))
    transition_text = data.get("transition_text", "Later...").strip() or "Later..."

    if not session or not clip1_rel or not clip2_rel:
        return jsonify({"error": "session, clip1 and clip2 are required"}), 400

    clips_root = os.path.abspath("clips")
    clip1_path = os.path.join(clips_root, session, "vertical", clip1_rel)
    clip2_path = os.path.join(clips_root, session, "vertical", clip2_rel)

    if not os.path.exists(clip1_path):
        return jsonify({"error": f"Clip 1 not found: {clip1_rel}"}), 404
    if not os.path.exists(clip2_path):
        return jsonify({"error": f"Clip 2 not found: {clip2_rel}"}), 404

    base1 = clip1_rel.replace("_vertical.mp4", "")
    base2 = clip2_rel.replace("_vertical.mp4", "")
    out_name   = f"{base1}__{base2}_stitch.mp4"
    output_dir = os.path.join(clips_root, session, "combined")
    output_path = os.path.join(output_dir, out_name)
    output_rel  = f"{session}/combined/{out_name}"

    def do_stitch():
        ok = render_stitch(
            clip1_path, clip2_path,
            above1, below1, hook_offset1,
            above2, below2, hook_offset2,
            transition_text, output_path,
            log_fn=log,
        )
        if ok:
            log(f"__stitch_done__:{output_rel}")
        else:
            log("__stitch_failed__")

    threading.Thread(target=do_stitch, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/dankify")
def dankify_page():
    return render_template("dankify.html")


@app.route("/run-dankify", methods=["POST"])
def run_dankify():
    data       = request.get_json()
    session    = data.get("session", "").strip()
    clip_rel   = data.get("clip", "").strip()
    hook_start = float(data.get("hook_start", 0))

    if not session or not clip_rel:
        return jsonify({"error": "session and clip are required"}), 400

    clips_root = os.path.abspath("clips")
    clip_path  = os.path.join(clips_root, session, "vertical", clip_rel)
    if not os.path.exists(clip_path):
        return jsonify({"error": "Clip not found"}), 404

    base        = clip_rel.replace("_vertical.mp4", "")
    out_name    = f"{base}_dankify.mp4"
    output_dir  = os.path.join(clips_root, session, "dankify")
    output_path = os.path.join(output_dir, out_name)
    output_rel  = f"{session}/dankify/{out_name}"

    def do_dankify():
        ok = render_dankify(clip_path, hook_start, output_path, log_fn=log)
        if ok:
            log(f"__dankify_done__:{output_rel}")
        else:
            log("__dankify_failed__")

    threading.Thread(target=do_dankify, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/montage")
def montage_page():
    return render_template("montage.html")


@app.route("/montage-original")
def montage_original_page():
    return render_template("montage_original.html")


@app.route("/run-montage", methods=["POST"])
def run_montage():
    data       = request.get_json()
    session    = data.get("session", "").strip()
    top_text   = data.get("top_text", "").strip()
    transition = data.get("transition", "cut").strip()
    logo_path     = data.get("logo_path", "").strip() or None
    black_top_bar = bool(data.get("black_top_bar", False))
    zoom          = bool(data.get("zoom", False))
    clips_data    = data.get("clips", [])
    FG_ZOOM       = 1.5

    if not session or len(clips_data) < 2:
        return jsonify({"error": "session and at least 2 clips are required"}), 400

    subfolder  = "original" if zoom else "vertical"
    clips_root = os.path.abspath("clips")
    clips_info = []
    for c in clips_data:
        clip_rel    = c.get("clip", "").strip()
        hook_offset = float(c.get("hook_offset", 5.0))
        end_early   = float(c.get("end_early", 0.0))
        if not clip_rel:
            return jsonify({"error": "Each clip entry must have a clip filename"}), 400
        clip_path = os.path.join(clips_root, session, subfolder, clip_rel)
        if not os.path.exists(clip_path):
            return jsonify({"error": f"Clip not found: {clip_rel}"}), 404
        clip_transition = c.get("transition", "").strip() or transition
        clip_top_text   = c.get("top_text", "").strip()
        clips_info.append({"path": clip_path, "hook_offset": hook_offset, "end_early": end_early, "transition": clip_transition, "top_text": clip_top_text})

    out_name    = f"montage_{int(time.time())}.mp4"
    output_dir  = os.path.join(clips_root, session, "montage")
    output_path = os.path.join(output_dir, out_name)
    output_rel  = f"{session}/montage/{out_name}"

    def do_montage():
        ok = render_montage(clips_info, top_text, transition, output_path, log_fn=log,
                            logo_path=logo_path, black_top_bar=black_top_bar,
                            fg_zoom=FG_ZOOM if zoom else 1.0)
        if ok:
            log(f"__montage_done__:{output_rel}")
        else:
            log("__montage_failed__")

    threading.Thread(target=do_montage, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/run-montage-original", methods=["POST"])
def run_montage_original():
    data       = request.get_json()
    session    = data.get("session", "").strip()
    top_text   = data.get("top_text", "").strip()
    transition = data.get("transition", "cut").strip()
    clips_data = data.get("clips", [])

    if not session or len(clips_data) < 2:
        return jsonify({"error": "session and at least 2 clips are required"}), 400

    clips_root = os.path.abspath("clips")
    clips_info = []
    for c in clips_data:
        clip_rel    = c.get("clip", "").strip()
        hook_offset = float(c.get("hook_offset", 5.0))
        end_early   = float(c.get("end_early", 0.0))
        if not clip_rel:
            return jsonify({"error": "Each clip entry must have a clip filename"}), 400
        clip_path = os.path.join(clips_root, session, "original", clip_rel)
        if not os.path.exists(clip_path):
            return jsonify({"error": f"Clip not found: {clip_rel}"}), 404
        clip_transition = c.get("transition", "").strip() or transition
        clips_info.append({"path": clip_path, "hook_offset": hook_offset, "end_early": end_early, "transition": clip_transition})

    out_name    = f"montage_{int(time.time())}.mp4"
    output_dir  = os.path.join(clips_root, session, "montage_original")
    output_path = os.path.join(output_dir, out_name)
    output_rel  = f"{session}/montage_original/{out_name}"

    def do_montage():
        ok = render_montage(clips_info, top_text, transition, output_path, log_fn=log)
        if ok:
            log(f"__montage_orig_done__:{output_rel}")
        else:
            log("__montage_orig_failed__")

    threading.Thread(target=do_montage, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/fadetotext")
def fadetotext_page():
    return render_template("fadetotext.html")


@app.route("/run-fadetotext", methods=["POST"])
def run_fadetotext():
    data       = request.get_json()
    session    = data.get("session", "").strip()
    clip_rel   = data.get("clip", "").strip()
    hook_offset = float(data.get("hook_offset", 5.0))
    fade_text   = data.get("fade_text", "").strip()
    top_text    = data.get("top_text", "").strip()

    if not session or not clip_rel:
        return jsonify({"error": "session and clip are required"}), 400
    if not fade_text:
        return jsonify({"error": "fade_text is required"}), 400

    clips_root = os.path.abspath("clips")
    clip_path  = os.path.join(clips_root, session, "vertical", clip_rel)
    if not os.path.exists(clip_path):
        return jsonify({"error": "Clip not found"}), 404

    base        = clip_rel.replace("_vertical.mp4", "")
    out_name    = f"{base}_fadetotext.mp4"
    output_dir  = os.path.join(clips_root, session, "fadetotext")
    output_path = os.path.join(output_dir, out_name)
    output_rel  = f"{session}/fadetotext/{out_name}"

    def do_fadetotext():
        ok = render_fade_to_text(clip_path, hook_offset, fade_text, output_path, log_fn=log, top_text=top_text)
        if ok:
            log(f"__fadetotext_done__:{output_rel}")
        else:
            log("__fadetotext_failed__")

    threading.Thread(target=do_fadetotext, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/manual-clip", methods=["POST"])
def manual_clip():
    data      = request.get_json()
    session   = data.get("session", "").strip()
    start_sec = float(data.get("start_sec", 0))
    end_sec   = float(data.get("end_sec", 0))
    clip_name = data.get("clip_name", "").strip()

    if not session:
        return jsonify({"error": "session is required"}), 400
    if end_sec <= start_sec:
        return jsonify({"error": "end must be after start"}), 400

    clips_root  = os.path.abspath("clips")
    session_dir = os.path.join(clips_root, session)
    meta_path   = os.path.join(session_dir, "meta.json")

    if not os.path.exists(meta_path):
        return jsonify({"error": "Session not found (no meta.json)"}), 404

    with open(meta_path) as f:
        meta = json.load(f)
    vod_path = meta.get("vod_path")
    if not vod_path or not os.path.exists(vod_path):
        return jsonify({"error": f"VOD not found: {vod_path}"}), 404

    if not clip_name:
        vert_dir = os.path.join(session_dir, "vertical")
        next_num = 1
        if os.path.exists(vert_dir):
            existing = [f for f in os.listdir(vert_dir) if f.endswith("_vertical.mp4")]
            next_num = len(existing) + 1
        mins = int(start_sec // 60)
        secs = int(start_sec % 60)
        clip_name = f"clip_{next_num}_{mins}m{secs}s"

    def do_cut():
        ok = cut_manual_clip(vod_path, start_sec, end_sec, session_dir, clip_name, log_fn=log)
        if ok:
            log(f"__manual_clip_done__:{session}")
        else:
            log("__manual_clip_failed__")

    threading.Thread(target=do_cut, daemon=True).start()
    return jsonify({"status": "started", "clip_name": clip_name})


@app.route("/clips-serve/<path:filename>")
def serve_clip(filename):
    resp = send_from_directory(os.path.abspath('clips'), filename)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route("/open-folder", methods=["POST"])
def open_folder_route():
    data = request.get_json()
    rel       = (data.get("path") or "").strip()
    file_name = (data.get("file") or "").strip()
    if not rel:
        return jsonify({"error": "No path"}), 400
    abs_path = os.path.abspath(rel)
    app_root = os.path.abspath(".")
    if not abs_path.startswith(app_root):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(abs_path):
        return jsonify({"error": "Path not found"}), 404
    if file_name:
        abs_file = os.path.join(abs_path, file_name)
        subprocess.Popen(f'explorer /select,"{abs_file}"')
    else:
        subprocess.Popen(f'explorer "{abs_path}"')
    return jsonify({"ok": True})


@app.route("/copy-clip", methods=["POST"])
def copy_clip_route():
    data = request.get_json()
    rel = (data.get("file") or "").strip()
    if not rel:
        return jsonify({"error": "No file specified"}), 400
    abs_file = os.path.abspath(rel)
    app_root = os.path.abspath(".")
    if not abs_file.startswith(app_root):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(abs_file):
        return jsonify({"error": "File not found"}), 404
    ps_cmd = (
        "Add-Type -Assembly System.Windows.Forms; "
        "$f = New-Object System.Collections.Specialized.StringCollection; "
        f"$f.Add('{abs_file}'); "
        "[System.Windows.Forms.Clipboard]::SetFileDropList($f)"
    )
    subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps_cmd])
    return jsonify({"ok": True})


@app.route("/run", methods=["POST"])
def run():
    data = request.get_json()
    url = data.get("url", "").strip()
    local_path = data.get("path", "").strip()
    if not url and not local_path:
        return jsonify({"error": "No URL or path provided"}), 400
    start_sec = data.get("start_sec")
    end_sec = data.get("end_sec")
    start_sec = float(start_sec) if start_sec not in (None, "") else None
    end_sec = float(end_sec) if end_sec not in (None, "") else None
    threading.Thread(target=run_pipeline, args=(url, local_path, start_sec, end_sec), daemon=True).start()
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


def run_pipeline(url, local_path='', start_sec=None, end_sec=None):
    try:
        expected_duration_sec = None
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
            video_title, filename_stem, expected_duration_sec = get_video_info(url)
            if not video_title:
                log("❌  Could not fetch video info.")
                log("__done__")
                return
            log(f"📺  Title: {video_title}")
            cached_path = next(
                (p for ext in ('.mp4', '.mkv')
                 if os.path.exists(p := os.path.join("downloads", filename_stem + ext))),
                None,
            )
            if cached_path:
                log("✅  Already downloaded — skipping re-download.")
                video_path = cached_path
            else:
                log("📥  Downloading VOD...")
                video_path = download_vod(url)
                if not video_path:
                    log("❌  Download failed.")
                    log("__done__")
                    return

        log("🔎  Verifying download integrity...")
        if not verify_video_integrity(video_path, log_fn=log, expected_duration_sec=expected_duration_sec):
            log("❌  Video file is corrupted or unreadable (likely a broken download/merge).")
            if not local_path:
                try:
                    failed_dir = os.path.join("downloads", "FAILED")
                    os.makedirs(failed_dir, exist_ok=True)
                    stamp = time.strftime("%Y%m%d_%H%M%S")
                    base_name = os.path.basename(video_path)
                    failed_video_path = os.path.join(failed_dir, f"{stamp}_{base_name}")
                    shutil.move(video_path, failed_video_path)
                    cache_path = os.path.splitext(video_path)[0] + "_ko_cache.json"
                    if os.path.exists(cache_path):
                        failed_cache_path = os.path.join(failed_dir, f"{stamp}_{os.path.basename(cache_path)}")
                        shutil.move(cache_path, failed_cache_path)
                    log(f"📁  Moved corrupted download to {failed_video_path} for analysis — please retry.")
                except Exception as e:
                    log(f"⚠️  Could not move corrupted file: {e}")
            log("__done__")
            return

        log("\n🔍  Scanning for KO flashes...")
        events = detect_ko_events(video_path, log_fn=log, start_scan_sec=start_sec, max_scan_sec=end_sec)

        safe_title = safe_folder_name(video_title)
        clips_dir = os.path.join("clips", safe_title)
        os.makedirs(clips_dir, exist_ok=True)
        meta_path = os.path.join(clips_dir, "meta.json")
        if not os.path.exists(meta_path):
            with open(meta_path, "w") as f:
                json.dump({"venue": video_title, "source": url or local_path, "vod_path": video_path}, f, indent=2)

        if not events:
            log("⚠️  No KO events detected. Session created — use Manual Cut to add clips.")
            log(f"__done__:{safe_title}")
            return

        cut_clips(video_path, events, output_dir=clips_dir, log_fn=log)

        log(f"\n✅  Done! Clips saved to: {os.path.abspath(clips_dir)}")
        log(f"__done__:{safe_title}")

    except Exception as e:
        log(f"\n❌  Error: {e}")
        log("__done__")


VOD_OUTTMPL = 'downloads/%(title)s.%(ext)s'


def get_video_info(url):
    ydl_opts = {'quiet': True, 'skip_download': True, 'outtmpl': VOD_OUTTMPL}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            safe = ydl.prepare_filename(info).replace('\\', '/').split('/')[-1]
            return title, os.path.splitext(safe)[0], info.get('duration')
    except Exception as e:
        log(f"⚠️  Could not fetch info: {e}")
        return None, None, None


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
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': VOD_OUTTMPL,
        'merge_output_format': 'mkv',
        'remuxvideo': 'mkv',
        'logger': YTLogger(),
        'retries': float('inf'),
        'fragment_retries': float('inf'),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        requested = info.get('requested_downloads') or []
        actual_path = requested[0].get('filepath') if requested else None
        filename = ydl.prepare_filename(info).replace('\\', '/').split('/')[-1]

    # Prefer yt-dlp's own record of what it wrote to disk — reconstructing the
    # name from prepare_filename + a guessed extension can miss postprocessing
    # (remux/merge) renames, and a wrong guess here must never silently fall
    # back to an unrelated file already sitting in downloads/.
    if actual_path and os.path.exists(actual_path):
        return actual_path

    base = os.path.splitext(os.path.join("downloads", filename))[0]
    for ext in ('.mkv', '.mp4'):
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    return None


def _clip_num(filename):
    m = re.search(r'clip_(\d+)_', filename)
    return int(m.group(1)) if m else 0


def _parse_ko_ts_from_filename(filename):
    """Parse KO timestamp (seconds) from a clip filename like clip_1_5m23s_vertical.mp4."""
    m = re.search(r'_(\d+)m(\d+)s', filename)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def safe_folder_name(title):
    invalid = r'\/:*?"<>|'
    cleaned = ''.join(c for c in title if c not in invalid).strip()[:80]
    return cleaned.rstrip('. ')


# ── Archive ───────────────────────────────────────────────────────────────────

@app.route("/hype-reel")
def hype_reel_page():
    return render_template("hypereel.html")


@app.route("/outro-music")
def outro_music():
    music_dir = os.path.join(os.path.abspath("props"), "music")
    files = []
    if os.path.exists(music_dir):
        for f in sorted(os.listdir(music_dir)):
            if f.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac', '.mp4')):
                files.append(f)
    return jsonify({"files": files})


@app.route("/sessions-with-originals")
def sessions_with_originals():
    clips_root = os.path.abspath("clips")
    sessions = []
    if os.path.exists(clips_root):
        for name in sorted(os.listdir(clips_root)):
            orig_dir = os.path.join(clips_root, name, "original")
            if os.path.isdir(orig_dir) and any(f.endswith('.mp4') for f in os.listdir(orig_dir)):
                sessions.append(name)
    return jsonify({"sessions": sessions})


@app.route("/original-clips/<path:session>")
def original_clips(session):
    clips_root = os.path.abspath("clips")
    orig_dir   = os.path.join(clips_root, session, "original")
    clips = []
    if os.path.exists(orig_dir):
        for f in sorted(os.listdir(orig_dir), key=_clip_num):
            if not f.endswith('.mp4'):
                continue
            m    = re.search(r'clip_(\d+)_(\d+)m(\d+)s', f)
            name = f"Game {m.group(1)} · {m.group(2)}:{m.group(3).zfill(2)}" if m else f.replace('_original.mp4', '')
            clips.append({"filename": f, "name": name})
    return jsonify({"clips": clips})


@app.route("/run-hype-reel", methods=["POST"])
def run_hype_reel():
    data        = request.get_json()
    title_text  = data.get("title_text", "SoCal is Hype Vol 1").strip()
    logo_path   = data.get("logo_path", "").strip() or None
    clips_data  = data.get("clips", [])
    outro_music = data.get("outro_music", "").strip() or None
    outro_music_path = None
    if outro_music:
        candidate = os.path.join(os.path.abspath("props"), "music", outro_music)
        if os.path.exists(candidate):
            outro_music_path = candidate

    if len(clips_data) < 2:
        return jsonify({"error": "Need at least 2 clips"}), 400

    clips_root = os.path.abspath("clips")
    clips_info = []
    for c in clips_data:
        session    = c.get("session", "").strip()
        clip_file  = c.get("clip", "").strip()
        hook_offset = float(c.get("hook_offset", 5.0))
        transition  = c.get("transition", "flash").strip()
        if not session or not clip_file:
            return jsonify({"error": "Each clip must have session and clip"}), 400
        clip_path = os.path.join(clips_root, session, "original", clip_file)
        if not os.path.exists(clip_path):
            return jsonify({"error": f"Clip not found: {clip_file}"}), 404
        clips_info.append({"path": clip_path, "hook_offset": hook_offset, "transition": transition})

    session    = clips_data[0].get("session", "").strip()
    out_dir    = os.path.join(os.path.abspath("clips"), session, "hype_reels")
    os.makedirs(out_dir, exist_ok=True)
    out_name    = f"hype_reel_{int(time.time())}.mp4"
    output_path = os.path.join(out_dir, out_name)
    output_rel  = f"{session}/hype_reels/{out_name}"

    def do_hype_reel():
        ok = render_hype_reel(clips_info, title_text, logo_path, output_path, log_fn=log, outro_music_path=outro_music_path)
        if ok:
            log(f"__hypereel_done__:{output_rel}")
        else:
            log("__hypereel_failed__")

    threading.Thread(target=do_hype_reel, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/hype-reels-serve/<path:filename>")
def serve_hype_reel(filename):
    resp = send_from_directory(os.path.abspath("clips"), filename)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/beat-sync")
def beat_sync_page():
    return render_template("beat_sync.html")


@app.route("/run-beat-sync", methods=["POST"])
def run_beat_sync():
    data           = request.get_json()
    session        = data.get("session", "").strip()
    clip_file      = data.get("clip", "").strip()
    audio_file     = data.get("audio", "").strip()
    hit_times      = [float(t) for t in data.get("hit_times", [])]
    beat_times     = [float(t) for t in data.get("beat_times", [])]
    effect         = data.get("effect", "none").strip()
    flash_delay    = float(data.get("flash_delay", 0.0))
    context_before = float(data.get("context_before", 3.0))
    context_after  = float(data.get("context_after", 2.0))
    logo_path      = os.path.join(os.path.abspath("static"), "favicon.png")
    black_top_bar  = bool(data.get("black_top_bar", False))
    top_text       = data.get("top_text", "").strip()

    if not session or not clip_file or not audio_file:
        return jsonify({"error": "session, clip, and audio required"}), 400
    if len(hit_times) < 2 or len(beat_times) < 2:
        return jsonify({"error": "Need at least 2 hit and beat times"}), 400

    clips_root  = os.path.abspath("clips")
    clip_path   = os.path.join(clips_root, session, "original", clip_file)
    audio_path  = os.path.join(os.path.abspath("props"), "music", audio_file)

    if not os.path.exists(clip_path):
        return jsonify({"error": f"Clip not found: {clip_file}"}), 404
    if not os.path.exists(audio_path):
        return jsonify({"error": f"Audio not found: {audio_file}"}), 404

    out_dir     = os.path.join(clips_root, session, "beat_sync")
    os.makedirs(out_dir, exist_ok=True)
    out_name    = f"beat_sync_{int(time.time())}.mp4"
    output_path = os.path.join(out_dir, out_name)
    output_rel  = f"{session}/beat_sync/{out_name}"

    def do_render():
        ok = render_beat_sync(clip_path, hit_times, beat_times, audio_path, output_path,
                              effect=effect, flash_delay=flash_delay,
                              context_before=context_before, context_after=context_after,
                              logo_path=logo_path, black_top_bar=black_top_bar,
                              top_text=top_text, log_fn=log)
        if ok:
            log(f"__beat_sync_done__:{output_rel}")
        else:
            log("__beat_sync_failed__")

    threading.Thread(target=do_render, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/archive")
def archive_page():
    return render_template("archive.html")


@app.route("/archive-list")
def archive_list():
    archive_root = os.path.abspath("archive")
    months = []
    if os.path.exists(archive_root):
        for name in sorted(os.listdir(archive_root), reverse=True):
            month_path = os.path.join(archive_root, name)
            if not os.path.isdir(month_path):
                continue
            meta_path = os.path.join(month_path, "meta.json")
            meta = {"clips": {}, "finals": {}, "montages": {}}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                except Exception:
                    pass
            months.append({"month": name, "meta": meta})
    return jsonify({"months": months})


@app.route("/run-archive", methods=["POST"])
def run_archive():
    data         = request.get_json() or {}
    preview_only = bool(data.get("preview", True))

    clips_root   = os.path.abspath("clips")
    archive_root = os.path.abspath("archive")
    month        = time.strftime("%Y-%m")
    month_dir    = os.path.join(archive_root, month)

    if not os.path.exists(clips_root):
        return jsonify({"error": "No clips folder found"}), 404

    items = []  # {type, src, dest_name, venue, source, has_original}
    session_count = 0

    for session_name in sorted(os.listdir(clips_root)):
        session_path = os.path.join(clips_root, session_name)
        if not os.path.isdir(session_path):
            continue

        meta_path = os.path.join(session_path, "meta.json")
        venue  = session_name
        source = ""
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                venue  = meta.get("venue", session_name)
                source = meta.get("source", "")
            except Exception:
                pass

        review_path   = os.path.join(session_path, "review.json")
        review_states = {}  # no review file = nothing flagged yet
        if os.path.exists(review_path):
            try:
                with open(review_path) as f:
                    review_states = json.load(f)
            except Exception:
                review_states = {}

        vert_dir    = os.path.join(session_path, "vertical")
        orig_dir    = os.path.join(session_path, "original")
        finals_dir  = os.path.join(session_path, "finals")
        montage_dir = os.path.join(session_path, "montage")
        session_contributed = False
        prefix = f"{session_name}__"

        if os.path.exists(vert_dir):
            for fname in sorted(os.listdir(vert_dir)):
                if not fname.endswith("_vertical.mp4"):
                    continue
                base        = fname.replace("_vertical.mp4", "")
                final_fname = base + "_final.mp4"
                has_final   = os.path.exists(os.path.join(finals_dir, final_fname)) if os.path.exists(finals_dir) else False
                is_flagged  = review_states.get(base) == "flagged"
                if not (is_flagged or has_final):
                    continue

                orig_fname   = base + "_original.mp4"
                has_original = os.path.exists(os.path.join(orig_dir, orig_fname))
                items.append({
                    "type":         "vertical",
                    "src":          os.path.join(vert_dir, fname),
                    "dest_name":    prefix + fname,
                    "venue":        venue,
                    "source":       source,
                    "has_original": has_original,
                })
                if has_original:
                    items.append({
                        "type":      "original",
                        "src":       os.path.join(orig_dir, orig_fname),
                        "dest_name": prefix + orig_fname,
                        "venue":     venue,
                        "source":    source,
                    })
                session_contributed = True

        if os.path.exists(finals_dir):
            for fname in sorted(os.listdir(finals_dir)):
                if not fname.endswith(".mp4"):
                    continue
                items.append({
                    "type":      "final",
                    "src":       os.path.join(finals_dir, fname),
                    "dest_name": prefix + fname,
                    "venue":     venue,
                    "source":    source,
                })
                session_contributed = True

        if os.path.exists(montage_dir):
            for fname in sorted(os.listdir(montage_dir)):
                if not fname.endswith(".mp4"):
                    continue
                items.append({
                    "type":      "montage",
                    "src":       os.path.join(montage_dir, fname),
                    "dest_name": prefix + fname,
                    "venue":     venue,
                    "source":    source,
                })
                session_contributed = True

        # Scan all subdirs by filename suffix — handles custom folder names like slo-mo-moment
        suffix_type_map = {
            "_replay.mp4":  "replay",
            "_dankify.mp4": "dankify",
            "_stitch.mp4":  "stitch",
        }
        known_dirs = {"vertical", "original", "finals", "montage"}
        already_added = {i["dest_name"] for i in items}
        for subdir_name in sorted(os.listdir(session_path)):
            if subdir_name.lower() in known_dirs:
                continue
            subdir_path = os.path.join(session_path, subdir_name)
            if not os.path.isdir(subdir_path):
                continue
            for fname in sorted(os.listdir(subdir_path)):
                proc_type = next((t for sfx, t in suffix_type_map.items() if fname.endswith(sfx)), None)
                if proc_type is None:
                    continue
                dest_name = prefix + fname
                if dest_name in already_added:
                    continue
                items.append({
                    "type":      proc_type,
                    "src":       os.path.join(subdir_path, fname),
                    "dest_name": dest_name,
                    "venue":     venue,
                    "source":    source,
                })
                already_added.add(dest_name)
                session_contributed = True

        if session_contributed:
            session_count += 1

    clip_items    = [i for i in items if i["type"] == "vertical"]
    final_items   = [i for i in items if i["type"] == "final"]
    montage_items = [i for i in items if i["type"] == "montage"]
    dankify_items = [i for i in items if i["type"] == "dankify"]
    replay_items  = [i for i in items if i["type"] == "replay"]
    stitch_items  = [i for i in items if i["type"] == "stitch"]
    total_bytes   = sum(os.path.getsize(i["src"]) for i in items if os.path.exists(i["src"]))

    stats = {
        "sessions": session_count,
        "clips":    len(clip_items),
        "finals":   len(final_items),
        "montages": len(montage_items),
        "dankify":  len(dankify_items),
        "replay":   len(replay_items),
        "stitch":   len(stitch_items),
        "size_mb":  round(total_bytes / (1024 * 1024), 1),
        "month":    month,
    }

    if preview_only:
        return jsonify({"ok": True, "preview": True, "stats": stats})

    if not items:
        return jsonify({"error": "Nothing to archive"}), 400

    for subdir in ("vertical", "original", "finals", "montages", "dankify", "replay", "stitch"):
        os.makedirs(os.path.join(month_dir, subdir), exist_ok=True)

    meta_out = {"archived_at": time.strftime("%Y-%m-%d"), "clips": {}, "finals": {}, "montages": {}, "dankify": {}, "replay": {}, "stitch": {}}
    meta_path = os.path.join(month_dir, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta_out = json.load(f)
            for key in ("clips", "finals", "montages", "dankify", "replay", "stitch"):
                meta_out.setdefault(key, {})
            meta_out["archived_at"] = time.strftime("%Y-%m-%d")
        except Exception:
            pass

    subdir_map = {"vertical": "vertical", "original": "original", "final": "finals", "montage": "montages", "dankify": "dankify", "replay": "replay", "stitch": "stitch"}
    for item in items:
        dest = os.path.join(month_dir, subdir_map[item["type"]], item["dest_name"])
        shutil.copy2(item["src"], dest)
        entry = {"venue": item["venue"], "source": item["source"]}
        if item["type"] == "vertical":
            entry["has_original"] = item.get("has_original", False)
            meta_out["clips"][item["dest_name"]] = entry
        elif item["type"] == "final":
            meta_out["finals"][item["dest_name"]] = entry
        elif item["type"] == "montage":
            meta_out["montages"][item["dest_name"]] = entry
        elif item["type"] in ("dankify", "replay", "stitch"):
            meta_out[item["type"]][item["dest_name"]] = entry

    with open(meta_path, "w") as f:
        json.dump(meta_out, f, indent=2)

    return jsonify({"ok": True, "preview": False, "stats": stats})


@app.route("/restore-venue", methods=["POST"])
def restore_venue():
    data  = request.get_json() or {}
    month = data.get("month", "").strip()
    venue = data.get("venue", "").strip()
    if not month or not venue:
        return jsonify({"error": "month and venue required"}), 400

    archive_root = os.path.abspath("archive")
    clips_root   = os.path.abspath("clips")
    meta_path    = os.path.join(archive_root, month, "meta.json")
    if not os.path.exists(meta_path):
        return jsonify({"error": "Archive month not found"}), 404

    with open(meta_path) as f:
        meta = json.load(f)

    # archive subdir → clips subdir
    subdir_map = {
        "vertical":  "vertical",
        "original":  "original",
        "finals":    "finals",
        "montages":  "montage",
        "dankify":   "dankify",
        "replay":    "replay",
        "stitch":    "stitch",
    }
    # meta key → archive subdir
    key_subdir = {
        "clips":    "vertical",
        "finals":   "finals",
        "montages": "montages",
        "dankify":  "dankify",
        "replay":   "replay",
        "stitch":   "stitch",
    }

    restored = 0
    sessions_written = set()

    for meta_key, archive_subdir in key_subdir.items():
        for fname, entry in meta.get(meta_key, {}).items():
            if entry.get("venue") != venue:
                continue
            # extract session name from prefix
            if "__" not in fname:
                continue
            session_name = fname.split("__")[0]
            bare_name    = fname.split("__", 1)[1]

            clips_subdir = subdir_map[archive_subdir]
            dest_dir  = os.path.join(clips_root, session_name, clips_subdir)
            os.makedirs(dest_dir, exist_ok=True)
            src = os.path.join(archive_root, month, archive_subdir, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest_dir, bare_name))
                restored += 1

            # also restore paired original for vertical clips
            if meta_key == "clips" and entry.get("has_original"):
                orig_fname = fname.replace("_vertical.mp4", "_original.mp4")
                orig_bare  = bare_name.replace("_vertical.mp4", "_original.mp4")
                orig_src   = os.path.join(archive_root, month, "original", orig_fname)
                orig_dest  = os.path.join(clips_root, session_name, "original")
                os.makedirs(orig_dest, exist_ok=True)
                if os.path.exists(orig_src):
                    shutil.copy2(orig_src, os.path.join(orig_dest, orig_bare))

            # write session meta.json if not already done
            if session_name not in sessions_written:
                session_dir   = os.path.join(clips_root, session_name)
                sess_meta_path = os.path.join(session_dir, "meta.json")
                if not os.path.exists(sess_meta_path):
                    with open(sess_meta_path, "w") as f:
                        json.dump({
                            "venue":    entry.get("venue", session_name),
                            "source":   entry.get("source", ""),
                            "vod_path": "",
                        }, f, indent=2)
                sessions_written.add(session_name)

    return jsonify({"ok": True, "restored": restored})


@app.route("/archive-serve/<path:filename>")
def serve_archive(filename):
    resp = send_from_directory(os.path.abspath("archive"), filename)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/archive-thumb/<path:filename>")
def serve_archive_thumb(filename):
    archive_root = os.path.abspath("archive")
    video_path   = os.path.join(archive_root, filename)
    if not os.path.exists(video_path):
        return "", 404

    parts      = filename.replace("\\", "/").split("/")
    month      = parts[0]
    base_name  = os.path.splitext(parts[-1])[0]
    thumb_dir  = os.path.join(archive_root, month, "thumbs")
    thumb_name = base_name + ".jpg"
    thumb_path = os.path.join(thumb_dir, thumb_name)

    if not os.path.exists(thumb_path):
        os.makedirs(thumb_dir, exist_ok=True)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "1", "-i", video_path,
                 "-vframes", "1", "-q:v", "5", "-vf", "scale=320:-1", thumb_path],
                capture_output=True, timeout=15
            )
        except Exception:
            return "", 500

    if not os.path.exists(thumb_path):
        return "", 404

    from flask import send_file
    return send_file(thumb_path, mimetype="image/jpeg")


if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    app.run(debug=True, port=5000, threaded=True)
