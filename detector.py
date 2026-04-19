import cv2
import numpy as np
import subprocess
import os

# --- Tunable constants ---
BRIGHTNESS_THRESHOLD = 220      # Min average brightness to count as a white flash
MIN_FLASH_DURATION_SEC = 0.3    # Ignore white flashes shorter than this (filters character select)
FRAME_SKIP = 2                  # Analyze every Nth frame (2 = 2x faster, still catches 0.7s+ flashes)
KO_OFFSET_SEC = 6.0             # How many seconds before the victory flash the KO actually landed
CLIP_BEFORE_SEC = 10.0          # How many seconds before the KO to start the clip
CLIP_AFTER_SEC = 3.0            # How many seconds after the KO to end the clip


def detect_ko_events(video_path):
    """
    Single-pass flash detector. Samples every FRAME_SKIP frames for brightness spikes.
    Filters by flash duration to eliminate character select screen flashes.
    Returns confirmed KO events with timestamps.
    """
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

        # Only analyze every Nth frame
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

    # --- Results ---
    print(f"\n{'='*50}")
    print(f"CONFIRMED KO EVENTS: {len(ko_events)}")
    print(f"{'='*50}")

    for i, event in enumerate(ko_events):
        ko_mins = int(event['ko_timestamp'] // 60)
        ko_secs = event['ko_timestamp'] % 60
        print(f"  [{i+1}] KO at {ko_mins}m {ko_secs:.1f}s  |  flash duration: {event['flash_duration_seconds']:.2f}s")

    return ko_events


def cut_clips(video_path, ko_events, output_dir="clips"):
    """
    Uses FFmpeg to cut a highlight clip around each KO timestamp.
    Clips run from CLIP_BEFORE_SEC before the KO to CLIP_AFTER_SEC after.
    """
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nCutting {len(ko_events)} clip(s) into '{output_dir}/'...\n")

    for i, event in enumerate(ko_events):
        start = max(0, event['ko_timestamp'] - CLIP_BEFORE_SEC)
        duration = CLIP_BEFORE_SEC + CLIP_AFTER_SEC

        ko_mins = int(event['ko_timestamp'] // 60)
        ko_secs = event['ko_timestamp'] % 60
        output_path = f"{output_dir}/clip_{i+1}_{ko_mins}m{int(ko_secs)}s.mp4"

        cmd = [
            "ffmpeg",
            "-y",                        # Overwrite without asking
            "-ss", str(start),           # Seek to start time
            "-i", video_path,            # Input file
            "-t", str(duration),         # Duration to capture
            "-c:v", "libx264",           # Video codec
            "-c:a", "aac",               # Audio codec
            "-preset", "fast",           # Encoding speed
            output_path
        ]

        print(f"  Cutting clip {i+1}: {ko_mins}m {ko_secs:.1f}s...")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  Saved: {output_path}")

    print(f"\nDone! {len(ko_events)} clip(s) saved to '{output_dir}/'")


if __name__ == "__main__":
    downloads = os.listdir("downloads")
    if downloads:
        video_path = f"downloads/{downloads[0]}"
        print(f"Analyzing: {video_path}\n")
        events = detect_ko_events(video_path)
        if events:
            cut_clips(video_path, events)
        else:
            print("No KO events detected.")
    else:
        print("No videos found in downloads folder.")