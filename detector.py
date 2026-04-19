import cv2
import numpy as np
import subprocess
import os
import json

# --- Tunable constants ---
BRIGHTNESS_THRESHOLD = 220
MIN_FLASH_DURATION_SEC = 0.3
FRAME_SKIP = 2
KO_OFFSET_SEC = 6.0
CLIP_BEFORE_SEC = 10.0
CLIP_AFTER_SEC = 3.0
FFMPEG_TIMEOUT = 120

# --- Blur background tuning ---
BLUR_STRENGTH = 20      # Higher = more blurred background (10-30 recommended)


def _cache_path(video_path):
    base = os.path.splitext(video_path)[0]
    return base + "_ko_cache.json"


def _load_cache(video_path):
    path = _cache_path(video_path)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                events = json.load(f)
            if not events:
                print("⚠️  Cache is empty, re-scanning...")
                return None
            print(f"✅ Loaded {len(events)} KO event(s) from cache — skipping scan.")
            return events
        except Exception as e:
            print(f"⚠️  Cache read failed ({e}), re-scanning...")
    return None


def _save_cache(video_path, events):
    path = _cache_path(video_path)
    try:
        with open(path, 'w') as f:
            json.dump(events, f, indent=2)
        print(f"💾 KO events cached to: {path}")
    except Exception as e:
        print(f"⚠️  Could not save cache: {e}")


def detect_ko_events(video_path, force_rescan=False):
    if not force_rescan:
        cached = _load_cache(video_path)
        if cached is not None:
            return cached

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    print(f"Video loaded: {duration_sec:.1f}s total at {fps:.1f} FPS")
    print(f"Scanning every {FRAME_SKIP} frames ({total_frames // FRAME_SKIP} samples)...\n")

    ko_events = []
    in_flash = False
    flash_start_frame = 0
    frame_num = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_num % FRAME_SKIP == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = np.mean(gray)

            if brightness >= BRIGHTNESS_THRESHOLD:
                if not in_flash:
                    in_flash = True
                    flash_start_frame = frame_num
            else:
                if in_flash:
                    flash_duration_sec = (frame_num - flash_start_frame) / fps
                    if flash_duration_sec >= MIN_FLASH_DURATION_SEC:
                        victory_timestamp = flash_start_frame / fps
                        ko_timestamp = max(0, victory_timestamp - KO_OFFSET_SEC)
                        ko_events.append({
                            'ko_timestamp': ko_timestamp,
                            'victory_flash_timestamp': victory_timestamp,
                            'flash_duration_seconds': flash_duration_sec,
                        })
                    in_flash = False

        frame_num += 1
        if frame_num % 1000 == 0:
            pct = (frame_num / total_frames) * 100
            print(f"  Scanning... {frame_num}/{total_frames} frames ({pct:.0f}%)")

    cap.release()

    print(f"\n{'='*50}")
    print(f"CONFIRMED KO EVENTS: {len(ko_events)}")
    print(f"{'='*50}")

    for i, event in enumerate(ko_events):
        ko_mins = int(event['ko_timestamp'] // 60)
        ko_secs = event['ko_timestamp'] % 60
        print(f"  [{i+1}] KO at {ko_mins}m {ko_secs:.1f}s  |  flash duration: {event['flash_duration_seconds']:.2f}s")

    _save_cache(video_path, ko_events)
    return ko_events


def run_ffmpeg(cmd, clip_label):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT
        )
        if result.returncode != 0:
            print(f"  ⚠️  FFmpeg error on {clip_label}:")
            print(result.stderr.decode(errors='replace'))
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  FFmpeg timed out after {FFMPEG_TIMEOUT}s on {clip_label} — skipping.")
        return False


def cut_clips(video_path, ko_events, output_dir="clips"):
    """
    Two separate FFmpeg calls per clip:
      - vertical/  → 9:16 with blurred background + sharp gameplay overlay
      - original/  → straight 16:9 re-encode
    """
    os.makedirs(output_dir, exist_ok=True)
    vertical_dir = os.path.join(output_dir, "vertical")
    original_dir = os.path.join(output_dir, "original")
    os.makedirs(vertical_dir, exist_ok=True)
    os.makedirs(original_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    src_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # 9:16 canvas dimensions
    out_height = src_height
    out_width = int(src_height * 9 / 16)
    out_width = out_width if out_width % 2 == 0 else out_width - 1
    out_height = out_height if out_height % 2 == 0 else out_height - 1

    # Foreground: scale full frame to fit canvas width, preserve aspect ratio
    fg_width = out_width
    fg_height = int(out_width * src_height / src_width)
    fg_height = fg_height if fg_height % 2 == 0 else fg_height - 1

    # Vertical offset to center foreground on canvas
    fg_y = (out_height - fg_height) // 2

    # FFmpeg filtergraph:
    # [bg]  = source scaled to fill full 9:16 canvas + heavily blurred
    # [fg]  = source scaled to fit width, sharp
    # overlay fg centered on bg
    blur_filter = (
        f"[0:v]scale={out_width}:{out_height}:force_original_aspect_ratio=increase,"
        f"crop={out_width}:{out_height},"
        f"boxblur={BLUR_STRENGTH}:{BLUR_STRENGTH}[bg];"
        f"[0:v]scale={fg_width}:{fg_height}[fg];"
        f"[bg][fg]overlay=0:{fg_y}"
    )

    print(f"\nSource: {src_width}x{src_height}")
    print(f"9:16 canvas: {out_width}x{out_height}")
    print(f"Foreground: {fg_width}x{fg_height} at y={fg_y}")
    print(f"Blur strength: {BLUR_STRENGTH}")
    print(f"Cutting {len(ko_events)} clip(s)...\n")

    for i, event in enumerate(ko_events):
        start = max(0, event['ko_timestamp'] - CLIP_BEFORE_SEC)
        duration = CLIP_BEFORE_SEC + CLIP_AFTER_SEC

        ko_mins = int(event['ko_timestamp'] // 60)
        ko_secs = event['ko_timestamp'] % 60
        clip_name = f"clip_{i+1}_{ko_mins}m{int(ko_secs)}s"

        vertical_path = os.path.join(vertical_dir, f"{clip_name}_vertical.mp4")
        original_path = os.path.join(original_dir, f"{clip_name}_original.mp4")

        print(f"  Clip {i+1}: {ko_mins}m {ko_secs:.1f}s...")

        vertical_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-filter_complex", blur_filter,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            vertical_path,
        ]

        original_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            original_path,
        ]

        v_ok = run_ffmpeg(vertical_cmd, f"{clip_name}_vertical")
        o_ok = run_ffmpeg(original_cmd, f"{clip_name}_original")

        if v_ok:
            print(f"    vertical → {vertical_path}")
        if o_ok:
            print(f"    original → {original_path}")
        if not v_ok and not o_ok:
            print(f"    ❌ Both outputs failed for clip {i+1}")

    print(f"\nDone! Clips saved to '{output_dir}/'")