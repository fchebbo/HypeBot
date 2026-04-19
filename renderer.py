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


def render_with_text(clip_path, above_text, below_text, output_path, log_fn=print):
    cap    = cv2.VideoCapture(clip_path)
    clip_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    clip_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
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

    cmd = [
        'ffmpeg', '-y',
        '-i', clip_path,
        '-i', tmp_path,
        '-filter_complex', '[0:v][1:v]overlay=0:0',
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-preset', 'fast',
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
