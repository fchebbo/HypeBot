import cv2
import os
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

FFMPEG_TIMEOUT = 180
STROKE_WIDTH   = 6
TEXT_PADDING   = 40   # horizontal margin from canvas edge
BAR_PADDING    = 28   # vertical margin within each bar

_IMPACT = r'C:\Windows\Fonts\impact.ttf'
_EMOJI  = r'C:\Windows\Fonts\seguiemj.ttf'   # Segoe UI Emoji
_ARIAL  = r'C:\Windows\Fonts\arialbd.ttf'

# Matches emoji and symbol characters
_EMOJI_RE = re.compile(
    r'[\U0001F000-\U0001FFFF'  # Misc Symbols, Emoticons, Supplemental Symbols
    r'\U00002600-\U000027BF'   # Misc Symbols, Dingbats
    r'\U00002B00-\U00002BFF'   # Misc Symbols and Arrows
    r'\U0000FE0F'              # VS-16 (emoji presentation selector)
    r'\U0000200D'              # ZWJ
    r']+'
)


def _load_font(size, emoji=False):
    candidates = [_EMOJI, _ARIAL] if emoji else [_IMPACT, _ARIAL]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _split_segments(text):
    """Split text into [(is_emoji, substr), ...] preserving order."""
    result = []
    last = 0
    for m in _EMOJI_RE.finditer(text):
        if m.start() > last:
            result.append((False, text[last:m.start()]))
        result.append((True, m.group()))
        last = m.end()
    if last < len(text):
        result.append((False, text[last:]))
    return [(is_e, t) for is_e, t in result if t]


def _seg_w(draw, text, font, is_emoji):
    sw = 0 if is_emoji else STROKE_WIDTH
    bb = draw.textbbox((0, 0), text, font=font, stroke_width=sw, anchor='lt')
    return bb[2] - bb[0]


def _line_w(draw, segs, fonts):
    return sum(_seg_w(draw, t, fonts[is_e], is_e) for is_e, t in segs)


def _wrap_lines(draw, text, max_w, fonts):
    """Word-wrap text into lines fitting max_w, emoji-aware."""
    words = text.split()
    lines = []
    current = []

    for word in words:
        trial = current + [word]
        segs  = _split_segments(' '.join(trial))
        if _line_w(draw, segs, fonts) <= max_w or not current:
            current = trial
        else:
            lines.append(' '.join(current))
            current = [word]

    if current:
        lines.append(' '.join(current))

    return lines or [text]


def _bar_regions(clip_w, clip_h):
    """Return (top_bar_bottom, bottom_bar_top) for a 9:16 clip from a 16:9 source."""
    fg_h = int(clip_w * 9 / 16)
    if fg_h % 2 != 0:
        fg_h -= 1
    fg_y = (clip_h - fg_h) // 2
    return fg_y, fg_y + fg_h


def _draw_bar_text(draw, text, clip_w, bar_top, bar_bottom, max_size=120, min_size=24):
    if not text or bar_bottom <= bar_top:
        return

    max_w = clip_w - TEXT_PADDING * 2
    max_h = (bar_bottom - bar_top) - BAR_PADDING * 2
    size  = max_size

    while size >= min_size:
        impact_font = _load_font(size, emoji=False)
        emoji_font  = _load_font(size, emoji=True)
        fonts = {False: impact_font, True: emoji_font}

        lines = _wrap_lines(draw, text, max_w, fonts)

        # Line height from Impact (dominant font)
        lh_bb   = draw.textbbox((0, 0), 'Ag', font=impact_font,
                                stroke_width=STROKE_WIDTH, anchor='lt')
        line_h  = lh_bb[3] - lh_bb[1]
        line_gap = max(4, int(line_h * 0.12))
        total_h  = len(lines) * line_h + (len(lines) - 1) * line_gap

        fits_w = all(
            _line_w(draw, _split_segments(l), fonts) <= max_w
            for l in lines
        )

        if fits_w and total_h <= max_h:
            break

        size -= 4

    # Centre the text block in the bar
    bar_cy = bar_top + (bar_bottom - bar_top) // 2
    y = bar_cy - total_h // 2

    for line in lines:
        segs   = _split_segments(line)
        total_lw = _line_w(draw, segs, fonts)
        x = (clip_w - total_lw) // 2

        for is_emoji, seg_text in segs:
            font = fonts[is_emoji]
            sw   = 0 if is_emoji else STROKE_WIDTH
            draw.text(
                (x, y), seg_text,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=sw,
                stroke_fill=(0, 0, 0, 255) if sw else None,
                anchor='lt',
            )
            x += _seg_w(draw, seg_text, font, is_emoji)

        y += line_h + line_gap


def render_with_text(clip_path, above_text, below_text, output_path, log_fn=print, hook=False, hook_offset=2.8, normalize_audio=False, hook_transition='none', cut_end_sec=0.0, hook_only=False):
    cap        = cv2.VideoCapture(clip_path)
    clip_w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    clip_h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_dur  = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if not clip_w or not clip_h:
        log_fn("❌  Could not read clip dimensions.")
        return False

    log_fn(f"🎨  Compositing text onto {clip_w}x{clip_h} canvas...")

    top_bar_bottom, bottom_bar_top = _bar_regions(clip_w, clip_h)

    overlay = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    if above_text:
        _draw_bar_text(draw, above_text.upper(), clip_w, 0, top_bar_bottom)
    if below_text:
        _draw_bar_text(draw, below_text.upper(), clip_w, bottom_bar_top, clip_h)

    tmp      = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp_path = tmp.name
    tmp.close()
    overlay.save(tmp_path)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    log_fn("🎬  Encoding final clip...")

    if normalize_audio:
        log_fn("🔊  Audio normalization: on (compressor + hard limiter)")

    if hook and hook_only:
        effective_end = round(max(0.1, total_dur - cut_end_sec), 3) if cut_end_sec > 0 else None
        clip_end      = effective_end if effective_end else total_dur
        hook_start    = round(max(0.0, clip_end - hook_offset), 3)
        cut_note      = f" (cut last {cut_end_sec}s)" if effective_end else ""
        log_fn(f"🪝  Hook only: last {hook_offset}s (from {hook_start:.2f}s){cut_note}")

        hv_end  = f":end={effective_end}" if effective_end else ""
        hv_trim = f"[0:v]trim=start={hook_start}{hv_end},setpts=PTS-STARTPTS[hv]"
        ha_trim = f"[0:a]atrim=start={hook_start}{hv_end},asetpts=PTS-STARTPTS[ha]"

        if normalize_audio:
            audio_part = ";[ha]acompressor=threshold=0.063:ratio=15:attack=100:release=800,alimiter=limit=0.65:level=disabled[ca]"
            audio_map  = '[ca]'
        else:
            audio_part = ""
            audio_map  = '[ha]'

        filter_complex = (
            f"{hv_trim};{ha_trim};"
            f"[hv][1:v]overlay=0:0[outv]"
            f"{audio_part}"
        )
        cmd = [
            'ffmpeg', '-y',
            '-i', clip_path,
            '-i', tmp_path,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', audio_map,
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'ultrafast',
            output_path,
        ]

    elif hook:
        effective_end = round(max(0.1, total_dur - cut_end_sec), 3) if cut_end_sec > 0 else None
        clip_end      = effective_end if effective_end else total_dur
        hook_start    = round(max(0.0, clip_end - hook_offset), 3)
        cut_note      = f" (cut last {cut_end_sec}s)" if effective_end else ""
        log_fn(f"🪝  Hook: prepending last {hook_offset}s (from {hook_start:.2f}s){cut_note}")

        hv_end = f":end={effective_end}" if effective_end else ""
        hv_trim = f"[0:v]trim=start={hook_start}{hv_end},setpts=PTS-STARTPTS[hv]"
        ha_trim = f"[0:a]atrim=start={hook_start}{hv_end},asetpts=PTS-STARTPTS[ha]"
        fv_trim = (f"[0:v]trim=end={effective_end},setpts=PTS-STARTPTS[fv]" if effective_end
                   else "[0:v]setpts=PTS-STARTPTS[fv]")
        fa_trim = (f"[0:a]atrim=end={effective_end},asetpts=PTS-STARTPTS[fa]" if effective_end
                   else "[0:a]asetpts=PTS-STARTPTS[fa]")

        if hook_transition and hook_transition != 'none':
            T = 0.5
            xfade_offset = round(max(0.0, hook_offset - T), 3)
            xfade_type   = _XFADE_MAP.get(hook_transition, hook_transition)
            log_fn(f"✨  Transition: {hook_transition} ({T}s)")
            audio_tail = (
                f"[ha][fa]acrossfade=d={T}[ca_pre];[ca_pre]acompressor=threshold=0.063:ratio=15:attack=100:release=800,alimiter=limit=0.65:level=disabled[ca]"
                if normalize_audio else
                f"[ha][fa]acrossfade=d={T}[ca]"
            )
            filter_complex = (
                f"{hv_trim};{ha_trim};{fv_trim};{fa_trim};"
                f"[hv][fv]xfade=transition={xfade_type}:duration={T}:offset={xfade_offset}[cv];"
                f"{audio_tail};"
                f"[cv][1:v]overlay=0:0[outv]"
            )
        else:
            audio_tail = "[ha][fa]concat=n=2:v=0:a=1[ca_pre];[ca_pre]acompressor=threshold=0.063:ratio=15:attack=100:release=800,alimiter=limit=0.65:level=disabled[ca]" if normalize_audio \
                    else "[ha][fa]concat=n=2:v=0:a=1[ca]"
            filter_complex = (
                f"{hv_trim};{ha_trim};{fv_trim};{fa_trim};"
                f"[hv][fv]concat=n=2:v=1:a=0[cv];"
                f"{audio_tail};"
                f"[cv][1:v]overlay=0:0[outv]"
            )
        cmd = [
            'ffmpeg', '-y',
            '-i', clip_path,
            '-i', tmp_path,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', '[ca]',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'ultrafast',
            output_path,
        ]
    else:
        af_args = ['-af', 'acompressor=threshold=0.063:ratio=15:attack=100:release=800,alimiter=limit=0.65:level=disabled'] if normalize_audio else []
        t_args  = ['-t', str(round(max(0.1, total_dur - cut_end_sec), 3))] if cut_end_sec > 0 else []
        cmd = [
            'ffmpeg', '-y',
            '-i', clip_path,
            '-i', tmp_path,
            '-filter_complex', '[0:v][1:v]overlay=0:0',
            '-c:v', 'libx264',
            *af_args,
            '-c:a', 'aac',
            '-preset', 'ultrafast',
            *t_args,
            output_path,
        ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
        if result.returncode != 0:
            log_fn("❌  FFmpeg error: " + result.stderr.decode(errors='replace')[-400:])
            return False
        log_fn("✅  Final clip ready.")
        return True
    except subprocess.TimeoutExpired:
        log_fn("⚠️  FFmpeg timed out.")
        return False
    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def render_replay(
    clip_path,
    top_text,
    replay_text,
    c4_time,
    slowmo_input,
    slowmo_factor,
    zoom_factor,
    crossfade_dur,
    output_path,
    log_fn=print,
    ko_hook=False,
    ko_hook_offset=6.0,
):
    cap       = cv2.VideoCapture(clip_path)
    clip_w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    clip_h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    if not clip_w or not clip_h:
        log_fn("❌  Could not read clip dimensions.")
        return False

    tmp = []

    def _tmp_mp4():
        t = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        t.close()
        tmp.append(t.name)
        return t.name

    def _run(cmd, label):
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0:
            log_fn(f"❌  {label}: " + r.stderr.decode(errors='replace')[-400:])
            return False
        return True

    # Pre-trim to KO hook if requested
    if ko_hook:
        hook_start = round(max(0.0, total_dur - ko_hook_offset), 3)
        log_fn(f"✂️  Trimming to last {ko_hook_offset}s (from {hook_start:.2f}s)...")
        trimmed = _tmp_mp4()
        if not _run([
            'ffmpeg', '-y', '-i', clip_path,
            '-filter_complex',
            f"[0:v]trim=start={hook_start},setpts=PTS-STARTPTS[v];"
            f"[0:a]atrim=start={hook_start},asetpts=PTS-STARTPTS[a]",
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
            trimmed,
        ], "KO hook trim"):
            for f in tmp:
                try: os.unlink(f)
                except: pass
            return False
        clip_path = trimmed
        cap2 = cv2.VideoCapture(clip_path)
        total_dur = cap2.get(cv2.CAP_PROP_FRAME_COUNT) / cap2.get(cv2.CAP_PROP_FPS)
        cap2.release()

    c4_time     = round(min(c4_time, total_dur - 0.1), 3)
    end_b       = round(min(c4_time + slowmo_input, total_dur), 3)
    slowmo_pts  = round(1.0 / slowmo_factor, 4)
    crop_w      = int(clip_w / zoom_factor) & ~1
    crop_h      = int(clip_h / zoom_factor) & ~1
    crop_x      = (clip_w - crop_w) // 2
    crop_y      = (clip_h - crop_h) // 2

    top_bar_bottom, _ = _bar_regions(clip_w, clip_h)

    try:
        # --- Part 1: full clip + top text overlay ---
        log_fn(f"🎨  Creating text overlay...")
        ov = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(ov)
        if top_text:
            _draw_bar_text(draw, top_text.upper(), clip_w, 0, top_bar_bottom)
        ov_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        ov_png.close()
        ov.save(ov_png.name)
        tmp.append(ov_png.name)

        part1 = _tmp_mp4()
        log_fn("🎬  Rendering Part 1 (full clip + text)...")
        if not _run([
            'ffmpeg', '-y',
            '-i', clip_path, '-i', ov_png.name,
            '-filter_complex', '[0:v][1:v]overlay=0:0',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
            part1,
        ], "Part 1"): return False

        # --- Replay Segment A: 0 → c4_time (normal) ---
        segA = _tmp_mp4()
        log_fn(f"🎬  Replay A: 0s → {c4_time}s (normal speed)...")
        if c4_time > 0.05:
            if not _run([
                'ffmpeg', '-y', '-i', clip_path,
                '-filter_complex',
                f"[0:v]trim=start=0:end={c4_time},setpts=PTS-STARTPTS[v];"
                f"[0:a]atrim=start=0:end={c4_time},asetpts=PTS-STARTPTS[a]",
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
                segA,
            ], "Seg A"): return False
        else:
            segA = None  # skip if c4_time is essentially 0

        # --- Replay Segment B: c4_time → end_b (slowmo + zoom) ---
        segB = _tmp_mp4()
        log_fn(f"🎬  Replay B: {c4_time}s → {end_b}s ({slowmo_factor}x speed, {zoom_factor}x zoom)...")
        if not _run([
            'ffmpeg', '-y', '-i', clip_path,
            '-filter_complex',
            f"[0:v]trim=start={c4_time}:end={end_b},setpts={slowmo_pts}*(PTS-STARTPTS),"
            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={clip_w}:{clip_h}[v];"
            f"[0:a]atrim=start={c4_time}:end={end_b},asetpts=PTS-STARTPTS,atempo={slowmo_factor}[a]",
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
            segB,
        ], "Seg B"): return False

        # --- Replay Segment C: end_b → end (normal) ---
        segC = None
        if end_b < total_dur - 0.1:
            segC = _tmp_mp4()
            log_fn(f"🎬  Replay C: {end_b}s → end (normal speed)...")
            if not _run([
                'ffmpeg', '-y', '-i', clip_path,
                '-filter_complex',
                f"[0:v]trim=start={end_b},setpts=PTS-STARTPTS[v];"
                f"[0:a]atrim=start={end_b},asetpts=PTS-STARTPTS[a]",
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
                segC,
            ], "Seg C"): return False

        # --- Concat replay segments ---
        replay = _tmp_mp4()
        concat_f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w')
        segs = [s for s in [segA, segB, segC] if s]
        for s in segs:
            concat_f.write(f"file '{s}'\n")
        concat_path = concat_f.name
        concat_f.close()
        tmp.append(concat_path)

        log_fn("🔗  Joining replay segments...")
        if not _run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_path,
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            replay,
        ], "Replay concat"): return False

        # Apply replay text overlay if provided
        if replay_text:
            ov2 = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 0))
            draw2 = ImageDraw.Draw(ov2)
            _draw_bar_text(draw2, replay_text.upper(), clip_w, 0, top_bar_bottom)
            ov2_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            ov2_png.close()
            ov2.save(ov2_png.name)
            tmp.append(ov2_png.name)
            replay_with_text = _tmp_mp4()
            if not _run([
                'ffmpeg', '-y',
                '-i', replay, '-i', ov2_png.name,
                '-filter_complex', '[0:v][1:v]overlay=0:0',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
                replay_with_text,
            ], "Replay text"): return False
            replay = replay_with_text

        # --- Crossfade Part1 + Replay ---
        log_fn("✨  Applying crossfade transition...")
        cap1  = cv2.VideoCapture(part1)
        dur1  = cap1.get(cv2.CAP_PROP_FRAME_COUNT) / cap1.get(cv2.CAP_PROP_FPS)
        cap1.release()
        offset = round(max(0.0, dur1 - crossfade_dur), 3)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if not _run([
            'ffmpeg', '-y',
            '-i', part1, '-i', replay,
            '-filter_complex',
            f"[0:v][1:v]xfade=transition=fade:duration={crossfade_dur}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={crossfade_dur}[a]",
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ], "Crossfade"): return False

        log_fn("✅  Replay clip ready!")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp:
            try:
                os.unlink(f)
            except Exception:
                pass


def render_stitch(
    clip1_path, clip2_path,
    above1, below1, hook_offset1,
    above2, below2, hook_offset2,
    transition_text,
    output_path,
    log_fn=print,
):
    def _read_clip_info(path):
        cap = cv2.VideoCapture(path)
        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return w, h, dur

    clip_w, clip_h, dur1 = _read_clip_info(clip1_path)
    _,      _,      dur2 = _read_clip_info(clip2_path)

    if not clip_w or not clip_h:
        log_fn("❌  Could not read clip dimensions.")
        return False

    top_bar_bottom, bottom_bar_top = _bar_regions(clip_w, clip_h)

    def _make_overlay(above, below):
        img  = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        if above:
            _draw_bar_text(draw, above.upper(), clip_w, 0, top_bar_bottom)
        if below:
            _draw_bar_text(draw, below.upper(), clip_w, bottom_bar_top, clip_h)
        t = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        t.close()
        img.save(t.name)
        return t.name

    def _make_title_card(text):
        img  = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        _draw_bar_text(draw, text.upper(), clip_w, 0, clip_h, max_size=100)
        t = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        t.close()
        img.save(t.name)
        return t.name

    tmp_pngs = []
    tmp_vids = []

    try:
        log_fn(f"🎨  Compositing overlays  ({clip_w}x{clip_h})...")
        ov1  = _make_overlay(above1, below1);  tmp_pngs.append(ov1)
        ov2  = _make_overlay(above2, below2);  tmp_pngs.append(ov2)
        card = _make_title_card(transition_text); tmp_pngs.append(card)

        def _render_hook(clip_path, overlay_path, offset, label):
            clip_dur = dur1 if label == '1' else dur2
            start    = round(max(0.0, clip_dur - offset), 3)
            t = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
            t.close()
            log_fn(f"🎬  Rendering clip {label} hook ({offset}s from end)...")
            # Use atrim/vtrim so audio and video trim in perfect sync — avoids
            # the brief audio dropout that fast-seek (-ss before -i) causes at boundaries
            fc = (
                f"[0:v]trim=start={start},setpts=PTS-STARTPTS[tv];"
                f"[0:a]atrim=start={start},asetpts=PTS-STARTPTS[ta];"
                f"[tv][1:v]overlay=0:0[v]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-i', clip_path,
                '-i', overlay_path,
                '-filter_complex', fc,
                '-map', '[v]', '-map', '[ta]',
                '-c:v', 'libx264', '-c:a', 'aac',
                '-preset', 'ultrafast', '-r', '30',
                t.name,
            ]
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
            if r.returncode != 0:
                log_fn(f"❌  Clip {label} failed: " + r.stderr.decode(errors='replace')[-400:])
                return None
            return t.name

        h1 = _render_hook(clip1_path, ov1, hook_offset1, '1')
        if not h1: return False
        tmp_vids.append(h1)

        # Title card video (1 second, silent audio)
        log_fn("🎬  Rendering transition card...")
        tc = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
        tc.close()
        cmd_card = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', card,
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-t', '1', '-r', '30',
            '-c:v', 'libx264', '-c:a', 'aac',
            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-shortest',
            tc.name,
        ]
        r = subprocess.run(cmd_card, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0:
            log_fn("❌  Title card failed: " + r.stderr.decode(errors='replace')[-400:])
            return False
        tmp_vids.append(tc.name)

        h2 = _render_hook(clip2_path, ov2, hook_offset2, '2')
        if not h2: return False
        tmp_vids.append(h2)

        # Concat all three
        log_fn("🔗  Stitching clips together...")
        concat_f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w')
        for v in tmp_vids:
            concat_f.write(f"file '{v}'\n")
        concat_path = concat_f.name
        concat_f.close()
        tmp_pngs.append(concat_path)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cmd_cat = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_path,
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ]
        r = subprocess.run(cmd_cat, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0:
            log_fn("❌  Concat failed: " + r.stderr.decode(errors='replace')[-400:])
            return False

        log_fn("✅  Stitch complete!")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp_pngs + tmp_vids:
            try:
                os.unlink(f)
            except Exception:
                pass


# ── Montage ──────────────────────────────────────────────────────────────────

_XFADE_MAP = {'fade': 'fade', 'crossfade': 'dissolve', 'flash': 'fadewhite'}


def _concat_segments(segments, output_path, log_fn):
    """Concatenate pre-extracted segment files.
    Each segment has {path, duration, transition} where transition (ignored for
    segment 0) is the xfade type from the previous segment, or 'cut'."""
    n = len(segments)
    transitions = [s.get('transition', 'cut') for s in segments[1:]]
    T = 0.3

    if all(t == 'cut' for t in transitions):
        inputs = []
        for seg in segments:
            inputs += ['-i', seg['path']]
        filter_str = (
            ''.join(f'[{i}:v][{i}:a]' for i in range(n)) +
            f'concat=n={n}:v=1:a=1[outv][outa]'
        )
        cmd = ['ffmpeg', '-y'] + inputs + [
            '-filter_complex', filter_str,
            '-map', '[outv]', '-map', '[outa]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ]
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
            if r.returncode != 0:
                log_fn("❌  FFmpeg concat error: " + r.stderr.decode(errors='replace')[-400:])
                return False
            return True
        except subprocess.TimeoutExpired:
            log_fn("⚠️  FFmpeg concat timed out.")
            return False

    # Sequential pair-by-pair merging — handles mixed and uniform xfade transitions
    tmp_outs = []
    txt_files = []

    def _tmp():
        p = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        tmp_outs.append(p)
        return p

    try:
        current_path = segments[0]['path']
        current_dur  = segments[0]['duration']

        for k in range(1, n):
            seg      = segments[k]
            tr       = seg.get('transition', 'cut')
            out_path = output_path if k == n - 1 else _tmp()

            if tr == 'cut':
                concat_f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
                concat_f.write(f"file '{current_path}'\n")
                concat_f.write(f"file '{seg['path']}'\n")
                txt_files.append(concat_f.name)
                concat_f.close()
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat', '-safe', '0', '-i', concat_f.name,
                    '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
                    out_path,
                ]
                current_dur = current_dur + seg['duration']
            else:
                xfade_type = _XFADE_MAP.get(tr, tr)
                offset = round(max(0.0, current_dur - T), 3)
                cmd = [
                    'ffmpeg', '-y',
                    '-i', current_path, '-i', seg['path'],
                    '-filter_complex',
                    f"[0:v][1:v]xfade=transition={xfade_type}:duration={T}:offset={offset}[v];"
                    f"[0:a][1:a]acrossfade=d={T}[a]",
                    '-map', '[v]', '-map', '[a]',
                    '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
                    out_path,
                ]
                current_dur = current_dur + seg['duration'] - T

            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
                if r.returncode != 0:
                    log_fn(f"❌  FFmpeg merge [{k}] error: " + r.stderr.decode(errors='replace')[-400:])
                    return False
            except subprocess.TimeoutExpired:
                log_fn(f"⚠️  FFmpeg merge [{k}] timed out.")
                return False

            current_path = out_path

        return True
    finally:
        for f in tmp_outs + txt_files:
            try:
                os.unlink(f)
            except Exception:
                pass


def render_montage(clips_info, top_text, transition, output_path, log_fn=print, logo_path=None, black_top_bar=False):
    """
    clips_info:    list of {path, hook_offset, end_early}
    transition:    'cut' | 'fade' | 'crossfade' | 'flash'
    logo_path:     optional image to fill the bottom bar
    black_top_bar: if True, paint the top bar solid black
    """
    tmp_files = []
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def _tmp():
        p = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
        tmp_files.append(p)
        return p

    try:
        segments = []
        for i, info in enumerate(clips_info):
            cap = cv2.VideoCapture(info['path'])
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
            cap.release()

            hook_offset = float(info.get('hook_offset', 5.0))
            end_early   = float(info.get('end_early', 0.0))
            seg_start   = round(max(0.0, total_dur - hook_offset), 3)
            seg_dur     = round(hook_offset - end_early, 3)

            if seg_dur <= 0:
                log_fn(f"⚠️  Clip {i+1}: end_early >= hook_offset — skipping.")
                continue

            seg_path = _tmp()

            log_fn(f"✂️  [{i+1}/{len(clips_info)}]  hook={hook_offset}s  early={end_early}s  → {seg_start:.2f}s–{seg_start+seg_dur:.2f}s  ({seg_dur:.2f}s)  {os.path.basename(info['path'])}")
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(seg_start),
                '-i', info['path'],
                '-t', str(seg_dur),
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
                seg_path,
            ]
            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
                if r.returncode != 0:
                    log_fn(f"❌  Clip {i+1} extraction failed: " + r.stderr.decode(errors='replace')[-200:])
                    return False
            except subprocess.TimeoutExpired:
                log_fn(f"⚠️  Clip {i+1} extraction timed out.")
                return False
            seg_transition = info.get('transition') or transition
            segments.append({'path': seg_path, 'duration': seg_dur, 'transition': seg_transition})

        if len(segments) < 2:
            log_fn("❌  Need at least 2 valid clips for a montage.")
            return False

        use_logo = bool(logo_path and os.path.exists(logo_path))
        use_text = bool(top_text and top_text.strip())
        use_bars = use_logo or black_top_bar

        # Route: concat → [bars/logo] → [text] → output
        concat_out = _tmp() if (use_bars or use_text) else output_path

        log_fn(f"🎬  Joining {len(segments)} clips with '{transition}' transition...")
        if not _concat_segments(segments, concat_out, log_fn):
            return False

        current = concat_out

        if use_bars:
            cap2 = cv2.VideoCapture(current)
            vid_w = int(cap2.get(cv2.CAP_PROP_FRAME_WIDTH))
            vid_h = int(cap2.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap2.release()

            top_bar_bottom, bottom_bar_top = _bar_regions(vid_w, vid_h)
            bar_h = vid_h - bottom_bar_top

            bars_out = _tmp() if use_text else output_path

            if use_logo and black_top_bar:
                log_fn(f"🖼️  Logo (bottom) + black top bar...")
                filter_str = (
                    f'[1:v]scale={vid_w}:{bar_h}:force_original_aspect_ratio=increase,'
                    f'crop={vid_w}:{bar_h}[logo];'
                    f'[0:v][logo]overlay=0:{bottom_bar_top}[withlogo];'
                    f'[withlogo]drawbox=x=0:y=0:w=iw:h={top_bar_bottom}:color=black:t=fill[outv]'
                )
                cmd = ['ffmpeg', '-y', '-i', current, '-i', logo_path,
                       '-filter_complex', filter_str,
                       '-map', '[outv]', '-map', '0:a',
                       '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', bars_out]
            elif use_logo:
                log_fn(f"🖼️  Filling bottom bar with logo ({vid_w}x{bar_h})...")
                filter_str = (
                    f'[1:v]scale={vid_w}:{bar_h}:force_original_aspect_ratio=increase,'
                    f'crop={vid_w}:{bar_h}[logo];'
                    f'[0:v][logo]overlay=0:{bottom_bar_top}[outv]'
                )
                cmd = ['ffmpeg', '-y', '-i', current, '-i', logo_path,
                       '-filter_complex', filter_str,
                       '-map', '[outv]', '-map', '0:a',
                       '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', bars_out]
            else:
                log_fn(f"⬛  Blacking out top bar...")
                cmd = ['ffmpeg', '-y', '-i', current,
                       '-vf', f'drawbox=x=0:y=0:w=iw:h={top_bar_bottom}:color=black:t=fill',
                       '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', bars_out]

            r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
            if r.returncode != 0:
                log_fn("❌  Bar overlay failed: " + r.stderr.decode(errors='replace')[-400:])
                return False
            current = bars_out

        if use_text:
            log_fn("🎨  Burning top text...")
            if not render_with_text(current, top_text, None, output_path, log_fn=log_fn):
                return False

        log_fn("✅  Montage complete.")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass


# ── Dankify ───────────────────────────────────────────────────────────────────

# Each replay pass: (top_bar_text, xfade_transition_into_this_segment)
_DANKIFY_EFFECTS = [
    # (top_text, xfade_transition_into_this_segment)
    ("HE LANDED",    "dissolve"),
    ("THAT?!?!",  "dissolve"),
]

_FFMPEG_FONT = _IMPACT.replace('\\', '/').replace('C:/', 'C\\:/')


def _run(cmd, label, log_fn):
    """Run an FFmpeg command, log on failure, return success bool."""
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT)
        if r.returncode != 0:
            log_fn(f"❌  {label}: " + r.stderr.decode(errors='replace')[-300:])
            return False
        return True
    except subprocess.TimeoutExpired:
        log_fn(f"⚠️  {label} timed out.")
        return False


def _extract(clip_path, ss, duration, vfilter, aspeed, out_path, label, log_fn):
    """Extract a segment with optional video filter and audio speed."""
    cmd = ['ffmpeg', '-y', '-i', clip_path,
           '-ss', str(round(ss, 3)),
           '-t',  str(round(duration, 3))]
    if vfilter:
        cmd += ['-vf', vfilter]
    if aspeed != 1.0:
        cmd += ['-af', f'atempo={aspeed}']
    cmd += ['-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', out_path]
    return _run(cmd, label, log_fn)


def render_hype_reel(clips_info, title_text, logo_path, output_path, log_fn=print):
    """
    clips_info: list of {path, hook_offset, transition}
    Structure: clip1 hook + fade to black → title card (logo + text, fade in/out)
               → clip2..N hooks with transitions between them.
    """
    tmp_files = []
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def _tmp(suffix='.mp4'):
        p = tempfile.NamedTemporaryFile(suffix=suffix, delete=False).name
        tmp_files.append(p)
        return p

    try:
        cap0   = cv2.VideoCapture(clips_info[0]['path'])
        reel_w = int(cap0.get(cv2.CAP_PROP_FRAME_WIDTH))
        reel_h = int(cap0.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap0.release()

        # ── 1. Extract hook segments ──────────────────────────────────────────
        segments = []
        for i, info in enumerate(clips_info):
            cap       = cv2.VideoCapture(info['path'])
            fps       = cap.get(cv2.CAP_PROP_FPS) or 30
            total_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
            cap.release()

            hook_offset = float(info.get('hook_offset', 5.0))
            seg_start   = round(max(0.0, total_dur - hook_offset), 3)
            seg_dur     = round(min(hook_offset, total_dur), 3)
            seg         = _tmp()

            log_fn(f"✂️  [{i+1}/{len(clips_info)}] {os.path.basename(info['path'])} — last {hook_offset}s")
            if not _run([
                'ffmpeg', '-y',
                '-ss', str(seg_start), '-i', info['path'],
                '-t', str(seg_dur),
                '-vf', f'scale={reel_w}:{reel_h}',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
                seg,
            ], f"extract clip {i+1}", log_fn):
                return False

            segments.append({'path': seg, 'duration': seg_dur, 'transition': info.get('transition', 'flash')})

        # ── 2. Fade to black at end of clip 1 ────────────────────────────────
        log_fn("🎬  Fading opening clip to black...")
        fade_dur = 1.0
        fade_st  = round(max(0.0, segments[0]['duration'] - fade_dur), 3)
        seg1_out = _tmp()
        if not _run([
            'ffmpeg', '-y', '-i', segments[0]['path'],
            '-filter_complex',
            f"[0:v]fade=t=out:st={fade_st}:d={fade_dur}:color=black[v];"
            f"[0:a]afade=t=out:st={fade_st}:d={fade_dur}[a]",
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
            seg1_out,
        ], "clip 1 fadeout", log_fn):
            return False
        segments[0]['path'] = seg1_out

        # ── 3. Title card: logo + text, fade in then fade out ─────────────────
        log_fn(f"🎨  Rendering title card: '{title_text}'...")
        card_dur = 4.0
        fi_dur   = 1.0
        fo_dur   = 1.0

        card_img = Image.new('RGBA', (reel_w, reel_h), (0, 0, 0, 255))
        draw     = ImageDraw.Draw(card_img)

        text_top = reel_h // 3
        if logo_path and os.path.exists(logo_path):
            try:
                logo     = Image.open(logo_path).convert('RGBA')
                max_logo_h = int(reel_h * 0.35)
                scale    = max_logo_h / logo.height
                logo_w   = int(logo.width * scale)
                logo     = logo.resize((logo_w, max_logo_h), Image.LANCZOS)
                logo_x   = (reel_w - logo_w) // 2
                logo_y   = int(reel_h * 0.18)
                card_img.paste(logo, (logo_x, logo_y), logo)
                text_top = logo_y + max_logo_h + 32
            except Exception as e:
                log_fn(f"⚠️  Logo load failed: {e}")

        _draw_bar_text(draw, title_text.upper(), reel_w, text_top, reel_h - int(reel_h * 0.08), max_size=80)

        card_png = _tmp('.png')
        card_img.save(card_png)

        fo_st     = round(card_dur - fo_dur, 3)
        title_vid = _tmp()
        if not _run([
            'ffmpeg', '-y',
            '-loop', '1', '-i', card_png,
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-t', str(card_dur),
            '-vf', f'scale={reel_w}:{reel_h},fade=t=in:st=0:d={fi_dur},fade=t=out:st={fo_st}:d={fo_dur}',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            '-pix_fmt', 'yuv420p', '-shortest', '-r', '30',
            title_vid,
        ], "title card", log_fn):
            return False

        # ── 4. Join clip 2..N with transitions ────────────────────────────────
        remaining = segments[1:]
        if len(remaining) == 0:
            rest_vid = None
        elif len(remaining) == 1:
            rest_vid = remaining[0]['path']
        else:
            rest_vid = _tmp()
            log_fn(f"🔗  Joining {len(remaining)} remaining clips...")
            if not _concat_segments(remaining, rest_vid, log_fn):
                return False

        # ── 5. Final assembly ─────────────────────────────────────────────────
        log_fn("🔗  Assembling final hype reel...")
        concat_f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
        concat_f.write(f"file '{segments[0]['path']}'\n")
        concat_f.write(f"file '{title_vid}'\n")
        if rest_vid:
            concat_f.write(f"file '{rest_vid}'\n")
        concat_path = concat_f.name
        concat_f.close()
        tmp_files.append(concat_path)

        if not _run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_path,
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ], "final assembly", log_fn):
            return False

        log_fn("✅  Hype reel complete!")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass


def render_fade_to_text(clip_path, hook_offset, fade_text, output_path, log_fn=print, top_text=""):
    """
    Play clip from hook_offset seconds before end → fade to black → white text fades in.
    Optional top_text is burned into the top bar of the clip segment.
    """
    cap       = cv2.VideoCapture(clip_path)
    clip_w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    clip_h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps       = cap.get(cv2.CAP_PROP_FPS) or 30
    total_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()

    if not clip_w or not clip_h:
        log_fn("❌  Could not read clip dimensions.")
        return False

    hook_start     = round(max(0.0, total_dur - hook_offset), 3)
    seg_dur        = round(total_dur - hook_start, 3)
    fade_out_dur   = 1.0
    card_dur       = 3.0
    fade_in_dur    = 1.0
    fade_out_start = round(max(0.0, seg_dur - fade_out_dur), 3)

    tmp_files = []

    def _tmp(suffix='.mp4'):
        p = tempfile.NamedTemporaryFile(suffix=suffix, delete=False).name
        tmp_files.append(p)
        return p

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Part 1: clip from hook_start → end with optional top text overlay + fade to black
        log_fn(f"🎬  Extracting last {hook_offset:.1f}s (from {hook_start:.1f}s) with fade to black...")
        part1 = _tmp()

        top_bar_bottom, _ = _bar_regions(clip_w, clip_h)
        ov_png = None
        if top_text:
            log_fn(f"🎨  Adding top text: '{top_text}'")
            ov = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(ov)
            _draw_bar_text(draw, top_text.upper(), clip_w, 0, top_bar_bottom)
            ov_tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            ov_tmp.close()
            ov_png = ov_tmp.name
            tmp_files.append(ov_png)
            ov.save(ov_png)
            filter_complex = (
                f"[0:v]trim=start={hook_start},setpts=PTS-STARTPTS[trimmed];"
                f"[trimmed][1:v]overlay=0:0[overlaid];"
                f"[overlaid]fade=t=out:st={fade_out_start}:d={fade_out_dur}:color=black[v];"
                f"[0:a]atrim=start={hook_start},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={fade_out_start}:d={fade_out_dur}[a]"
            )
            cmd_part1 = [
                'ffmpeg', '-y', '-i', clip_path, '-i', ov_png,
                '-filter_complex', filter_complex,
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
                part1,
            ]
        else:
            filter_complex = (
                f"[0:v]trim=start={hook_start},setpts=PTS-STARTPTS,"
                f"fade=t=out:st={fade_out_start}:d={fade_out_dur}:color=black[v];"
                f"[0:a]atrim=start={hook_start},asetpts=PTS-STARTPTS,"
                f"afade=t=out:st={fade_out_start}:d={fade_out_dur}[a]"
            )
            cmd_part1 = [
                'ffmpeg', '-y', '-i', clip_path,
                '-filter_complex', filter_complex,
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', '-r', '30',
                part1,
            ]

        if not _run(cmd_part1, "fade out", log_fn):
            return False

        # Part 2: black card with white text, fade in
        log_fn(f"🎨  Creating text card: '{fade_text}'...")
        text_png = _tmp('.png')
        img  = Image.new('RGBA', (clip_w, clip_h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)
        _draw_bar_text(draw, fade_text.upper(), clip_w, 0, clip_h, max_size=80)
        img.save(text_png)

        part2 = _tmp()
        if not _run([
            'ffmpeg', '-y',
            '-loop', '1', '-i', text_png,
            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo',
            '-t', str(card_dur),
            '-vf', f'fade=t=in:st=0:d={fade_in_dur}',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            '-pix_fmt', 'yuv420p', '-shortest', '-r', '30',
            part2,
        ], "text card", log_fn):
            return False

        # Concat
        log_fn("🔗  Joining parts...")
        concat_f = tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8')
        concat_f.write(f"file '{part1}'\n")
        concat_f.write(f"file '{part2}'\n")
        concat_path = concat_f.name
        concat_f.close()
        tmp_files.append(concat_path)

        if not _run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_path,
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ], "concat", log_fn):
            return False

        log_fn("✅  Fade to text complete!")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass


def render_dankify(clip_path, hook_start, output_path, log_fn=print):
    """
    Dankify sequence: hook → N replays of the same segment with varied transitions
    and "Montage Time!" burned into the top bar of each replay.
    All timestamps are seconds from the start of the vertical clip.
    """
    tmp_files = []
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        cap = cv2.VideoCapture(clip_path)
        clip_w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        clip_h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps       = cap.get(cv2.CAP_PROP_FPS) or 30
        total_dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
        cap.release()

        if not clip_w or not clip_h:
            log_fn("❌  Could not read clip dimensions.")
            return False

        hook_dur = round(total_dur - hook_start, 3)
        if hook_dur <= 0:
            log_fn("❌  hook_start must be before clip end.")
            return False

        # Top-bar geometry for per-replay text
        fg_h = int(clip_w * 9 / 16)
        fg_h = fg_h if fg_h % 2 == 0 else fg_h - 1
        fg_y = (clip_h - fg_h) // 2

        def _text_vf(text):
            safe = text.replace('\\', '\\\\').replace(':', '\\:')
            return (
                f"drawtext=fontfile='{_FFMPEG_FONT}':text='{safe}'"
                f":x=(w-tw)/2:y=({fg_y}-th)/2"
                f":fontsize=96:fontcolor=white:borderw=5:bordercolor=black"
            )

        def tmp():
            p = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
            tmp_files.append(p)
            return p

        # ── 1. Hook ───────────────────────────────────────────────────────────
        log_fn("🎬  Extracting hook...")
        hook_path = tmp()
        if not _run([
            'ffmpeg', '-y',
            '-ss', str(round(hook_start, 3)), '-i', clip_path,
            '-t', str(round(hook_dur, 3)),
            '-vf', f"setpts=PTS-STARTPTS,{_text_vf('OMG!')}",
            '-af', 'asetpts=PTS-STARTPTS',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', hook_path,
        ], "hook", log_fn):
            return False

        # ── 2. Replay passes ──────────────────────────────────────────────────
        # Each entry: (path, duration, xfade_transition_into_this_seg)
        replay_segs = []
        for i, (top_text, xfade_tr) in enumerate(_DANKIFY_EFFECTS):
            log_fn(f"🎨  Replay {i+1}/{len(_DANKIFY_EFFECTS)}: {top_text}...")
            seg = tmp()
            vf = f"setpts=PTS-STARTPTS,{_text_vf(top_text)}"
            cmd = ['ffmpeg', '-y',
                   '-ss', str(round(hook_start, 3)), '-i', clip_path,
                   '-t',  str(round(hook_dur, 3)),
                   '-vf', vf, '-af', 'asetpts=PTS-STARTPTS',
                   '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast', seg]
            if _run(cmd, top_text, log_fn):
                replay_segs.append((seg, hook_dur, xfade_tr))
            else:
                log_fn(f"⚠️  Skipping {top_text}.")

        if not replay_segs:
            log_fn("❌  All replays failed.")
            return False

        # ── 3. Join with varied xfade transitions ─────────────────────────────
        all_segs  = [(hook_path, hook_dur)] + [(s, d) for s, d, _ in replay_segs]
        xfade_trs = [tr for _, _, tr in replay_segs]  # transition into each replay
        n = len(all_segs)
        T = 0.5  # transition duration in seconds

        log_fn(f"🔗  Joining {n} segments...")
        inputs = []
        for seg, _ in all_segs:
            inputs += ['-i', seg]

        v_parts, a_parts = [], []
        cumulative = 0.0
        for k in range(n - 1):
            src_v = f'[{k}:v]' if k == 0 else f'[xv{k}]'
            src_a = f'[{k}:a]' if k == 0 else f'[xa{k}]'
            out_v = f'[xv{k+1}]'
            out_a = f'[xa{k+1}]'
            cumulative += all_segs[k][1]
            offset = round(max(0.0, cumulative - (k + 1) * T), 3)
            tr = xfade_trs[k]
            v_parts.append(f'{src_v}[{k+1}:v]xfade=transition={tr}:duration={T}:offset={offset}{out_v}')
            a_parts.append(f'{src_a}[{k+1}:a]acrossfade=d={T}{out_a}')

        filter_str = ';'.join(v_parts + a_parts)
        if not _run([
            'ffmpeg', '-y'] + inputs + [
            '-filter_complex', filter_str,
            '-map', f'[xv{n-1}]', '-map', f'[xa{n-1}]',
            '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'ultrafast',
            output_path,
        ], "join", log_fn):
            return False

        log_fn("✅  Dankify complete!")
        return True

    except Exception as e:
        log_fn(f"❌  {e}")
        return False
    finally:
        for f in tmp_files:
            try:
                os.unlink(f)
            except Exception:
                pass
