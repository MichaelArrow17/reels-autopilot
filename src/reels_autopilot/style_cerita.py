"""Gaya B — cerita stickman: pustaka tetap (lingkungan, rig, properti, efek).

LLM hanya mengisi JSON storyboard. Tidak ada kode yang digenerate per video.
"""

from __future__ import annotations

import logging
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reels_autopilot.config import (
    Settings,
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    get_settings,
)
from reels_autopilot.drawutil import (
    SAFE_LEFT,
    SAFE_RIGHT,
    blit,
    draw_centered_lines,
    fit_text,
    load_font,
    make_blob_sprite,
)
from reels_autopilot.encode import encode_video
from reels_autopilot.motion import clamp, ease_in_out_cubic, ease_out_cubic, entrance, lerp, pulse
from reels_autopilot.sfx import (
    mix_events,
    mix_to_wav,
    soft_pad,
    surface_triumph,
    underwater_ambient,
)
from reels_autopilot.storyboard import fallback_cerita, validate_cerita

log = logging.getLogger("reels.cerita")

W, H = TARGET_WIDTH, TARGET_HEIGHT

# Palet karakter (isi, garis)
CHAR_RGB = {
    "kuning": ((255, 204, 34), (176, 118, 8)),
    "abu": ((152, 158, 166), (68, 72, 80)),
    "oranye": ((242, 140, 40), (160, 80, 10)),
    "biru": ((80, 160, 220), (20, 70, 120)),
    "hijau": ((70, 190, 120), (16, 90, 50)),
    "merah": ((220, 70, 70), (120, 20, 20)),
    "putih": ((236, 238, 242), (90, 94, 104)),
}

# ---------- rig stickman klasik ----------

def _rot(x, y, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (c * x - s * y, s * x + c * y)


def joints_for(action: str, phase: float, facing: str = "kanan") -> dict[str, tuple[float, float]]:
    """Titik relatif terhadap pinggul, y ke bawah positif, kepala di y negatif."""
    action = action if action else "idle"
    ph = phase * 2 * math.pi
    breath = math.sin(ph) * 4

    def base():
        return {
            "head": (0, -205 + breath),
            "neck": (0, -168 + breath),
            "hip": (0, 0),
            "sh_l": (-42, -160 + breath),
            "sh_r": (42, -160 + breath),
            "el_l": (-58, -86),
            "el_r": (58, -86),
            "hd_l": (-64, -18),
            "hd_r": (64, -18),
            "kn_l": (-22, 96),
            "kn_r": (22, 96),
            "ft_l": (-28, 196),
            "ft_r": (28, 196),
        }

    j = base()
    if action in {"idle", "stand", "look"}:
        j["hd_l"] = (-64, -18 + math.sin(ph * 0.5) * 3)
        j["hd_r"] = (64, -18 - math.sin(ph * 0.5) * 3)
        if action == "look":
            j["head"] = (18, -205 + breath)
            j["hd_r"] = (110, -150)
            j["el_r"] = (88, -160)
    elif action == "walk":
        sw = math.sin(ph)
        j["kn_l"] = (-22 - 28 * sw, 90 - 18 * abs(sw))
        j["kn_r"] = (22 + 28 * sw, 90 - 18 * abs(-sw))
        j["ft_l"] = (-28 - 48 * sw, 196 - 28 * max(0, sw))
        j["ft_r"] = (28 + 48 * sw, 196 - 28 * max(0, -sw))
        j["hd_l"] = (-50 + 36 * sw, -10)
        j["hd_r"] = (50 - 36 * sw, -10)
        j["el_l"] = (-50 + 16 * sw, -86)
        j["el_r"] = (50 - 16 * sw, -86)
        bounce = abs(math.sin(ph)) * 8
        j = {k: (x, y - bounce) for k, (x, y) in j.items()}
    elif action == "climb":
        sw = math.sin(ph)
        j["hd_l"] = (-36, -250 - 30 * sw)
        j["el_l"] = (-40, -200 - 10 * sw)
        j["hd_r"] = (36, -250 + 30 * sw)
        j["el_r"] = (40, -200 + 10 * sw)
        j["kn_l"] = (-18, 80 - 36 * max(0, sw))
        j["ft_l"] = (-16, 150 - 50 * max(0, sw))
        j["kn_r"] = (18, 80 - 36 * max(0, -sw))
        j["ft_r"] = (16, 150 - 50 * max(0, -sw))
        j["head"] = (0, -210 + breath)
    elif action in {"swim", "struggle"}:
        amp = 1.4 if action == "struggle" else 1.0
        tilt = -0.45 if action == "swim" else -0.25
        sw = math.sin(ph * (1.4 if action == "struggle" else 1.0)) * amp
        j["el_l"] = (-70, -140 - 50 * sw)
        j["hd_l"] = (-90, -200 - 70 * sw)
        j["el_r"] = (70, -140 + 50 * sw)
        j["hd_r"] = (90, -200 + 70 * sw)
        j["kn_l"] = (-20, 90 + 20 * sw)
        j["ft_l"] = (-10, 190 + 30 * sw)
        j["kn_r"] = (20, 90 - 20 * sw)
        j["ft_r"] = (10, 190 - 30 * sw)
        # miring seluruh tubuh
        j = {k: _rot(x, y, tilt) for k, (x, y) in j.items()}
    elif action == "sink":
        limp = 0.15
        j["el_l"] = (-80, -40)
        j["hd_l"] = (-100, 20)
        j["el_r"] = (80, -50)
        j["hd_r"] = (95, 10)
        j["head"] = (8, -220)
        j["kn_l"] = (-30, 100)
        j["ft_l"] = (-50, 190)
        j["kn_r"] = (16, 110)
        j["ft_r"] = (10, 200)
        ang = limp + math.sin(ph * 0.5) * 0.08
        j = {k: _rot(x, y, ang) for k, (x, y) in j.items()}
    elif action == "fall":
        # jatuh miring, goyang pelan — tidak berputar penuh agar tubuh tetap utuh
        ang = 1.05 + 0.28 * math.sin(ph)
        j["el_l"] = (-90, -40)
        j["hd_l"] = (-120, 20)
        j["el_r"] = (80, -90)
        j["hd_r"] = (110, -30)
        j["kn_l"] = (-40, 110)
        j["ft_l"] = (-80, 170)
        j["kn_r"] = (50, 110)
        j["ft_r"] = (90, 160)
        j = {k: _rot(x, y, ang) for k, (x, y) in j.items()}
    elif action == "push":
        j["head"] = (30, -210)
        j["sh_l"] = (-20, -150)
        j["sh_r"] = (60, -155)
        j["el_r"] = (110, -130)
        j["hd_r"] = (170, -110)
        j["el_l"] = (20, -80)
        j["hd_l"] = (90, -70)
        j["hip"] = (0, 0)
        j["kn_l"] = (-40, 100)
        j["ft_l"] = (-70, 196)
        j["kn_r"] = (40, 100)
        j["ft_r"] = (50, 196)
    elif action == "celebrate":
        wig = math.sin(ph * 2) * 16
        bounce = abs(math.sin(ph)) * 18
        j["hd_l"] = (-70 - wig, -340)
        j["el_l"] = (-60, -250)
        j["hd_r"] = (70 + wig, -340)
        j["el_r"] = (60, -250)
        j["head"] = (0, -215)
        j["kn_l"] = (-36, 90)
        j["ft_l"] = (-50, 190)
        j["kn_r"] = (36, 90)
        j["ft_r"] = (50, 190)
        j = {k: (x, y - bounce) for k, (x, y) in j.items()}
    elif action == "sit":
        j["head"] = (0, -150)
        j["neck"] = (0, -100)
        j["sh_l"] = (-40, -90)
        j["sh_r"] = (40, -90)
        j["el_l"] = (-20, -20)
        j["el_r"] = (20, -20)
        j["hd_l"] = (10, -50)   # dekat kepala, lesu
        j["hd_r"] = (30, 10)
        j["hip"] = (0, 40)
        j["kn_l"] = (40, 50)
        j["kn_r"] = (70, 50)
        j["ft_l"] = (40, 120)
        j["ft_r"] = (100, 120)
    elif action == "reach":
        j["hd_r"] = (20, -390)
        j["el_r"] = (16, -280)
        j["sh_r"] = (30, -170)
        j["hd_l"] = (-50, -20)
        j["el_l"] = (-50, -80)
        j["head"] = (6, -210)
        j["kn_l"] = (-16, 100)
        j["ft_l"] = (-20, 196)
        j["kn_r"] = (30, 90)
        j["ft_r"] = (24, 160)  # ujung kaki menendang ke atas
    elif action == "limp":
        # tergeletak mendatar, semua sendi tetap tersambung
        j["hip"] = (0, 40)
        j["neck"] = (95, 20)
        j["head"] = (145, 8)
        j["sh_l"] = (60, 35)
        j["sh_r"] = (95, 8)
        j["el_l"] = (40, 85)
        j["hd_l"] = (10, 115)
        j["el_r"] = (145, -5)
        j["hd_r"] = (185, 30)
        j["kn_l"] = (-85, 50)
        j["ft_l"] = (-155, 55)
        j["kn_r"] = (-55, 85)
        j["ft_r"] = (-125, 115)
    elif action == "kneel":
        j["head"] = (0, -180)
        j["neck"] = (0, -120)
        j["sh_l"] = (-42, -110)
        j["sh_r"] = (42, -110)
        j["el_l"] = (-50, -40)
        j["hd_l"] = (-40, 20)
        j["el_r"] = (50, -40)
        j["hd_r"] = (40, 20)
        j["kn_l"] = (-30, 60)
        j["ft_l"] = (-80, 70)
        j["kn_r"] = (40, 100)
        j["ft_r"] = (40, 196)
    elif action == "wave":
        wig = math.sin(ph * 2) * 28
        j["hd_r"] = (80 + wig, -320)
        j["el_r"] = (70, -230)
        j["hd_l"] = (-60, -10)
        j["el_l"] = (-55, -80)
    else:
        # idle sudah di base
        pass

    if facing == "kiri":
        j = {k: (-x, y) for k, (x, y) in j.items()}
    return j


def _thick(d: ImageDraw.ImageDraw, a, b, fill, width: int) -> None:
    d.line([a, b], fill=fill, width=width)
    r = max(1, width // 2)
    for p in (a, b):
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=fill)


@lru_cache(maxsize=768)
def stick_sprite(action: str, phase_i: int, color: str, facing: str, scale_pct: int = 100) -> Image.Image:
    """Sprite RGBA ter-cache. phase_i 0–15."""
    scale = scale_pct / 100.0
    phase = (phase_i % 16) / 16.0
    fill, outline = CHAR_RGB.get(color, CHAR_RGB["kuning"])
    mul = 2
    w, h = 520 * mul, 860 * mul
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = w // 2, int(h * 0.62)
    pts = joints_for(action, phase, facing)

    def P(name: str) -> tuple[int, int]:
        x, y = pts[name]
        return int(ox + x * mul * scale), int(oy + y * mul * scale)

    lw = max(8, int(13 * mul * scale))
    # kaki
    _thick(d, P("hip"), P("kn_l"), fill, lw)
    _thick(d, P("kn_l"), P("ft_l"), fill, lw)
    _thick(d, P("hip"), P("kn_r"), fill, lw)
    _thick(d, P("kn_r"), P("ft_r"), fill, lw)
    # badan + leher ke kepala (supaya tidak terputus saat miring)
    _thick(d, P("neck"), P("hip"), fill, lw + 2)
    _thick(d, P("neck"), P("head"), fill, lw)
    # lengan
    _thick(d, P("sh_l"), P("el_l"), fill, lw)
    _thick(d, P("el_l"), P("hd_l"), fill, lw)
    _thick(d, P("sh_r"), P("el_r"), fill, lw)
    _thick(d, P("el_r"), P("hd_r"), fill, lw)
    # bahu
    _thick(d, P("sh_l"), P("sh_r"), fill, lw)
    # kepala
    hx, hy = P("head")
    hr = int(46 * mul * scale * 0.72)
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=fill, outline=outline, width=max(3, lw // 4))
    # mata
    blink = abs(math.sin(phase * 2 * math.pi * 0.4)) < 0.06
    eye_r = 6 if not blink else 2
    eye_y = hy - 4
    dx_sign = -1 if facing == "kiri" else 1
    for dx in (-15, 15):
        d.ellipse(
            (hx + dx * dx_sign - eye_r, eye_y - eye_r, hx + dx * dx_sign + eye_r, eye_y + (2 if blink else eye_r)),
            fill=outline,
        )
    layer = layer.resize((w // mul, h // mul), Image.Resampling.LANCZOS)
    return layer


def sprite_paste(canvas: Image.Image, sprite: Image.Image, hip_xy: tuple[int, int], *, glow=None, alpha: float = 1.0) -> None:
    """Pinggul di hip_xy. Sprite dibuat dengan hip di 0.62 tinggi."""
    sw, sh = sprite.size
    px = int(hip_xy[0] - sw / 2)
    py = int(hip_xy[1] - sh * 0.62)
    if glow:
        # halo sederhana
        halo = Image.new("RGBA", (sw + 80, sh + 80), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((20, 20, sw + 60, sh * 0.6), fill=(*glow, 50))
        halo = halo.filter(ImageFilter.GaussianBlur(24))
        blit(canvas, halo, (px - 40, py - 40), alpha=alpha)
    blit(canvas, sprite, (px, py), alpha=alpha)


# ---------- properti ----------

def draw_chain_ball(
    img: Image.Image,
    ankle: tuple[int, int],
    *,
    broken: bool = False,
    t: float = 0.0,
    ground_y: int = 1640,
    seed: int = 0,
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    ax, ay = ankle
    swing = math.sin(t * 3.1 + seed) * 14
    if broken:
        # bola di tanah, rantai putus
        bx, by = ax + 40 + seed * 7, ground_y - 28
        # potongan rantai
        rng = random.Random(seed + 17)
        for i in range(5):
            lx = ax + rng.randint(-40, 80)
            ly = ground_y - 10 - rng.randint(0, 40)
            d.ellipse((lx - 8, ly - 5, lx + 8, ly + 11), outline=(70, 74, 80, 255), width=4)
    else:
        bx, by = ax + swing, min(ground_y - 28, ay + 130 + math.sin(t * 2 + seed) * 8)
        # tautan
        steps = 6
        for i in range(steps):
            u = (i + 0.5) / steps
            x = int(ax + (bx - ax) * u)
            y = int(ay + (by - ay) * u)
            d.ellipse((x - 9, y - 6, x + 9, y + 12), outline=(70, 74, 80, 255), width=4)
        # gembok/kaitan di pergelangan
        d.ellipse((ax - 10, ay - 8, ax + 14, ay + 12), outline=(50, 52, 58, 255), width=5)
    # bola meriam
    r = 32
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=(32, 34, 40, 255), outline=(12, 12, 14, 255), width=3)
    d.ellipse((bx - 12, by - 18, bx + 2, by - 6), fill=(90, 94, 102, 160))  # highlight


def draw_ladder(img: Image.Image, x: int, y0: int, y1: int) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    col = (120, 90, 50, 255)
    d.line((x, y0, x, y1), fill=col, width=10)
    d.line((x + 70, y0, x + 70, y1), fill=col, width=10)
    n = max(3, int(abs(y1 - y0) / 50))
    for i in range(n):
        y = y0 + (y1 - y0) * i / max(1, n - 1)
        d.line((x, y, x + 70, y), fill=col, width=7)


def draw_coin_prop(img: Image.Image, xy: tuple[int, int], t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    x, y = xy
    r = 18
    d.ellipse((x - r, y - r, x + r, y + r), fill=(242, 186, 40, 255), outline=(180, 120, 20, 255), width=3)


# ---------- gelembung kata ----------

def draw_speech_bubble(
    img: Image.Image,
    text: str,
    *,
    tip: tuple[int, int],
    side: str = "right",
    fonts: dict,
    appear: float = 1.0,
) -> tuple[int, int, int, int] | None:
    if not text or appear <= 0.02:
        return None
    text = text.strip()
    font = fonts["bubble"]
    max_w = 420
    lines, font, _sz = fit_text(text, max_width=max_w - 36, max_height=200, max_size=36, min_size=20, weight=700, max_lines=3)
    lh = int(getattr(font, "size", 32) * 1.15)
    tw = max(font.getlength(ln) for ln in lines) if lines else 40
    th = lh * len(lines)
    pad_x, pad_y = 22, 14
    bw, bh = int(tw + pad_x * 2), int(th + pad_y * 2)
    # posisi: di atas ujung (kepala)
    tx, ty = tip
    if side == "left":
        x0 = tx - bw + 20
    else:
        x0 = tx - 20
    y0 = ty - bh - 36
    # clamp ke area aman
    x0 = max(SAFE_LEFT, min(SAFE_RIGHT - bw, x0))
    y0 = max(80, min(H - 200 - bh, y0))
    x1, y1 = x0 + bw, y0 + bh
    scale = 0.6 + 0.4 * clamp(appear)
    if scale < 0.99:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        bw2, bh2 = bw * scale, bh * scale
        x0, y0 = int(cx - bw2 / 2), int(cy - bh2 / 2)
        x1, y1 = int(cx + bw2 / 2), int(cy + bh2 / 2)
        bw, bh = x1 - x0, y1 - y0
    d = ImageDraw.Draw(img, "RGBA")
    # badan
    d.rounded_rectangle((x0, y0, x1, y1), radius=8, fill=(255, 255, 255, 255), outline=(16, 16, 18, 255), width=6)
    # ekor
    if side == "left":
        tail = [(x0 + 28, y1 - 2), (x0 + 8, y1 + 28), (x0 + 56, y1 - 2)]
    else:
        tail = [(x1 - 56, y1 - 2), (x1 - 8, y1 + 28), (x1 - 28, y1 - 2)]
    d.polygon(tail, fill=(255, 255, 255, 255), outline=(16, 16, 18, 255))
    # tutup garis ekor di tepi kotak
    d.rectangle((min(p[0] for p in tail) + 8, y1 - 8, max(p[0] for p in tail) - 8, y1 + 2), fill=(255, 255, 255, 255))
    # teks
    yy = y0 + pad_y * scale
    for ln in lines:
        twl = font.getlength(ln)
        d.text(((x0 + x1) / 2 - twl / 2, yy), ln, font=font, fill=(16, 16, 18, 255))
        yy += lh * scale
    return (x0, y0, x1, y1 + 28)


# ---------- lingkungan (statis di-cache, animasi per frame) ----------

def _vertical_gradient(colors: list[tuple[int, int, tuple[int, int, int]]]) -> Image.Image:
    """colors: list (y, y, rgb) stops 0–H."""
    col = Image.new("RGB", (1, H))
    px = col.load()
    stops = sorted((max(0, min(H - 1, int(y))), rgb) for y, rgb in ((s[0], s[2]) if len(s) == 3 else s for s in colors))
    if stops[0][0] != 0:
        stops = [(0, stops[0][1])] + stops
    if stops[-1][0] != H - 1:
        stops.append((H - 1, stops[-1][1]))
    for i in range(len(stops) - 1):
        y0, c0 = stops[i]
        y1, c1 = stops[i + 1]
        span = max(1, y1 - y0)
        for y in range(y0, y1 + (1 if i == len(stops) - 2 else 0)):
            u = (y - y0) / span
            rgb = tuple(int(c0[k] + (c1[k] - c0[k]) * u) for k in range(3))
            px[0, y] = rgb
    return col.resize((W, H), Image.Resampling.BILINEAR)


@lru_cache(maxsize=8)
def _env_static(env: str) -> Image.Image:
    if env == "underwater":
        img = _vertical_gradient([
            (0, 0, (18, 12, 10)),
            (400, 0, (28, 20, 14)),
            (520, 0, (20, 40, 55)),
            (560, 0, (40, 110, 145)),
            (900, 0, (18, 70, 110)),
            (1400, 0, (10, 36, 70)),
            (1640, 0, (8, 28, 50)),
            (1680, 0, (62, 48, 32)),
            (1920, 0, (40, 30, 20)),
        ])
        d = ImageDraw.Draw(img, "RGBA")
        # bintang di langit
        rng = random.Random(3)
        for _ in range(40):
            x, y = rng.randint(20, W - 20), rng.randint(20, 480)
            r = rng.choice((1, 1, 2, 2, 3))
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 230, 160, rng.randint(80, 200)))
        # gundukan pasir
        d.polygon(
            [(0, 1660), (80, 1630), (200, 1655), (360, 1620), (540, 1650),
             (720, 1615), (900, 1650), (1080, 1628), (1080, H), (0, H)],
            fill=(72, 56, 36, 255),
        )
        d.polygon(
            [(0, 1720), (200, 1690), (500, 1730), (800, 1688), (1080, 1710), (1080, H), (0, H)],
            fill=(54, 42, 28, 255),
        )
        return img
    if env in {"staircase", "mountain"}:
        if env == "mountain":
            img = _vertical_gradient([
                (0, 0, (255, 180, 110)),
                (400, 0, (255, 140, 90)),
                (900, 0, (80, 70, 90)),
                (1920, 0, (40, 36, 42)),
            ])
            d = ImageDraw.Draw(img, "RGBA")
            d.polygon([(0, 900), (200, 600), (420, 820), (600, 480), (900, 780), (1080, 520), (1080, H), (0, H)], fill=(70, 62, 72, 255))
            d.polygon([(0, 1200), (300, 900), (700, 1100), (1080, 860), (1080, H), (0, H)], fill=(52, 48, 56, 255))
        else:
            img = _vertical_gradient([
                (0, 0, (40, 50, 80)),
                (500, 0, (70, 55, 90)),
                (1100, 0, (30, 28, 40)),
                (1920, 0, (22, 20, 28)),
            ])
            d = ImageDraw.Draw(img, "RGBA")
        # tangga
        for i in range(14):
            y = 1780 - i * 108
            x = 40 + i * 42
            col = (90 + (i % 2) * 12, 82, 78, 255) if env == "staircase" else (96, 88, 82, 255)
            d.rectangle((x, y, W - 40, y + 28), fill=col)
            d.rectangle((x, y + 28, x + 80, min(H, y + 108)), fill=(70, 64, 60, 255))
        # cahaya di puncak
        return img
    if env == "road":
        img = _vertical_gradient([
            (0, 0, (255, 160, 90)),
            (500, 0, (120, 80, 90)),
            (800, 0, (50, 70, 50)),
            (1920, 0, (30, 50, 32)),
        ])
        d = ImageDraw.Draw(img, "RGBA")
        # bukit
        d.ellipse((-200, 700, 500, 1200), fill=(40, 80, 50, 255))
        d.ellipse((600, 720, 1300, 1300), fill=(36, 72, 46, 255))
        # jalan perspektif
        d.polygon([(200, H), (880, H), (640, 820), (440, 820)], fill=(48, 50, 54, 255))
        # garis tengah
        for i in range(12):
            u0, u1 = i / 12, (i + 0.45) / 12
            def xp(u):
                return lerp(540, 540, u)
            def yp(u):
                return lerp(H, 820, u)
            def wd(u):
                return lerp(16, 4, u)
            y0, y1 = yp(u0), yp(u1)
            w0, w1 = wd(u0), wd(u1)
            d.polygon([(xp(u0) - w0, y0), (xp(u0) + w0, y0), (xp(u1) + w1, y1), (xp(u1) - w1, y1)], fill=(230, 210, 80, 255))
        # finish banner
        d.rectangle((400, 760, 680, 820), fill=(40, 40, 42, 255))
        d.rectangle((420, 700, 660, 760), fill=(230, 50, 50, 255))
        return img
    if env == "office":
        img = _vertical_gradient([
            (0, 0, (210, 214, 220)),
            (1100, 0, (200, 204, 210)),
            (1300, 0, (160, 158, 152)),
            (1920, 0, (140, 138, 132)),
        ])
        d = ImageDraw.Draw(img, "RGBA")
        # jendela
        d.rounded_rectangle((640, 220, 1000, 820), radius=8, fill=(160, 200, 230, 255), outline=(90, 94, 100, 255), width=8)
        d.line((820, 220, 820, 820), fill=(90, 94, 100, 255), width=6)
        d.line((640, 520, 1000, 520), fill=(90, 94, 100, 255), width=6)
        # lantai garis
        d.rectangle((0, 1280, W, H), fill=(150, 148, 142, 255))
        # meja kiri & kanan
        for x0 in (80, 620):
            d.rounded_rectangle((x0, 1180, x0 + 380, 1280), radius=6, fill=(86, 64, 46, 255))
            d.rectangle((x0 + 30, 1280, x0 + 60, 1500), fill=(70, 52, 38, 255))
            d.rectangle((x0 + 320, 1280, x0 + 350, 1500), fill=(70, 52, 38, 255))
            # monitor
            d.rounded_rectangle((x0 + 90, 980, x0 + 300, 1180), radius=8, fill=(40, 44, 52, 255))
            d.rectangle((x0 + 110, 1000, x0 + 280, 1140), fill=(80, 160, 200, 255))
        return img
    # scale
    img = _vertical_gradient([
        (0, 0, (24, 22, 36)),
        (800, 0, (36, 30, 48)),
        (1920, 0, (16, 14, 22)),
    ])
    d = ImageDraw.Draw(img, "RGBA")
    # pilar
    d.rectangle((500, 900, 580, 1700), fill=(90, 84, 76, 255))
    d.polygon([(480, 900), (540, 780), (600, 900)], fill=(110, 100, 88, 255))
    d.rectangle((400, 1680, 680, 1740), fill=(70, 66, 60, 255))
    return img


_GLOW_SPRITE = None
_RAY_SPRITE = None


def _glow_sprite() -> Image.Image:
    global _GLOW_SPRITE
    if _GLOW_SPRITE is None:
        s = 900
        im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((80, 80, s - 80, s - 80), fill=(255, 210, 60, 90))
        ImageDraw.Draw(im).ellipse((280, 280, s - 280, s - 280), fill=(255, 240, 160, 140))
        _GLOW_SPRITE = im.filter(ImageFilter.GaussianBlur(40))
    return _GLOW_SPRITE


def _ray_sprite() -> Image.Image:
    global _RAY_SPRITE
    if _RAY_SPRITE is None:
        im = Image.new("RGBA", (220, 1200), (0, 0, 0, 0))
        ImageDraw.Draw(im).polygon([(90, 0), (130, 0), (200, 1200), (20, 1200)], fill=(200, 230, 255, 28))
        _RAY_SPRITE = im
    return _RAY_SPRITE


def _surface_y(t: float) -> list[tuple[int, int]]:
    pts = []
    for x in range(0, W + 1, 16):
        y = 560 + math.sin(x * 0.012 + t * 2.2) * 10 + math.sin(x * 0.035 + t * 3.1) * 4
        pts.append((x, int(y)))
    return pts


def draw_environment(img: Image.Image, env: str, t: float, climax: float = 0.0) -> dict:
    """Gambar lingkungan ke img (RGB). Kembalikan meta (surface_y, ground_y, ...)."""
    base = _env_static(env)
    img.paste(base)
    meta = {"ground_y": 1640, "surface_y": 560, "env": env}
    d = ImageDraw.Draw(img, "RGBA")
    if env == "underwater":
        # sinar
        ray = _ray_sprite()
        for i, x in enumerate((180, 400, 620, 850)):
            ang = math.sin(t * 0.4 + i) * 4
            xx = int(x + math.sin(t * 0.5 + i * 1.3) * 18)
            # paste with slight offset; skip rotate for speed
            blit(img, ray, (xx - 110, 540), alpha=0.7 + 0.2 * math.sin(t + i))
        # permukaan
        pts = _surface_y(t)
        meta["surface_pts"] = pts
        meta["surface_y"] = 560
        # isi langit sudah di static; garis permukaan
        if len(pts) > 2:
            d.line(pts, fill=(210, 240, 255, 220), width=6)
            # highlight kedua
            pts2 = [(x, y + 6) for x, y in pts]
            d.line(pts2, fill=(80, 160, 190, 80), width=4)
        # rumput laut
        rng = random.Random(5)
        for i in range(11):
            bx = 40 + i * 100 + (i % 3) * 12
            hgt = 140 + (i * 37) % 120
            pts_w = []
            for k in range(9):
                u = k / 8
                sway = math.sin(t * 1.4 + i + u * 2.2) * 22 * u
                pts_w.append((bx + sway, 1650 - hgt * u))
            color = (20, 80 + (i % 4) * 16, 55, 255)
            d.line(pts_w, fill=color, width=8 + i % 5, joint="curve")
        # gelembung
        for i in range(28):
            speed = 28 + (i * 13) % 40
            x = (70 + i * 37 + int(math.sin(i * 3) * 20)) % W
            y = 1640 - ((t * speed + i * 80) % 1100)
            if y < 540:
                continue
            r = 3 + i % 8
            d.ellipse((x - r, y - r, x + r, y + r), outline=(200, 230, 250, 160), width=2)
            d.ellipse((x - r / 2, y - r * 0.8, x - r / 6, y - r * 0.3), fill=(230, 245, 255, 100))
        # partikel
        for i in range(35):
            x = (30 + i * 29) % W
            y = 600 + (i * 97 + t * 8) % 1000
            d.ellipse((x, y, x + 2, y + 2), fill=(200, 230, 250, 90))
        meta["ground_y"] = 1640
        if climax > 0:
            g = _glow_sprite()
            blit(img, g, (int(W * 0.55 - g.width / 2), int(200 - g.height / 3)), alpha=climax)
            # lingkaran emas
            R = int(280 + 80 * climax)
            cx, cy = int(W * 0.62), 280
            d.ellipse((cx - R, cy - R, cx + R, cy + R), outline=(255, 210, 70, int(160 * climax)), width=4)
    elif env in {"staircase", "mountain"}:
        meta["ground_y"] = 1780
        if climax > 0:
            g = _glow_sprite()
            blit(img, g, (int(W * 0.65 - g.width / 2), -100), alpha=climax * 0.85)
    elif env == "road":
        meta["ground_y"] = 1700
        if climax > 0:
            g = _glow_sprite()
            blit(img, g, (int(W * 0.8 - g.width / 2), 400), alpha=climax * 0.8)
    elif env == "office":
        meta["ground_y"] = 1280
        # lampu kedip lembut
        if int(t * 2) % 9 == 0:
            pass
    elif env == "scale":
        meta["ground_y"] = 900
        # balok timbangan miring sesuai climax
        tilt = lerp(-0.18, 0.28, climax)
        cx, cy = 540, 900
        length = 420
        dx, dy = math.cos(tilt) * length, math.sin(tilt) * length
        d.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=(200, 190, 170, 255), width=16)
        # piring
        for sign, col in ((-1, (160, 160, 168, 255)), (1, (230, 190, 60, 255))):
            px, py = cx + sign * dx, cy + sign * dy
            d.polygon([(px - 120, py), (px + 120, py), (px + 90, py + 40), (px - 90, py + 40)], fill=col)
        meta["pan_a"] = (cx - dx, cy - dy + 10)
        meta["pan_b"] = (cx + dx, cy + dy + 10)
    return meta


def map_pos(env: str, x: float, y: float, meta: dict, char_id: str = "b") -> tuple[int, int]:
    """Peta koordinat 0–1 ke piksel pinggul."""
    if env == "underwater":
        # y=0 di atas air (langit), y=0.22 permukaan, y=0.88 pasir
        px = int(lerp(140, 940, clamp(x)))
        py = int(lerp(280, meta.get("ground_y", 1640) - 20, clamp(y)))
        return px, py
    if env in {"staircase", "mountain"}:
        px = int(lerp(160, 900, clamp(x)))
        py = int(lerp(300, 1700, clamp(y)))
        return px, py
    if env == "road":
        # semakin "jauh" (x besar) semakin naik (perspektif ke finish)
        px = int(lerp(250, 900, clamp(x)))
        py = int(lerp(1650, 900, clamp(y) * 0.3 + clamp(x) * 0.5))
        return px, py
    if env == "office":
        px = int(lerp(200, 900, clamp(x)))
        py = int(meta.get("ground_y", 1280) - 20)
        return px, py
    if env == "scale":
        key = "pan_a" if char_id == "a" else "pan_b"
        if key in meta:
            return int(meta[key][0]), int(meta[key][1] - 10)
        px = int(lerp(200, 880, clamp(x)))
        py = int(lerp(800, 1200, clamp(y)))
        return px, py
    return int(lerp(140, 940, clamp(x))), int(lerp(400, 1600, clamp(y)))


# ---------- interpolasi beat ----------

def _beat_at(beats: list[dict], t: float) -> tuple[dict, dict, float]:
    cur = beats[0]
    prev = beats[0]
    for b in beats:
        if b["t"] <= t + 1e-6:
            prev = cur
            cur = b
        else:
            break
    dur = min(0.9, max(0.25, cur.get("durasi", 3) * 0.4))
    u = ease_in_out_cubic(clamp((t - cur["t"]) / dur)) if dur else 1.0
    return prev, cur, u


def character_pose(sb: dict, which: str, t: float) -> dict:
    beats = sb["beats"]
    prev, cur, u = _beat_at(beats, t)
    key = "aksi_a" if which == "a" else "aksi_b"
    pa, ca = prev[key], cur[key]
    x = lerp(pa["x"], ca["x"], u)
    y = lerp(pa["y"], ca["y"], u)
    action = ca["nama"]
    facing = ca.get("hadap") or pa.get("hadap") or ""
    if not facing:
        facing = "kiri" if (ca["x"] - pa["x"]) < -0.02 else "kanan"
    # fase animasi
    speed = {"walk": 2.2, "swim": 1.6, "climb": 1.8, "struggle": 2.6, "celebrate": 2.0, "wave": 2.4}.get(action, 1.0)
    phase = (t * speed) % 1.0
    bubble = cur.get("gelembung_a") if which == "a" else cur.get("gelembung_b")
    # appear di awal beat
    appear = entrance(t, cur["t"], 0.28, "back")
    if t > cur["t"] + cur["durasi"] - 0.25:
        appear = clamp((cur["t"] + cur["durasi"] - t) / 0.25)
    return {
        "x": x, "y": y, "action": action, "facing": facing, "phase": phase,
        "bubble": bubble or "", "appear": appear,
        "props": [p for p in (cur.get("properti") or []) if (p.get("pada") or which) in {which, p.get("pada"), ""}],
        "effects": cur.get("efek") or [],
        "klimaks": bool(cur.get("klimaks")),
        "beat": cur,
    }


# ---------- audio ----------

def build_cerita_audio(sb: dict, dest: Path, *, voice: Path | None = None, settings: Settings | None = None) -> Path:
    dur = float(sb.get("durasi_detik") or 24)
    env = sb.get("environment") or "underwater"
    if env == "underwater":
        music = underwater_ambient(dur, gain=0.18)
    else:
        music = soft_pad(dur, gain=0.09)
    events: list[tuple[float, str]] = []
    for b in sb.get("beats") or []:
        for s in b.get("sfx") or []:
            events.append((float(b["t"]), str(s)))
        if b.get("klimaks"):
            if "break" not in (b.get("sfx") or []):
                events.append((float(b["t"]), "break"))
            events.append((float(b["t"]) + 0.25, "chime"))
    sfx = mix_events(events, dur, gain=0.38)
    # kemenangan di klimaks
    kt = float((sb.get("klimaks") or {}).get("t") or 0)
    if kt > 0:
        tri = surface_triumph(min(3.0, dur - kt))
        off = int(kt * 44100)
        # sisipkan ke sfx (panjang mungkin beda)
        # cukup lewat mix_events: kita tambahkan sebagai raw — mix_events hanya terima nama.
        # manual:
        rate = 44100
        need = off + len(tri)
        if need > len(sfx):
            sfx = sfx + [0.0] * (need - len(sfx))
        for i, s in enumerate(tri):
            sfx[off + i] = sfx[off + i] + s * 0.4
    return mix_to_wav(
        dest, dur,
        voice=voice if voice and Path(voice).exists() else None,
        music=music, sfx=sfx,
        voice_gain=1.0, music_gain=1.0, sfx_gain=1.0,
        loudnorm_on=True,
    )


# ---------- frame & render ----------

def render_cerita_frame(
    sb: dict,
    t: float,
    fonts: dict,
    *,
    climax_amt: float | None = None,
) -> Image.Image:
    env = sb.get("environment") or "underwater"
    kt = float((sb.get("klimaks") or {}).get("t") or 0)
    if climax_amt is None:
        climax_amt = clamp((t - kt) / 1.2) if kt and t >= kt else 0.0
    img = Image.new("RGB", (W, H), (0, 0, 0))
    meta = draw_environment(img, env, t, climax_amt)
    colors = {c["id"]: c.get("warna") or ("abu" if c["id"] == "a" else "kuning") for c in sb.get("karakter") or []}
    # karakter a dulu (sering di belakang / bawah), b di depan
    poses = {}
    for which in ("a", "b"):
        poses[which] = character_pose(sb, which, t)
    # urutan: yang y lebih besar (lebih bawah) digambar kemudian? untuk air, yang di depan (b) terakhir
    for which in ("a", "b"):
        p = poses[which]
        color = colors.get(which, "kuning" if which == "b" else "abu")
        hip = map_pos(env, p["x"], p["y"], meta, which)
        phase_i = int(p["phase"] * 16) % 16
        scale = 100 if env != "road" else int(lerp(110, 70, p["x"]))
        spr = stick_sprite(p["action"], phase_i, color, p["facing"], scale)
        glow = (255, 210, 60) if (which == (sb.get("klimaks") or {}).get("pemenang", "b") and climax_amt > 0.3) else None
        sprite_paste(img, spr, hip, glow=glow)
        # properti rantai
        for prop in p["props"]:
            jenis = prop.get("jenis")
            if jenis in {"chain_ball", "chain", "ball"}:
                # pergelangan kaki kiri kira-kira di bawah pinggul
                ankle = (hip[0] - (18 if p["facing"] == "kanan" else -18), hip[1] + int(196 * scale / 100 * 0.55))
                broken = bool(climax_amt > 0.4 and which == (sb.get("klimaks") or {}).get("pemenang", "b"))
                draw_chain_ball(img, ankle, broken=broken, t=t, ground_y=meta.get("ground_y", 1640), seed=hash(which) % 9)
            elif jenis == "ladder":
                draw_ladder(img, hip[0] - 40, hip[1] - 400, meta.get("ground_y", 1640))
            elif jenis == "coin":
                draw_coin_prop(img, (hip[0] + 50, hip[1] - 80), t)
        # gelembung
        if p["bubble"]:
            head = (hip[0], hip[1] - int(230 * scale / 100))
            side = "left" if which == "a" else "right"
            # jika dekat tepi, balik
            if head[0] < 280:
                side = "right"
            if head[0] > W - 280:
                side = "left"
            draw_speech_bubble(img, p["bubble"], tip=head, side=side, fonts=fonts, appear=p["appear"])
    # label atas
    lk = (sb.get("label_kiri") or "").upper()
    rk = (sb.get("label_kanan") or "").upper()
    d = ImageDraw.Draw(img)
    if lk:
        tw = fonts["label"].getlength(lk)
        d.text((W * 0.25 - tw / 2, 90), lk, font=fonts["label"], fill=(170, 174, 180, 255))
    if rk:
        col = (255, 210, 50) if climax_amt > 0 else (255, 204, 34)
        tw = fonts["label"].getlength(rk)
        # sedikit glow
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((W * 0.72 - tw / 2 + ox, 90 + oy), rk, font=fonts["label"], fill=(120, 80, 10, 80))
        d.text((W * 0.72 - tw / 2, 90), rk, font=fonts["label"], fill=col)
    # merek kecil, tidak menonjol
    d.text((SAFE_LEFT, H - 48), "PO CHAI", font=fonts["tiny"], fill=(200, 200, 200, 70))
    return img


def render_cerita(
    storyboard: dict,
    audio_path: Path,
    dest: Path,
    *,
    settings: Settings | None = None,
    fps: int = TARGET_FPS,
) -> Path:
    settings = settings or get_settings()
    sb, fb, err = validate_cerita(storyboard)
    if fb:
        log.warning("render cerita memakai fallback: %s", err)
    duration = float(sb.get("durasi_detik") or 24)
    fonts = {
        "label": load_font(42, 800, settings),
        "bubble": load_font(34, 700, settings),
        "tiny": load_font(20, 500, settings),
        "clim": load_font(52, 800, settings),
    }
    n = max(1, int(round(duration * fps)))

    def frames():
        for i in range(n):
            t = i / fps
            yield render_cerita_frame(sb, t, fonts)

    return encode_video(dest, audio_path, duration, frames(), fps=fps)
