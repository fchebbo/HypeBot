import cv2
import numpy as np
import subprocess
import os
import json
import tempfile
from collections import deque

# --- Tunable constants ---
# BRIGHTNESS_THRESHOLD retired — replaced by BRIGHT_PIXEL_RATIO check below
MIN_FLASH_DURATION_SEC = 0.3
MAX_FLASH_DURATION_SEC = 1.5
FRAME_SKIP = 4          # grab() skips without decoding — safe to go higher
KO_OFFSET_SEC = 6.0
CLIP_BEFORE_SEC = 10.0
CLIP_AFTER_SEC = 3.0
FFMPEG_TIMEOUT = 120

# --- Blur background tuning ---
BLUR_STRENGTH = 20      # Higher = more blurred background (10-30 recommended)

SCAN_LOG_INTERVAL = 5000  # frames between scan progress updates in browser
SCAN_RESIZE_W = 320       # resize frames to this width before brightness check
BRIGHT_PIXEL_THRESHOLD = 185   # minimum per-channel brightness to count as "white"
BRIGHT_PIXEL_SPREAD    = 40    # max channel spread (R-B etc) — filters pink/yellow/colored effects
BRIGHT_PIXEL_RATIO     = 0.55  # fraction of true-white pixels required to trigger
FLASH_SPIKE            = 0.30  # how much above rolling baseline the ratio must jump to trigger
ROLLING_WINDOW         = 40    # decoded frames to track for baseline (~3-4s at FRAME_SKIP=4, 30fps)

# --- Red flash detection (KO hit effect — fires at the hit, not the victory screen) ---
RED_PIXEL_THRESHOLD_R  = 180   # minimum red channel value
RED_PIXEL_THRESHOLD_GB = 110   # maximum green/blue channel value (110 catches orange-red bursts)
RED_PIXEL_RATIO        = 0.13  # fraction of red pixels required to trigger
RED_KO_OFFSET_SEC      = 0.5   # red flash fires at the hit — small offset
MIN_RED_FLASH_SEC      = 0.3
MAX_RED_FLASH_SEC      = 1.8
RED_MERGE_WINDOW_SEC   = 10.0  # red event within this many seconds of a white event = same KO


def _fmt_ts(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _cache_path(video_path):
    base = os.path.splitext(video_path)[0]
    return base + "_ko_cache.json"


def _load_cache(video_path, log_fn=print):
    path = _cache_path(video_path)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                events = json.load(f)
            if not events:
                log_fn("⚠️  Cache is empty, re-scanning...")
                return None
            log_fn(f"✅  Loaded {len(events)} KO event(s) from cache — skipping scan.")
            return events
        except Exception as e:
            log_fn(f"⚠️  Cache read failed ({e}), re-scanning...")
    return None


def _save_cache(video_path, events, log_fn=print):
    path = _cache_path(video_path)
    try:
        with open(path, 'w') as f:
            json.dump(events, f, indent=2)
        log_fn(f"💾  KO events cached.")
    except Exception as e:
        log_fn(f"⚠️  Could not save cache: {e}")


def dump_frame_at(video_path, target_sec, out_path="debug_frame.png", log_fn=print):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    target_frame = int(target_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()
    if ret:
        cv2.imwrite(out_path, frame)
        log_fn(f"🖼  Frame at {target_sec}s saved to {out_path}")
    else:
        log_fn(f"❌  Could not extract frame at {target_sec}s")


def detect_ko_events(video_path, force_rescan=False, log_fn=print, max_scan_sec=None, start_scan_sec=None):
    if not force_rescan:
        cached = _load_cache(video_path, log_fn)
        if cached is not None:
            return cached

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    log_fn(f"📹  Video: {duration_sec:.1f}s at {fps:.1f} FPS ({total_frames} frames)")

    if start_scan_sec is not None:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_scan_sec * 1000)
        log_fn(f"⏩  Seeking to {_fmt_ts(start_scan_sec)} before scan...")

    log_fn(f"🔎  Scanning every {FRAME_SKIP} frames for KO flashes...")

    ko_events = []
    in_flash = False
    flash_start_pts = 0.0
    in_red_flash = False
    red_flash_start_pts = 0.0
    red_flash_end_pts = 0.0
    red_events = []
    frame_num = 0
    last_log_frame = 0
    consecutive_failures = 0
    baseline_window = deque(maxlen=ROLLING_WINDOW)

    while cap.isOpened():
        if frame_num % FRAME_SKIP == 0:
            ret, frame = cap.read()
        else:
            ret = cap.grab()
            frame = None
        if not ret:
            consecutive_failures += 1
            if consecutive_failures > 30:
                log_fn(f"⚠️  Too many consecutive read failures at {_fmt_ts(cap.get(cv2.CAP_PROP_POS_MSEC)/1000)} — stopping scan.")
                break
            frame_num += 1
            continue
        consecutive_failures = 0

        current_pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        if frame is not None:
            small = cv2.resize(frame, (SCAN_RESIZE_W, SCAN_RESIZE_W * frame.shape[0] // frame.shape[1]))
            # Full-width horizontal band through the middle of the frame.
            # Avoids top/bottom HUD. Works regardless of black sidebars or logo position.
            h, w = small.shape[:2]
            vy0, vy1 = int(h * 0.30), int(h * 0.70)
            sample = small[vy0:vy1, :].reshape(-1, 3)
            min_ch = np.min(sample, axis=1)
            max_ch = np.max(sample, axis=1)
            is_white = (min_ch >= BRIGHT_PIXEL_THRESHOLD) & ((max_ch - min_ch) <= BRIGHT_PIXEL_SPREAD)
            white_ratio = np.mean(is_white)

            # Red sample uses outer thirds only — center has characters/smoke that dilute the ratio
            w3 = w // 3
            red_sample = np.concatenate([
                small[vy0:vy1, :w3].reshape(-1, 3),
                small[vy0:vy1, 2*w3:].reshape(-1, 3)
            ])

            baseline = np.mean(baseline_window) if len(baseline_window) >= 5 else 0.0
            is_flash_frame = white_ratio >= BRIGHT_PIXEL_RATIO and (white_ratio - baseline) >= FLASH_SPIKE
            if not in_flash:
                baseline_window.append(white_ratio)

            if is_flash_frame:
                if not in_flash:
                    in_flash = True
                    flash_start_pts = current_pts
            else:
                if in_flash:
                    flash_duration_sec = current_pts - flash_start_pts
                    if MIN_FLASH_DURATION_SEC <= flash_duration_sec <= MAX_FLASH_DURATION_SEC:
                        ko_timestamp = max(0, flash_start_pts - KO_OFFSET_SEC)
                        ko_events.append({
                            'ko_timestamp': ko_timestamp,
                            'victory_flash_timestamp': flash_start_pts,
                            'flash_duration_seconds': flash_duration_sec,
                        })
                        log_fn(f"  ⚡  KO detected at {_fmt_ts(ko_timestamp)} (flash: {flash_duration_sec:.2f}s)")
                    elif flash_duration_sec > MAX_FLASH_DURATION_SEC:
                        log_fn(f"  ⏭️  Flash too long ({flash_duration_sec:.2f}s) at {_fmt_ts(flash_start_pts)} — skipped")
                    in_flash = False

            # --- Red flash check (OpenCV is BGR: index 2=R, 1=G, 0=B) ---
            r_ch = red_sample[:, 2]
            g_ch = red_sample[:, 1]
            b_ch = red_sample[:, 0]
            is_red = (r_ch >= RED_PIXEL_THRESHOLD_R) & (g_ch <= RED_PIXEL_THRESHOLD_GB) & (b_ch <= RED_PIXEL_THRESHOLD_GB)
            red_ratio = np.mean(is_red)

            is_red_flash_frame = red_ratio >= RED_PIXEL_RATIO
            in_cooldown = (current_pts - red_flash_end_pts) < MIN_RED_FLASH_SEC

            if is_red_flash_frame and not in_cooldown:
                if not in_red_flash:
                    in_red_flash = True
                    red_flash_start_pts = current_pts
            else:
                if in_red_flash:
                    red_duration = current_pts - red_flash_start_pts
                    if MIN_RED_FLASH_SEC <= red_duration <= MAX_RED_FLASH_SEC:
                        red_events.append({
                            'flash_start': red_flash_start_pts,
                            'flash_duration': red_duration,
                        })
                    in_red_flash = False
                    red_flash_end_pts = current_pts

        frame_num += 1
        if max_scan_sec is not None and current_pts > max_scan_sec:
            log_fn(f"  ⏹️  Scan limit reached ({max_scan_sec}s) — stopping early.")
            break
        if frame_num - last_log_frame >= SCAN_LOG_INTERVAL:
            pct = (frame_num / total_frames) * 100
            elapsed_min = int(current_pts // 60)
            elapsed_s = current_pts % 60
            log_fn(f"  📊  Scanning... {pct:.0f}% ({elapsed_min}m {elapsed_s:.0f}s scanned)")
            last_log_frame = frame_num

    cap.release()

    # Merge red flash events that have no nearby white flash (player-cam cutaway cases)
    for red in red_events:
        has_nearby_white = any(
            abs(w['victory_flash_timestamp'] - red['flash_start']) <= RED_MERGE_WINDOW_SEC
            for w in ko_events
        )
        if not has_nearby_white:
            ko_ts = max(0, red['flash_start'] - RED_KO_OFFSET_SEC)
            log_fn(f"  🔴  KO detected via red flash at {_fmt_ts(ko_ts)} (flash: {red['flash_duration']:.2f}s)")
            ko_events.append({
                'ko_timestamp': ko_ts,
                'victory_flash_timestamp': red['flash_start'],
                'flash_duration_seconds': red['flash_duration'],
            })

    ko_events.sort(key=lambda e: e['ko_timestamp'])

    log_fn(f"✅  Scan complete — {len(ko_events)} KO event(s) found.")
    _save_cache(video_path, ko_events, log_fn)
    return ko_events


def run_ffmpeg(cmd, clip_label, log_fn=print):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT
        )
        if result.returncode != 0:
            log_fn(f"  ⚠️  FFmpeg error on {clip_label}:")
            log_fn(result.stderr.decode(errors='replace')[-400:])
            return False
        return True
    except subprocess.TimeoutExpired:
        log_fn(f"  ⚠️  FFmpeg timed out after {FFMPEG_TIMEOUT}s on {clip_label} — skipping.")
        return False


def cut_clips(video_path, ko_events, output_dir="clips", log_fn=print):
    os.makedirs(output_dir, exist_ok=True)
    vertical_dir = os.path.join(output_dir, "vertical")
    original_dir = os.path.join(output_dir, "original")
    os.makedirs(vertical_dir, exist_ok=True)
    os.makedirs(original_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    out_width  = 1080
    out_height = 1920
    fg_width   = 1080
    fg_height  = int(1080 * src_height / src_width)
    fg_height  = fg_height if fg_height % 2 == 0 else fg_height - 1
    fg_y       = (out_height - fg_height) // 2

    blur_filter = (
        f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
        f"crop={out_width}:{out_height},"
        f"boxblur={BLUR_STRENGTH}:{BLUR_STRENGTH}[bg];"
        f"[0:v]scale={fg_width}:{fg_height}[fg];"
        f"[bg][fg]overlay=0:{fg_y}"
    )

    log_fn(f"✂️  Cutting {len(ko_events)} clip(s)  |  source {src_width}x{src_height}  →  canvas {out_width}x{out_height}")

    for i, event in enumerate(ko_events):
        start = max(0, event['ko_timestamp'] - CLIP_BEFORE_SEC)
        duration = CLIP_BEFORE_SEC + CLIP_AFTER_SEC

        ko_ts = event['ko_timestamp']
        ko_mins = int(ko_ts // 60)
        ko_secs = ko_ts % 60
        clip_name = f"clip_{i+1}_{ko_mins}m{int(ko_secs)}s"

        vertical_path = os.path.join(vertical_dir, f"{clip_name}_vertical.mp4")
        original_path = os.path.join(original_dir, f"{clip_name}_original.mp4")

        log_fn(f"\n  [{i+1}/{len(ko_events)}]  Game {i+1}  @  {_fmt_ts(ko_ts)}")
        log_fn(f"    🎬  Rendering vertical (9:16)...")

        vertical_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-filter_complex", blur_filter,
            "-c:v", "libx264", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "30M",
            "-profile:v", "high", "-level:v", "4.2",
            "-g", "30", "-keyint_min", "30",
            "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
            "-movflags", "+faststart",
            vertical_path,
        ]

        original_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "30M",
            "-profile:v", "high", "-level:v", "4.2",
            "-g", "30", "-keyint_min", "30",
            "-preset", "slow", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
            "-movflags", "+faststart",
            original_path,
        ]

        v_ok = run_ffmpeg(vertical_cmd, f"{clip_name}_vertical", log_fn)
        if v_ok:
            log_fn(f"    ✅  Vertical done.")
            thumb_path = os.path.join(vertical_dir, f"{clip_name}_thumb.jpg")
            if not os.path.exists(thumb_path):
                run_ffmpeg([
                    "ffmpeg", "-y",
                    "-ss", str(5),
                    "-i", vertical_path,
                    "-vframes", "1",
                    "-q:v", "4",
                    thumb_path,
                ], f"{clip_name}_thumb", log_fn)
        log_fn(f"    🎬  Rendering original (16:9)...")
        o_ok = run_ffmpeg(original_cmd, f"{clip_name}_original", log_fn)
        if o_ok:
            log_fn(f"    ✅  Original done.")
        if not v_ok and not o_ok:
            log_fn(f"    ❌  Both outputs failed for clip {i+1}.")

    log_fn(f"\n✅  All clips saved to '{output_dir}/'")


def cut_manual_clip(video_path, start_sec, end_sec, output_dir, clip_name, log_fn=print):
    """Cut a clip with explicit start/end timestamps — vertical (9:16) + original (16:9)."""
    cap = cv2.VideoCapture(video_path)
    src_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if not src_width or not src_height:
        log_fn("❌  Could not read VOD dimensions.")
        return False

    duration = round(end_sec - start_sec, 3)

    out_width  = 1080
    out_height = 1920
    fg_width   = 1080
    fg_height  = int(1080 * src_height / src_width)
    fg_height  = fg_height if fg_height % 2 == 0 else fg_height - 1
    fg_y       = (out_height - fg_height) // 2

    blur_filter = (
        f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
        f"crop={out_width}:{out_height},"
        f"boxblur={BLUR_STRENGTH}:{BLUR_STRENGTH}[bg];"
        f"[0:v]scale={fg_width}:{fg_height}[fg];"
        f"[bg][fg]overlay=0:{fg_y}"
    )

    vert_dir = os.path.join(output_dir, "vertical")
    orig_dir = os.path.join(output_dir, "original")
    os.makedirs(vert_dir, exist_ok=True)
    os.makedirs(orig_dir, exist_ok=True)

    vert_path = os.path.join(vert_dir, f"{clip_name}_vertical.mp4")
    orig_path = os.path.join(orig_dir, f"{clip_name}_original.mp4")

    clips_meta_path = os.path.join(output_dir, "clips_meta.json")
    clips_meta = {}
    if os.path.exists(clips_meta_path):
        try:
            with open(clips_meta_path) as f:
                clips_meta = json.load(f)
        except Exception:
            pass
    clips_meta[clip_name] = {"start_sec": start_sec, "end_sec": end_sec}
    try:
        with open(clips_meta_path, "w") as f:
            json.dump(clips_meta, f, indent=2)
    except Exception as e:
        log_fn(f"⚠️  Could not save clips_meta: {e}")

    log_fn(f"✂️  Manual clip: {_fmt_ts(start_sec)} → {_fmt_ts(end_sec)} ({duration:.1f}s)")
    log_fn(f"🎬  Rendering vertical (9:16)...")
    v_ok = run_ffmpeg([
        "ffmpeg", "-y",
        "-ss", str(start_sec), "-i", video_path,
        "-t", str(duration),
        "-filter_complex", blur_filter,
        "-c:v", "libx264", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "30M",
        "-profile:v", "high", "-level:v", "4.2",
        "-g", "30", "-keyint_min", "30",
        "-preset", "slow", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
        "-movflags", "+faststart",
        vert_path,
    ], f"{clip_name}_vertical", log_fn)
    if v_ok:
        log_fn("✅  Vertical done.")
        thumb_path = os.path.join(vert_dir, f"{clip_name}_thumb.jpg")
        run_ffmpeg([
            "ffmpeg", "-y", "-ss", "5", "-i", vert_path,
            "-vframes", "1", "-q:v", "4", thumb_path,
        ], f"{clip_name}_thumb", log_fn)

    log_fn(f"🎬  Rendering original (16:9)...")
    o_ok = run_ffmpeg([
        "ffmpeg", "-y",
        "-ss", str(start_sec), "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "30M",
        "-profile:v", "high", "-level:v", "4.2",
        "-g", "30", "-keyint_min", "30",
        "-preset", "slow", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
        "-movflags", "+faststart",
        orig_path,
    ], f"{clip_name}_original", log_fn)
    if o_ok:
        log_fn("✅  Original done.")

    return v_ok or o_ok


def upscale_to_4k(input_path, output_path, log_fn=print):
    """Upscale a 1080x1920 clip to 2160x3840 — forces YouTube to serve high-quality 1080p."""
    import shutil
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vf', 'scale=2160:3840:flags=lanczos',
            '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            tmp_path,
        ]
        log_fn("⬆️  Upscaling to 4K (2160×3840)...")
        ok = run_ffmpeg(cmd, 'upscale_4k', log_fn)
        if ok:
            shutil.move(tmp_path, output_path)
            log_fn("✅  4K upscale done.")
        return ok
    except Exception as e:
        log_fn(f"❌  upscale_to_4k: {e}")
        return False
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def cut_extended_vertical(video_path, ko_timestamp, extend_sec, output_path, log_fn=print, fg_zoom=1.0, explicit_start=None, base_duration=None, zoom_end_mode="none", zoom_end_sec=0.0):
    cap = cv2.VideoCapture(video_path)
    src_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if not src_width or not src_height:
        log_fn("❌  Could not read VOD dimensions for extended cut.")
        return False

    out_width  = 1080
    out_height = 1920

    fg_base_h = int(out_width * src_height / src_width)
    fg_base_h = fg_base_h if fg_base_h % 2 == 0 else fg_base_h - 1

    fg_height = int(fg_base_h * fg_zoom)
    fg_height = fg_height if fg_height % 2 == 0 else fg_height - 1
    fg_width  = int(fg_height * src_width / src_height)
    fg_width  = fg_width if fg_width % 2 == 0 else fg_width - 1
    fg_y      = (out_height - fg_height) // 2

    if explicit_start is not None:
        start    = explicit_start
        duration = (base_duration or (CLIP_BEFORE_SEC + CLIP_AFTER_SEC)) + extend_sec
    else:
        start    = max(0, ko_timestamp - CLIP_BEFORE_SEC)
        duration = CLIP_BEFORE_SEC + CLIP_AFTER_SEC + extend_sec

    use_dynamic = (fg_zoom > 1.0
                   and zoom_end_mode in ("zoom_out", "pan_left", "pan_right")
                   and zoom_end_sec > 0)

    if use_dynamic:
        lerp_start = max(0.0, duration - zoom_end_sec)
        # t_frac: 0.0 at lerp_start, 1.0 at clip end — avoids min/max commas in filter expressions
        t_frac = (
            f"if(lt(t,{lerp_start}),0.0,"
            f"if(gt(t,{duration}),1.0,"
            f"(t-{lerp_start})/{zoom_end_sec}))"
        )

        if zoom_end_mode == "zoom_out":
            aspect  = src_width / src_height
            z_delta = 1.0 - fg_zoom  # negative — zooming out
            z_expr  = f"({fg_zoom}+{z_delta}*({t_frac}))"
            fw_expr = f"trunc({fg_base_h}*{aspect}*({z_expr})/2)*2"
            fh_expr = f"trunc({fg_base_h}*({z_expr})/2)*2"
            ox_expr = f"({out_width}-({fw_expr}))/2"
            oy_expr = f"({out_height}-({fh_expr}))/2"
        else:  # pan_left or pan_right
            ox_center = (out_width - fg_width) // 2
            if zoom_end_mode == "pan_left":
                ox_expr = f"({ox_center}*(1-({t_frac})))"
            else:
                ox_expr = f"({ox_center}*(1+({t_frac})))"

    zoom_note = f"  zoom={fg_zoom}x" if fg_zoom > 1.0 else ""
    if use_dynamic:
        zoom_note += f"  → {zoom_end_mode.replace('_', ' ')} over {zoom_end_sec}s"
    log_fn(f"⏱️  Cutting {duration}s from VOD...{zoom_note}")

    bg_in   = "[0:v]"
    fg_in   = "[0:v]"
    out_tag = ""

    if use_dynamic:
        if zoom_end_mode == "zoom_out":
            fg_part = f"{fg_in}scale=w={fw_expr}:h={fh_expr}:eval=frame[fg]"
            overlay = f"[bg][fg]overlay={ox_expr}:{oy_expr}:eval=frame{out_tag}"
        else:
            fg_part = f"{fg_in}scale={fg_width}:{fg_height}[fg]"
            overlay = f"[bg][fg]overlay={ox_expr}:{fg_y}:eval=frame{out_tag}"
        inner = (
            f"{bg_in}scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
            f"crop={out_width}:{out_height},"
            f"boxblur={BLUR_STRENGTH}:{BLUR_STRENGTH}[bg];"
            f"{fg_part};"
            f"{overlay}"
        )
    else:
        if fg_zoom > 1.0:
            crop_x  = (fg_width - out_width) // 2
            fg_part = f"{fg_in}scale={fg_width}:{fg_height},crop={out_width}:{fg_height}:{crop_x}:0[fg]"
        else:
            fg_part = f"{fg_in}scale={fg_width}:{fg_height}[fg]"
        inner = (
            f"{bg_in}scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
            f"crop={out_width}:{out_height},"
            f"boxblur={BLUR_STRENGTH}:{BLUR_STRENGTH}[bg];"
            f"{fg_part};"
            f"[bg][fg]overlay=0:{fg_y}{out_tag}"
        )

    blur_filter = inner

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-filter_complex", blur_filter,
        "-c:v", "libx264", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "30M",
        "-profile:v", "high", "-level:v", "4.2",
        "-g", "30", "-keyint_min", "30",
        "-preset", "slow", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "384k", "-ar", "48000",
        "-movflags", "+faststart",
        output_path,
    ]

    return run_ffmpeg(cmd, "extended_vertical", log_fn)
