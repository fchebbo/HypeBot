import cv2
import numpy as np
import subprocess
import os
import json
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


def detect_ko_events(video_path, force_rescan=False, log_fn=print, max_scan_sec=None):
    if not force_rescan:
        cached = _load_cache(video_path, log_fn)
        if cached is not None:
            return cached

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    log_fn(f"📹  Video: {duration_sec:.1f}s at {fps:.1f} FPS ({total_frames} frames)")
    log_fn(f"🔎  Scanning every {FRAME_SKIP} frames for KO flashes...")

    ko_events = []
    in_flash = False
    flash_start_pts = 0.0
    frame_num = 0
    last_log_frame = 0
    baseline_window = deque(maxlen=ROLLING_WINDOW)

    while cap.isOpened():
        if frame_num % FRAME_SKIP == 0:
            ret, frame = cap.read()
        else:
            ret = cap.grab()
            frame = None
        if not ret:
            break

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

    out_height = src_height
    out_width = int(src_height * 9 / 16)
    out_width = out_width if out_width % 2 == 0 else out_width - 1
    out_height = out_height if out_height % 2 == 0 else out_height - 1

    fg_width = out_width
    fg_height = int(out_width * src_height / src_width)
    fg_height = fg_height if fg_height % 2 == 0 else fg_height - 1
    fg_y = (out_height - fg_height) // 2

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
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "ultrafast",
            vertical_path,
        ]

        original_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "ultrafast",
            original_path,
        ]

        v_ok = run_ffmpeg(vertical_cmd, f"{clip_name}_vertical", log_fn)
        if v_ok:
            log_fn(f"    ✅  Vertical done.")
        log_fn(f"    🎬  Rendering original (16:9)...")
        o_ok = run_ffmpeg(original_cmd, f"{clip_name}_original", log_fn)
        if o_ok:
            log_fn(f"    ✅  Original done.")
        if not v_ok and not o_ok:
            log_fn(f"    ❌  Both outputs failed for clip {i+1}.")

    log_fn(f"\n✅  All clips saved to '{output_dir}/'")
