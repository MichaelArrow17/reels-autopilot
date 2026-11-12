"""Renderer Reels 1080×1920 30 fps: stickman + karaoke caption + audio TTS.

Jalur utama: Python + Pillow + ffmpeg (paling andal di Ubuntu GitHub runner).
Remotion/stickman-story adalah jalur upgrade visual (lihat BLUEPRINT), bukan default,
karena butuh Node+Chrome dan kode TypeScript per video — lebih rapuh untuk 5×/hari otonom.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reels_autopilot.captions import CaptionChunk, chunk_at_time, chunk_captions
from reels_autopilot.config import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_MUTED,
    COLOR_TEXT,
    HARD_MAX_DURATION,
    ROOT,
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    Settings,
    get_settings,
)
from reels_autopilot.providers.tts import TTSResult, Word, normalize_word_timings
from reels_autopilot.stickman import pose_frame

log = logging.getLogger("reels.render")

BG = _hex = tuple(int(COLOR_BG[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore
ACCENT = tuple(int(COLOR_ACCENT[i : i + 2], 16) for i in (1, 3, 5))
TEXT = tuple(int(COLOR_TEXT[i : i + 2], 16) for i in (1, 3, 5))
MUTED = tuple(int(COLOR_MUTED[i : i + 2], 16) for i in (1, 3, 5))


def _font_path(settings: Settings) -> Path:
    candidates = [
        settings.assets_dir / "fonts" / "Inter-VariableFont_opsz,wght.ttf",
        Path("/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("Font Inter/Liberation/DejaVu tidak ditemukan")


def load_font(size: int, weight: int = 400, settings: Settings | None = None) -> ImageFont.FreeTypeFont:
    settings = settings or get_settings()
    path = _font_path(settings)
    font = ImageFont.truetype(str(path), size=size)
    try:
        # Inter variable: opsz 14–32, wght 100–900
        font.set_variation_by_axes([min(32, max(14, size * 0.3)), float(weight)])
    except Exception:
        pass
    return font


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def wrap_words(text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if font.getlength(trial) <= max_w or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def scene_for_time(windows: list[tuple[float, float, dict]], t: float) -> dict:
    for a, b, sc in windows:
        if a <= t < b:
            return sc
    return windows[-1][2] if windows else {}


def build_windows(script: dict, words: list[Word], duration: float) -> list[tuple[float, float, dict]]:
    adegan = list(script.get("adegan") or [])
    if not adegan:
        adegan = [{"id": 1, "pose": "idle", "teks_layar": script.get("hook") or "", "keyword": "", "nama": "full"}]
    n = len(adegan)
    # coba cocokkan narasi adegan ke aliran kata
    full = " ".join(w.word for w in words)
    used = 0.0
    windows = []
    cursor = 0
    for i, sc in enumerate(adegan):
        nar = (sc.get("narasi") or "").strip()
        start = used
        if nar and words:
            # cari token pertama narasi mulai dari cursor
            first = nar.split()[0] if nar.split() else ""
            idx = _find_word(words, first, cursor)
            if idx is not None:
                start = words[idx].start
                cursor = idx + 1
        if i == 0:
            start = 0.0
        windows.append([start, duration, sc])
    # tutup end masing-masing
    for i in range(len(windows) - 1):
        windows[i][1] = max(windows[i][0] + 0.4, windows[i + 1][0])
    if windows:
        windows[-1][1] = duration
        # hook minimal ~2 detik (playbook: karakter tidak fokus di 2 dtk pertama)
        if windows[0][1] < 2.0 and duration > 3:
            # geser sedikit, tapi jangan hancurkan urutan
            pass
    return [(float(a), float(b), sc) for a, b, sc in windows]


def _find_word(words: list[Word], token: str, start: int) -> int | None:
    tok = token.lower().strip(".,!?\"'")
    for i in range(start, len(words)):
        if words[i].word.lower().strip(".,!?\"'") == tok:
            return i
    return None


def make_background(size: tuple[int, int] = (TARGET_WIDTH, TARGET_HEIGHT), photo: Image.Image | None = None) -> Image.Image:
    img = Image.new("RGB", size, _hex_rgb(COLOR_BG))
    dr = ImageDraw.Draw(img, "RGBA")
    w, h = size
    if photo is not None:
        ph = photo.convert("RGB")
        # cover 1080x1920
        scale = max(w / ph.width, h / ph.height)
        nw, nh = int(ph.width * scale), int(ph.height * scale)
        ph = ph.resize((nw, nh), Image.Resampling.LANCZOS)
        left, top = (nw - w) // 2, (nh - h) // 2
        ph = ph.crop((left, top, left + w, top + h))
        ph = ph.filter(ImageFilter.GaussianBlur(12))
        # gelap agar teks tetap terbaca
        overlay = Image.new("RGB", size, _hex_rgb(COLOR_BG))
        img = Image.blend(ph, overlay, 0.62)
        dr = ImageDraw.Draw(img, "RGBA")
    # blob aksen
    for cx, cy, r, col in [
        (180, 220, 260, (*ACCENT, 28)),
        (980, 1700, 320, (40, 90, 150, 40)),
        (540, 800, 180, (*ACCENT, 16)),
    ]:
        blob = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(blob).ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        blob = blob.filter(ImageFilter.GaussianBlur(40))
        img = Image.alpha_composite(img.convert("RGBA"), blob).convert("RGB")
        dr = ImageDraw.Draw(img, "RGBA")
    # titik grid halus
    for x in range(80, w, 80):
        for y in range(80, h, 80):
            dr.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(255, 255, 255, 18))
    # garis lantai
    dr.ellipse((140, 1380, 940, 1500), outline=(*ACCENT, 50), width=3)
    return img.convert("RGB")


def draw_header(dr: ImageDraw.ImageDraw, fonts: dict) -> None:
    dr.text((64, 56), "PO CHAI", font=fonts["brand"], fill=ACCENT)
    # ukur kanan
    label = "KREATOR AI"
    tw = fonts["brand"].getlength(label)
    dr.text((TARGET_WIDTH - 64 - tw, 56), label, font=fonts["brand"], fill=MUTED)
    dr.rectangle((64, 100, TARGET_WIDTH - 64, 104), fill=ACCENT)


def draw_keyword(img: Image.Image, text: str, font: ImageFont.ImageFont, y: int = 280) -> None:
    if not text:
        return
    dr = ImageDraw.Draw(img)
    tw = font.getlength(text)
    x = (TARGET_WIDTH - tw) / 2
    # glow kasar
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        dr.text((x + dx, y + dy), text, font=font, fill=(*ACCENT, 80) if False else ACCENT)
    dr.text((x, y), text, font=font, fill=TEXT)


def draw_karaoke(
    img: Image.Image,
    words: list[Word],
    t: float,
    fonts: dict,
    chunks: list[CaptionChunk] | None = None,
) -> None:
    """Tampilkan SATU chunk stabil (2–4 kata), highlight kata yang sedang diucapkan."""
    if chunks is None and words:
        chunks = chunk_captions(words)
    ch = chunk_at_time(chunks or [], t)
    if not ch:
        return
    hi = ch.highlight_index(t)
    window = ch.words
    font = fonts["caption"]
    font_hi = fonts["caption_hi"]
    max_w = 920
    # bangun baris (chunk pendek: biasanya 1 baris)
    lines: list[list[tuple[str, bool]]] = [[]]
    for i, w in enumerate(window):
        token = w.word
        is_hi = i == hi
        cur = lines[-1]
        trial = " ".join(x[0] for x in cur + [(token, is_hi)])
        if font.getlength(trial) > max_w and cur:
            lines.append([(token, is_hi)])
        else:
            cur.append((token, is_hi))
    box_h = 80 + len(lines) * 64
    box = Image.new("RGBA", (TARGET_WIDTH, box_h + 20), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box)
    margin = 50
    bd.rounded_rectangle(
        (margin, 8, TARGET_WIDTH - margin, box_h),
        radius=24,
        fill=(8, 16, 32, 220),
        outline=(*ACCENT, 180),
        width=3,
    )
    y = 28
    for line in lines:
        # center the line
        widths = []
        for tok, hi in line:
            f = font_hi if hi else font
            widths.append(f.getlength(tok) + 14)
        total = sum(widths)
        x = (TARGET_WIDTH - total) / 2
        for tok, hi in line:
            f = font_hi if hi else font
            color = ACCENT if hi else TEXT
            bd.text((x, y), tok, font=f, fill=color)
            x += (font_hi if hi else font).getlength(tok) + 14
        y += 64
    img.paste(box, (0, 1540), box)


def draw_progress(dr: ImageDraw.ImageDraw, t: float, duration: float) -> None:
    y = TARGET_HEIGHT - 10
    dr.rectangle((0, y, TARGET_WIDTH, TARGET_HEIGHT), fill=(10, 16, 28))
    frac = 0 if duration <= 0 else min(1.0, max(0.0, t / duration))
    dr.rectangle((0, y, int(TARGET_WIDTH * frac), TARGET_HEIGHT), fill=ACCENT)


def draw_hook_frame(img: Image.Image, hook: str, fonts: dict, t: float) -> None:
    dr = ImageDraw.Draw(img)
    draw_header(dr, fonts)
    lines = wrap_words(hook, fonts["hook"], 900)
    total_h = len(lines) * 110
    y = 720 - total_h // 2
    for line in lines:
        tw = fonts["hook"].getlength(line)
        # sedikit "naik" di awal
        offset = max(0, int((0.35 - min(t, 0.35)) * 40))
        dr.text(((TARGET_WIDTH - tw) / 2, y - offset), line, font=fonts["hook"], fill=TEXT)
        y += 110
    # garis aksen
    dr.rectangle((TARGET_WIDTH // 2 - 60, y + 20, TARGET_WIDTH // 2 + 60, y + 26), fill=ACCENT)


def render_video(
    script: dict,
    tts: TTSResult,
    dest: Path,
    *,
    settings: Settings | None = None,
    background_photo: Path | None = None,
    attribution: str = "",
    fps: int = TARGET_FPS,
) -> Path:
    settings = settings or get_settings()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = tts.duration or 0.0
    words = list(tts.words or [])
    if duration > HARD_MAX_DURATION:
        log.warning(
            "durasi TTS %.1fs melebihi batas keras %.0fs, dipotong",
            duration, HARD_MAX_DURATION,
        )
        duration = HARD_MAX_DURATION
        words = normalize_word_timings(words, duration)
    elif duration <= 0:
        duration = 1.0 / max(1, fps)
    chunks = chunk_captions(words, audio_duration=duration)
    n_frames = max(1, int(round(duration * fps)))
    fonts = {
        "brand": load_font(28, 600, settings),
        "hook": load_font(64, 700, settings),
        "keyword": load_font(86, 800, settings),
        "caption": load_font(44, 500, settings),
        "caption_hi": load_font(48, 800, settings),
        "small": load_font(22, 400, settings),
        "title": load_font(42, 650, settings),
    }
    photo = None
    if background_photo and Path(background_photo).exists():
        try:
            photo = Image.open(background_photo)
        except Exception as e:
            log.info("latar foto gagal: %s", e)
    base = make_background((TARGET_WIDTH, TARGET_HEIGHT), photo)
    hook = script.get("hook") or (script.get("narasi_penuh") or "")[:80]
    windows = build_windows(script, words, duration)
    poses = sorted({(sc.get("pose") or "idle") for *_, sc in windows} | {"idle", "cheer"})
    # panaskan cache sprite
    for p in poses:
        for i in range(16):
            pose_frame(p, i, 16, 100)

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(tts.audio_path),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for fi in range(n_frames):
            t = fi / fps
            frame = base.copy()
            dr = ImageDraw.Draw(frame)
            draw_header(dr, fonts)
            sc = scene_for_time(windows, t)
            pose = (sc.get("pose") or "idle")
            keyword = (sc.get("keyword") or sc.get("teks_layar") or "").upper()
            is_hook = t < 2.0
            if is_hook:
                draw_hook_frame(frame, hook, fonts, t)
            else:
                if keyword:
                    draw_keyword(frame, keyword, fonts["keyword"], y=240)
                # stickman masuk (fade kasar 2–2.4s)
                sprite = pose_frame(pose, fi % 16, 16, 100)
                if t < 2.4:
                    alpha = sprite.split()[-1].point(lambda a: int(a * ((t - 2.0) / 0.4)))
                    sprite = sprite.copy()
                    sprite.putalpha(alpha)
                frame.paste(sprite, ((TARGET_WIDTH - sprite.width) // 2, 420), sprite)
            draw_karaoke(frame, words, t, fonts, chunks=chunks)
            if attribution:
                dr2 = ImageDraw.Draw(frame)
                dr2.text((64, 1488), attribution[:80], font=fonts["small"], fill=MUTED)
            draw_progress(ImageDraw.Draw(frame), t, duration)
            proc.stdin.write(frame.convert("RGB").tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        rc = proc.wait()
    except Exception:
        proc.kill()
        raise
    if rc != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg render gagal ({rc}): {stderr[-800:]}")
    log.info("Render selesai: %s (%.1fs, %s frame)", dest, duration, n_frames)
    return dest
