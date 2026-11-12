"""Karakter stickman 9:16 (pose dari kit stickman-story: idle/walk/sit/typing/point/cheer + think/shrug).

Dirender 2× lalu dikecilkan agar garis halus. Tanpa ketergantungan Remotion/Node —
cocok di GitHub-hosted Ubuntu runner.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

# titik relatif terhadap pinggul (0, 0), satuan "desain" (naik = y negatif)
# skala diterapkan saat gambar
POSES: dict[str, dict[str, tuple[float, float]]] = {
    "idle": {
        "head": (0, -268), "neck": (0, -210),
        "sh_l": (-46, -200), "sh_r": (46, -200),
        "el_l": (-78, -110), "el_r": (78, -110),
        "hd_l": (-84, -28), "hd_r": (84, -28),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-32, 118), "kn_r": (32, 118),
        "ft_l": (-36, 242), "ft_r": (36, 242),
    },
    "point": {
        "head": (8, -270), "neck": (4, -210),
        "sh_l": (-44, -198), "sh_r": (50, -206),
        "el_l": (-80, -115), "el_r": (110, -170),
        "hd_l": (-86, -40), "hd_r": (168, -230),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-28, 118), "kn_r": (38, 118),
        "ft_l": (-32, 242), "ft_r": (42, 242),
    },
    "think": {
        "head": (14, -268), "neck": (4, -210),
        "sh_l": (-48, -198), "sh_r": (50, -202),
        "el_l": (-86, -120), "el_r": (86, -150),
        "hd_l": (-90, -40), "hd_r": (48, -250),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-30, 120), "kn_r": (34, 118),
        "ft_l": (-34, 242), "ft_r": (38, 242),
    },
    "cheer": {
        "head": (0, -280), "neck": (0, -218),
        "sh_l": (-50, -210), "sh_r": (50, -210),
        "el_l": (-95, -300), "el_r": (95, -300),
        "hd_l": (-90, -390), "hd_r": (90, -390),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-40, 118), "kn_r": (40, 118),
        "ft_l": (-50, 242), "ft_r": (50, 242),
    },
    "typing": {
        "head": (0, -250), "neck": (0, -200),
        "sh_l": (-50, -190), "sh_r": (50, -190),
        "el_l": (-40, -100), "el_r": (40, -100),
        "hd_l": (-28, -20), "hd_r": (28, -20),
        "hp_l": (-28, 8), "hp_r": (28, 8),
        "kn_l": (10, 110), "kn_r": (70, 110),
        "ft_l": (-10, 230), "ft_r": (90, 230),
    },
    "walk": {  # basis; kaki/tangan dianimasikan di _walk_offsets
        "head": (0, -268), "neck": (0, -210),
        "sh_l": (-46, -200), "sh_r": (46, -200),
        "el_l": (-70, -100), "el_r": (90, -130),
        "hd_l": (-60, -20), "hd_r": (100, -40),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-50, 120), "kn_r": (40, 110),
        "ft_l": (-60, 242), "ft_r": (50, 230),
    },
    "shrug": {
        "head": (0, -260), "neck": (0, -205),
        "sh_l": (-60, -220), "sh_r": (60, -220),
        "el_l": (-120, -160), "el_r": (120, -160),
        "hd_l": (-150, -120), "hd_r": (150, -120),
        "hp_l": (-26, 8), "hp_r": (26, 8),
        "kn_l": (-32, 118), "kn_r": (32, 118),
        "ft_l": (-36, 242), "ft_r": (36, 242),
    },
    "sit": {
        "head": (0, -200), "neck": (0, -150),
        "sh_l": (-48, -140), "sh_r": (48, -140),
        "el_l": (-70, -60), "el_r": (70, -60),
        "hd_l": (-55, 10), "hd_r": (55, 10),
        "hp_l": (-30, 70), "hp_r": (30, 70),
        "kn_l": (-20, 70), "kn_r": (80, 70),
        "ft_l": (-30, 160), "ft_r": (110, 160),
    },
}

SKIN = (245, 230, 210, 255)
LINE = (232, 238, 246, 255)
LINE_DARK = (15, 22, 34, 255)
SHIRT = (242, 140, 40, 255)
SHIRT_DK = (200, 100, 20, 255)
SHOE = (30, 40, 55, 255)
LAPTOP = (40, 50, 70, 255)
SCREEN = (160, 210, 255, 230)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_pt(a, b, t):
    return (_lerp(a[0], b[0], t), _lerp(a[1], b[1], t))


def resolve_pose(pose: str, phase: float) -> dict[str, tuple[float, float]]:
    pose = pose if pose in POSES else "idle"
    pts = dict(POSES[pose])
    breath = math.sin(phase * 2 * math.pi) * 5
    for k in ("head", "neck", "sh_l", "sh_r"):
        x, y = pts[k]
        pts[k] = (x, y + breath)
    if pose == "walk":
        swing = math.sin(phase * 2 * math.pi)
        pts["kn_l"] = (pts["kn_l"][0] - 8 * swing, pts["kn_l"][1] - 8 * abs(swing))
        pts["kn_r"] = (pts["kn_r"][0] + 8 * swing, pts["kn_r"][1] - 8 * abs(-swing))
        pts["ft_l"] = (pts["ft_l"][0] - 22 * swing, pts["ft_l"][1] - 16 * max(0, swing))
        pts["ft_r"] = (pts["ft_r"][0] + 22 * swing, pts["ft_r"][1] - 16 * max(0, -swing))
        pts["hd_l"] = (pts["hd_l"][0] + 18 * swing, pts["hd_l"][1])
        pts["hd_r"] = (pts["hd_r"][0] - 18 * swing, pts["hd_r"][1])
        bounce = abs(math.sin(phase * 2 * math.pi)) * 6
        for k in pts:
            pts[k] = (pts[k][0], pts[k][1] - bounce)
    if pose == "typing":
        # jari "mengetik"
        tap = math.sin(phase * 8 * math.pi) * 6
        pts["hd_l"] = (pts["hd_l"][0], pts["hd_l"][1] + tap)
        pts["hd_r"] = (pts["hd_r"][0], pts["hd_r"][1] - tap)
    if pose == "cheer":
        wiggle = math.sin(phase * 4 * math.pi) * 8
        pts["hd_l"] = (pts["hd_l"][0] - wiggle, pts["hd_l"][1] + wiggle * 0.4)
        pts["hd_r"] = (pts["hd_r"][0] + wiggle, pts["hd_r"][1] + wiggle * 0.4)
    return pts


def _thick_line(d: ImageDraw.ImageDraw, a, b, fill, width: int) -> None:
    d.line([a, b], fill=fill, width=width)
    r = max(1, width // 2)
    for p in (a, b):
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=fill)


def draw_stickman(canvas: Image.Image, cx: int, cy: int, pose: str, phase: float, scale: float = 1.0) -> None:
    """Gambar stickman di canvas RGBA/RGB. (cx, cy) = pinggul."""
    pts = resolve_pose(pose, phase)
    # gambar di layer 2× lalu paste
    mul = 2
    w, h = 900 * mul, 1400 * mul
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = w // 2, int(h * 0.62)

    def P(name: str) -> tuple[int, int]:
        x, y = pts[name]
        return int(ox + x * mul * scale), int(oy + y * mul * scale)

    lw = int(15 * mul * scale)
    # bayangan kaki
    ft_l, ft_r = P("ft_l"), P("ft_r")
    shadow_y = max(ft_l[1], ft_r[1]) + 8
    d.ellipse((ox - 140, shadow_y - 22, ox + 140, shadow_y + 28), fill=(0, 0, 0, 60))

    # kursi untuk sit
    if pose == "sit":
        seat = (ox - 90, oy + 40, ox + 160, oy + 90)
        d.rounded_rectangle(seat, radius=12, fill=(25, 40, 60, 230), outline=LINE_DARK, width=4)
        d.rectangle((ox + 130, oy - 80, ox + 160, oy + 90), fill=(25, 40, 60, 230))

    # kaki
    _thick_line(d, P("hp_l"), P("kn_l"), LINE, lw)
    _thick_line(d, P("kn_l"), P("ft_l"), LINE, lw)
    _thick_line(d, P("hp_r"), P("kn_r"), LINE, lw)
    _thick_line(d, P("kn_r"), P("ft_r"), LINE, lw)
    # sepatu
    for ft in (ft_l, ft_r):
        d.ellipse((ft[0] - 22, ft[1] - 12, ft[0] + 34, ft[1] + 18), fill=SHOE)

    # baju (badan)
    sh_l, sh_r = P("sh_l"), P("sh_r")
    hip_mid = ((P("hp_l")[0] + P("hp_r")[0]) // 2, (P("hp_l")[1] + P("hp_r")[1]) // 2)
    shirt_pts = [
        (sh_l[0] - 16, sh_l[1] - 8),
        (sh_r[0] + 16, sh_r[1] - 8),
        (hip_mid[0] + 50, hip_mid[1] + 10),
        (hip_mid[0] - 50, hip_mid[1] + 10),
    ]
    d.polygon(shirt_pts, fill=SHIRT)
    # garis bahu
    _thick_line(d, sh_l, sh_r, SHIRT_DK, max(8, lw // 2))

    # lengan
    _thick_line(d, sh_l, P("el_l"), LINE, lw)
    _thick_line(d, P("el_l"), P("hd_l"), LINE, lw)
    _thick_line(d, sh_r, P("el_r"), LINE, lw)
    _thick_line(d, P("el_r"), P("hd_r"), LINE, lw)
    for hd in (P("hd_l"), P("hd_r")):
        d.ellipse((hd[0] - 16, hd[1] - 16, hd[0] + 16, hd[1] + 16), fill=SKIN, outline=LINE_DARK, width=3)

    # laptop untuk typing
    if pose == "typing":
        lx, ly = ox - 90, oy - 10
        d.rounded_rectangle((lx, ly, lx + 180, ly + 110), radius=10, fill=LAPTOP)
        d.rounded_rectangle((lx + 14, ly + 12, lx + 166, ly + 80), radius=6, fill=SCREEN)

    # kepala
    hx, hy = P("head")
    hr = int(52 * mul * scale * 0.55)
    d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=SKIN, outline=LINE_DARK, width=max(4, lw // 3))
    # mata (kedip)
    blink = abs(math.sin(phase * 2 * math.pi * 0.35)) < 0.06
    eye_y = hy - 4
    eye_r = 7 if not blink else 2
    for dx in (-16, 16):
        d.ellipse((hx + dx - eye_r, eye_y - eye_r, hx + dx + eye_r, eye_y + (2 if blink else eye_r)), fill=LINE_DARK)
    # senyum kecil
    d.arc((hx - 18, hy + 6, hx + 18, hy + 28), 20, 160, fill=LINE_DARK, width=4)

    # leher
    _thick_line(d, P("neck"), (hx, hy + hr - 4), SKIN, max(10, lw // 2))

    # downsample
    layer = layer.resize((w // mul, h // mul), Image.Resampling.LANCZOS)
    px = int(cx - (w // mul) / 2)
    py = int(cy - (h // mul) * 0.62)
    canvas.paste(layer, (px, py), layer)


@lru_cache(maxsize=64)
def pose_frame(pose: str, frame_i: int, n: int = 16, scale: int = 100) -> Image.Image:
    """Sprite RGBA 900×1400 untuk cache loop animasi."""
    img = Image.new("RGBA", (900, 1400), (0, 0, 0, 0))
    # pinggul di tengah-bawah sprite
    draw_stickman(img, 450, 900, pose, frame_i / max(1, n), scale=scale / 100.0)
    return img
