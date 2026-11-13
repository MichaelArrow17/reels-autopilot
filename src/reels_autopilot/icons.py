"""Ikon vektor flat prosedural (tanpa aset pihak ketiga)."""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# nama kanonis
ICON_NAMES = (
    "check", "close", "x", "warning", "lightbulb", "lock", "unlock", "shield",
    "chart", "wallet", "robot", "chat", "search", "user", "clock", "arrow",
    "coin", "heart", "star", "book", "gear", "cloud", "link", "phone",
    "calendar", "document", "megaphone", "house", "building", "scale",
    "flame", "flag", "wifi", "key", "folder", "play", "save", "thumbs_up",
    "thumbs_down", "question", "info", "brain", "laptop", "globe", "bell",
    "camera", "mic", "spark", "list", "target",
)


def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img, "RGBA")


def _stroke(size: int) -> int:
    return max(2, int(size * 0.08))


@lru_cache(maxsize=256)
def draw_icon(
    name: str,
    size: int = 160,
    color: tuple[int, int, int] = (20, 22, 28),
    fill: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Gambar ikon RGBA `size`×`size`. Nama tidak dikenal → lingkaran tanda tanya."""
    name = (name or "question").lower().strip().replace("-", "_")
    aliases = {"x": "close", "cross": "close", "tick": "check", "cek": "check",
               "lampu": "lightbulb", "hp": "phone", "dokumen": "document",
               "kalender": "calendar", "centang": "check", "peringatan": "warning",
               "otak": "brain", "uang": "wallet", "grafik": "chart", "lintas": "close"}
    name = aliases.get(name, name)
    fn = _DRAW.get(name, _draw_question)
    try:
        return fn(size, color, fill)
    except Exception:
        return _draw_question(size, color, fill)


def _draw_check(size, color, fill):
    img, d = _canvas(size)
    bg = fill or (15, 160, 95)
    pad = int(size * 0.06)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*bg, 255))
    sw = max(3, int(size * 0.12))
    p1 = (size * 0.28, size * 0.52)
    p2 = (size * 0.44, size * 0.70)
    p3 = (size * 0.74, size * 0.34)
    d.line([p1, p2, p3], fill=(255, 255, 255, 255), width=sw, joint="curve")
    r = sw // 2
    for p in (p1, p2, p3):
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=(255, 255, 255, 255))
    return img


def _draw_close(size, color, fill):
    img, d = _canvas(size)
    bg = fill or (230, 57, 70)
    pad = int(size * 0.06)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*bg, 255))
    sw = max(3, int(size * 0.12))
    m = int(size * 0.32)
    d.line((m, m, size - m, size - m), fill=(255, 255, 255, 255), width=sw)
    d.line((size - m, m, m, size - m), fill=(255, 255, 255, 255), width=sw)
    return img


def _draw_warning(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 180, 20)
    d.polygon(
        [(size * 0.5, size * 0.08), (size * 0.92, size * 0.88), (size * 0.08, size * 0.88)],
        fill=(*c, 255),
    )
    sw = max(2, int(size * 0.08))
    d.line((size * 0.5, size * 0.34, size * 0.5, size * 0.60), fill=(40, 30, 10, 255), width=sw)
    r = max(3, int(size * 0.05))
    d.ellipse((size * 0.5 - r, size * 0.70 - r, size * 0.5 + r, size * 0.70 + r), fill=(40, 30, 10, 255))
    return img


def _draw_lightbulb(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.ellipse((size * 0.22, size * 0.08, size * 0.78, size * 0.64), fill=(*c, 255))
    d.rectangle((size * 0.38, size * 0.58, size * 0.62, size * 0.72), fill=(*c, 255))
    d.rounded_rectangle((size * 0.36, size * 0.70, size * 0.64, size * 0.86), radius=4, fill=(160, 160, 165, 255))
    d.line((size * 0.40, size * 0.90, size * 0.60, size * 0.90), fill=(160, 160, 165, 255), width=max(2, int(size * 0.05)))
    return img


def _draw_lock(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.arc((size * 0.28, size * 0.14, size * 0.72, size * 0.58), 180, 0, fill=(*c, 255), width=sw)
    d.rounded_rectangle((size * 0.22, size * 0.42, size * 0.78, size * 0.90), radius=int(size * 0.08), fill=(*c, 255))
    r = max(3, int(size * 0.07))
    d.ellipse((size * 0.5 - r, size * 0.60 - r, size * 0.5 + r, size * 0.60 + r), fill=(255, 255, 255, 230))
    d.rectangle((size * 0.47, size * 0.62, size * 0.53, size * 0.78), fill=(255, 255, 255, 230))
    return img


def _draw_unlock(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.arc((size * 0.36, size * 0.10, size * 0.84, size * 0.52), 200, 20, fill=(*c, 255), width=sw)
    d.rounded_rectangle((size * 0.22, size * 0.42, size * 0.78, size * 0.90), radius=int(size * 0.08), fill=(*c, 255))
    return img


def _draw_shield(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.polygon(
        [
            (size * 0.5, size * 0.08),
            (size * 0.88, size * 0.26),
            (size * 0.82, size * 0.62),
            (size * 0.5, size * 0.92),
            (size * 0.18, size * 0.62),
            (size * 0.12, size * 0.26),
        ],
        fill=(*c, 255),
    )
    # check kecil
    sw = max(3, int(size * 0.08))
    d.line([(size * 0.34, size * 0.50), (size * 0.46, size * 0.64), (size * 0.70, size * 0.36)],
           fill=(255, 255, 255, 255), width=sw, joint="curve")
    return img


def _draw_chart(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    # 3 batang
    d.rounded_rectangle((size * 0.16, size * 0.52, size * 0.34, size * 0.86), radius=4, fill=(*c, 180))
    d.rounded_rectangle((size * 0.40, size * 0.32, size * 0.58, size * 0.86), radius=4, fill=(*c, 220))
    d.rounded_rectangle((size * 0.64, size * 0.18, size * 0.82, size * 0.86), radius=4, fill=(*c, 255))
    d.line((size * 0.10, size * 0.88, size * 0.90, size * 0.88), fill=(*c, 200), width=max(2, int(size * 0.04)))
    return img


def _draw_wallet(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.12, size * 0.30, size * 0.88, size * 0.86), radius=int(size * 0.08), fill=(*c, 255))
    d.rounded_rectangle((size * 0.12, size * 0.22, size * 0.70, size * 0.40), radius=6, fill=(*c, 220))
    r = int(size * 0.08)
    d.ellipse((size * 0.64, size * 0.50, size * 0.64 + r * 2, size * 0.50 + r * 2), fill=(255, 210, 80, 255))
    return img


def _draw_robot(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.18, size * 0.22, size * 0.82, size * 0.78), radius=int(size * 0.1), fill=(*c, 255))
    d.rectangle((size * 0.46, size * 0.10, size * 0.54, size * 0.22), fill=(*c, 255))
    d.ellipse((size * 0.44, size * 0.04, size * 0.56, size * 0.16), fill=(*c, 255))
    eye = (255, 255, 255, 255)
    d.rounded_rectangle((size * 0.28, size * 0.38, size * 0.46, size * 0.54), radius=4, fill=eye)
    d.rounded_rectangle((size * 0.54, size * 0.38, size * 0.72, size * 0.54), radius=4, fill=eye)
    d.rounded_rectangle((size * 0.34, size * 0.62, size * 0.66, size * 0.70), radius=3, fill=eye)
    return img


def _draw_chat(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.12, size * 0.12, size * 0.88, size * 0.68), radius=int(size * 0.12), fill=(*c, 255))
    d.polygon([(size * 0.30, size * 0.66), (size * 0.22, size * 0.90), (size * 0.50, size * 0.66)], fill=(*c, 255))
    for i, x in enumerate((0.28, 0.46, 0.64)):
        d.ellipse((size * x, size * 0.34, size * (x + 0.12), size * 0.46), fill=(255, 255, 255, 255))
    return img


def _draw_search(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.ellipse((size * 0.16, size * 0.16, size * 0.68, size * 0.68), outline=(*c, 255), width=sw)
    d.line((size * 0.58, size * 0.58, size * 0.86, size * 0.86), fill=(*c, 255), width=sw)
    return img


def _draw_user(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.ellipse((size * 0.30, size * 0.10, size * 0.70, size * 0.50), fill=(*c, 255))
    d.pieslice((size * 0.14, size * 0.48, size * 0.86, size * 1.10), 180, 0, fill=(*c, 255))
    return img


def _draw_clock(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = max(2, int(size * 0.07))
    pad = int(size * 0.08)
    d.ellipse((pad, pad, size - pad, size - pad), outline=(*c, 255), width=sw)
    d.line((size * 0.5, size * 0.5, size * 0.5, size * 0.28), fill=(*c, 255), width=sw)
    d.line((size * 0.5, size * 0.5, size * 0.70, size * 0.58), fill=(*c, 255), width=sw)
    return img


def _draw_arrow(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.line((size * 0.16, size * 0.5, size * 0.78, size * 0.5), fill=(*c, 255), width=sw)
    d.polygon(
        [(size * 0.70, size * 0.28), (size * 0.92, size * 0.5), (size * 0.70, size * 0.72)],
        fill=(*c, 255),
    )
    return img


def _draw_coin(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 186, 40)
    pad = int(size * 0.08)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*c, 255), outline=(200, 140, 20, 255), width=max(2, int(size * 0.05)))
    # Rp sederhana: batang
    sw = max(3, int(size * 0.09))
    d.line((size * 0.42, size * 0.30, size * 0.42, size * 0.70), fill=(120, 70, 10, 255), width=sw)
    d.arc((size * 0.42, size * 0.32, size * 0.70, size * 0.52), 270, 90, fill=(120, 70, 10, 255), width=sw)
    return img


def _draw_heart(size, color, fill):
    img, d = _canvas(size)
    c = fill or (230, 57, 70)
    d.ellipse((size * 0.12, size * 0.18, size * 0.54, size * 0.62), fill=(*c, 255))
    d.ellipse((size * 0.46, size * 0.18, size * 0.88, size * 0.62), fill=(*c, 255))
    d.polygon([(size * 0.14, size * 0.46), (size * 0.5, size * 0.90), (size * 0.86, size * 0.46)], fill=(*c, 255))
    return img


def _draw_star(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 186, 40)
    import math
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        r = size * (0.44 if i % 2 == 0 else 0.18)
        pts.append((size * 0.5 + r * math.cos(ang), size * 0.5 - r * math.sin(ang)))
    d.polygon(pts, fill=(*c, 255))
    return img


def _draw_book(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.18, size * 0.14, size * 0.86, size * 0.88), radius=6, fill=(*c, 255))
    d.rectangle((size * 0.18, size * 0.14, size * 0.30, size * 0.88), fill=(max(0, c[0] - 40), max(0, c[1] - 40), max(0, c[2] - 40), 255))
    for y in (0.32, 0.46, 0.60):
        d.line((size * 0.38, size * y, size * 0.76, size * y), fill=(255, 255, 255, 200), width=max(2, int(size * 0.04)))
    return img


def _draw_gear(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    import math
    cx = cy = size / 2
    outer, inner, hole = size * 0.42, size * 0.28, size * 0.14
    pts = []
    teeth = 8
    for i in range(teeth * 2):
        ang = i * math.pi / teeth - math.pi / 2
        r = outer if i % 2 == 0 else inner
        # flatter teeth
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d.polygon(pts, fill=(*c, 255))
    d.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=(0, 0, 0, 0))
    # punch hole by drawing center transparent — composite
    hole_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(hole_img).ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=(0, 0, 0, 255))
    # use hole as mask to clear
    clear = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img = Image.composite(clear, img, hole_img)
    return img


def _draw_cloud(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.ellipse((size * 0.10, size * 0.42, size * 0.48, size * 0.80), fill=(*c, 255))
    d.ellipse((size * 0.32, size * 0.28, size * 0.72, size * 0.70), fill=(*c, 255))
    d.ellipse((size * 0.54, size * 0.44, size * 0.90, size * 0.82), fill=(*c, 255))
    d.rounded_rectangle((size * 0.16, size * 0.54, size * 0.84, size * 0.82), radius=10, fill=(*c, 255))
    return img


def _draw_link(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.arc((size * 0.10, size * 0.28, size * 0.58, size * 0.72), 40, 320, fill=(*c, 255), width=sw)
    d.arc((size * 0.42, size * 0.28, size * 0.90, size * 0.72), 220, 140, fill=(*c, 255), width=sw)
    return img


def _draw_phone(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.28, size * 0.08, size * 0.72, size * 0.92), radius=int(size * 0.1), fill=(*c, 255))
    inner = (240, 244, 248, 255)
    d.rounded_rectangle((size * 0.34, size * 0.16, size * 0.66, size * 0.76), radius=6, fill=inner)
    d.rounded_rectangle((size * 0.44, size * 0.80, size * 0.56, size * 0.86), radius=4, fill=(220, 220, 220, 255))
    return img


def _draw_calendar(size, color, fill):
    img, d = _canvas(size)
    header = fill or (230, 57, 70)
    d.rounded_rectangle((size * 0.12, size * 0.16, size * 0.88, size * 0.90), radius=int(size * 0.08), fill=(250, 250, 252, 255), outline=(210, 210, 214, 255), width=2)
    d.rounded_rectangle((size * 0.12, size * 0.16, size * 0.88, size * 0.38), radius=int(size * 0.08), fill=(*header, 255))
    d.rectangle((size * 0.12, size * 0.28, size * 0.88, size * 0.38), fill=(*header, 255))
    # rings
    sw = max(2, int(size * 0.05))
    d.line((size * 0.32, size * 0.10, size * 0.32, size * 0.26), fill=(80, 80, 85, 255), width=sw)
    d.line((size * 0.68, size * 0.10, size * 0.68, size * 0.26), fill=(80, 80, 85, 255), width=sw)
    # dots grid
    for r in range(3):
        for c in range(4):
            x = size * (0.26 + c * 0.16)
            y = size * (0.50 + r * 0.12)
            col = (header if (r, c) == (0, 2) else (200, 202, 208))
            rr = size * 0.035
            d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(*col, 255))
    return img


def _draw_document(size, color, fill):
    img, d = _canvas(size)
    c = fill or (250, 250, 252)
    ink = color
    d.rounded_rectangle((size * 0.18, size * 0.08, size * 0.82, size * 0.92), radius=8, fill=(*c[:3], 255), outline=(*ink[:3], 80), width=2)
    # folded corner
    d.polygon([(size * 0.62, size * 0.08), (size * 0.82, size * 0.08), (size * 0.82, size * 0.28)], fill=(230, 230, 234, 255))
    for i, y in enumerate((0.40, 0.52, 0.64, 0.76)):
        w = 0.52 if i < 3 else 0.36
        d.line((size * 0.28, size * y, size * (0.28 + w), size * y), fill=(*ink[:3], 160), width=max(2, int(size * 0.045)))
    return img


def _draw_megaphone(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.polygon(
        [(size * 0.18, size * 0.42), (size * 0.18, size * 0.62), (size * 0.48, size * 0.70), (size * 0.48, size * 0.34)],
        fill=(*c, 255),
    )
    d.polygon(
        [(size * 0.48, size * 0.28), (size * 0.88, size * 0.12), (size * 0.88, size * 0.88), (size * 0.48, size * 0.72)],
        fill=(*c, 255),
    )
    d.rectangle((size * 0.14, size * 0.50, size * 0.22, size * 0.78), fill=(*c, 255))
    return img


def _draw_house(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.polygon([(size * 0.5, size * 0.10), (size * 0.92, size * 0.48), (size * 0.08, size * 0.48)], fill=(*c, 255))
    d.rounded_rectangle((size * 0.20, size * 0.46, size * 0.80, size * 0.90), radius=4, fill=(*c, 255))
    d.rounded_rectangle((size * 0.42, size * 0.62, size * 0.58, size * 0.90), radius=3, fill=(255, 255, 255, 230))
    return img


def _draw_building(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rectangle((size * 0.18, size * 0.22, size * 0.82, size * 0.90), fill=(*c, 255))
    d.polygon([(size * 0.18, size * 0.22), (size * 0.50, size * 0.06), (size * 0.82, size * 0.22)], fill=(*c, 255))
    win = (255, 255, 255, 220)
    for r in range(3):
        for col in range(3):
            x0 = size * (0.28 + col * 0.18)
            y0 = size * (0.34 + r * 0.18)
            d.rectangle((x0, y0, x0 + size * 0.10, y0 + size * 0.10), fill=win)
    return img


def _draw_scale(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.line((size * 0.5, size * 0.14, size * 0.5, size * 0.80), fill=(*c, 255), width=sw)
    d.line((size * 0.18, size * 0.32, size * 0.82, size * 0.32), fill=(*c, 255), width=sw)
    d.polygon([(size * 0.18, size * 0.32), (size * 0.05, size * 0.62), (size * 0.31, size * 0.62)], outline=(*c, 255), fill=(*c, 80), width=max(2, sw // 2))
    d.polygon([(size * 0.82, size * 0.32), (size * 0.69, size * 0.62), (size * 0.95, size * 0.62)], outline=(*c, 255), fill=(*c, 80), width=max(2, sw // 2))
    d.rectangle((size * 0.30, size * 0.80, size * 0.70, size * 0.88), fill=(*c, 255))
    return img


def _draw_flame(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 140, 40)
    d.polygon(
        [
            (size * 0.50, size * 0.08),
            (size * 0.78, size * 0.48),
            (size * 0.70, size * 0.80),
            (size * 0.50, size * 0.92),
            (size * 0.30, size * 0.80),
            (size * 0.22, size * 0.48),
        ],
        fill=(*c, 255),
    )
    inner = (255, 220, 80)
    d.polygon(
        [(size * 0.50, size * 0.40), (size * 0.62, size * 0.68), (size * 0.50, size * 0.82), (size * 0.38, size * 0.68)],
        fill=(*inner, 255),
    )
    return img


def _draw_flag(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.line((size * 0.22, size * 0.10, size * 0.22, size * 0.90), fill=(*c, 255), width=sw)
    d.polygon([(size * 0.26, size * 0.12), (size * 0.86, size * 0.32), (size * 0.26, size * 0.52)], fill=(*c, 255))
    return img


def _draw_wifi(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = max(2, int(size * 0.07))
    for i, (p, r) in enumerate(((0.55, 0.42), (0.62, 0.30), (0.72, 0.18))):
        box = (size * (0.5 - r), size * (p - r * 0.5), size * (0.5 + r), size * (p + r))
        d.arc(box, 200, 340, fill=(*c, 255), width=sw)
    rr = size * 0.06
    d.ellipse((size * 0.5 - rr, size * 0.78 - rr, size * 0.5 + rr, size * 0.78 + rr), fill=(*c, 255))
    return img


def _draw_key(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.ellipse((size * 0.12, size * 0.28, size * 0.52, size * 0.70), outline=(*c, 255), width=sw)
    d.line((size * 0.48, size * 0.50, size * 0.88, size * 0.50), fill=(*c, 255), width=sw)
    d.line((size * 0.76, size * 0.50, size * 0.76, size * 0.68), fill=(*c, 255), width=sw)
    d.line((size * 0.86, size * 0.50, size * 0.86, size * 0.62), fill=(*c, 255), width=sw)
    return img


def _draw_folder(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 186, 40)
    d.rounded_rectangle((size * 0.10, size * 0.32, size * 0.90, size * 0.86), radius=8, fill=(*c, 255))
    d.rounded_rectangle((size * 0.10, size * 0.22, size * 0.46, size * 0.40), radius=6, fill=(*c, 255))
    return img


def _draw_play(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.ellipse((size * 0.06, size * 0.06, size * 0.94, size * 0.94), fill=(*c, 255))
    d.polygon([(size * 0.40, size * 0.28), (size * 0.76, size * 0.50), (size * 0.40, size * 0.72)], fill=(255, 255, 255, 255))
    return img


def _draw_save(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.22, size * 0.10, size * 0.78, size * 0.88), radius=6, fill=(*c, 255))
    d.polygon([(size * 0.38, size * 0.10), (size * 0.62, size * 0.10), (size * 0.62, size * 0.38), (size * 0.50, size * 0.28), (size * 0.38, size * 0.38)], fill=(255, 255, 255, 230))
    return img


def _draw_thumbs_up(size, color, fill):
    img, d = _canvas(size)
    c = fill or (15, 160, 95)
    d.rounded_rectangle((size * 0.18, size * 0.46, size * 0.38, size * 0.86), radius=6, fill=(*c, 255))
    d.rounded_rectangle((size * 0.36, size * 0.40, size * 0.84, size * 0.86), radius=10, fill=(*c, 255))
    d.rounded_rectangle((size * 0.48, size * 0.14, size * 0.68, size * 0.48), radius=8, fill=(*c, 255))
    return img


def _draw_thumbs_down(size, color, fill):
    im = _draw_thumbs_up(size, color, fill or (230, 57, 70))
    return im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def _draw_question(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    pad = int(size * 0.06)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*c, 255))
    # gunakan teks "?"
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * 0.58)
        )
    except Exception:
        font = ImageFont.load_default()
    d.text((size * 0.32, size * 0.12), "?", font=font, fill=(255, 255, 255, 255))
    return img


def _draw_info(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    pad = int(size * 0.06)
    d.ellipse((pad, pad, size - pad, size - pad), fill=(*c, 255))
    sw = max(3, int(size * 0.1))
    d.line((size * 0.5, size * 0.42, size * 0.5, size * 0.74), fill=(255, 255, 255, 255), width=sw)
    r = max(3, int(size * 0.06))
    d.ellipse((size * 0.5 - r, size * 0.26 - r, size * 0.5 + r, size * 0.26 + r), fill=(255, 255, 255, 255))
    return img


def _draw_brain(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.ellipse((size * 0.12, size * 0.22, size * 0.56, size * 0.80), fill=(*c, 255))
    d.ellipse((size * 0.44, size * 0.22, size * 0.88, size * 0.80), fill=(*c, 255))
    d.arc((size * 0.18, size * 0.30, size * 0.50, size * 0.70), 200, 20, fill=(255, 255, 255, 180), width=max(2, int(size * 0.05)))
    d.arc((size * 0.50, size * 0.30, size * 0.82, size * 0.70), 160, 340, fill=(255, 255, 255, 180), width=max(2, int(size * 0.05)))
    return img


def _draw_laptop(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.16, size * 0.18, size * 0.84, size * 0.68), radius=6, fill=(*c, 255))
    d.rectangle((size * 0.22, size * 0.24, size * 0.78, size * 0.60), fill=(200, 220, 240, 255))
    d.polygon([(size * 0.10, size * 0.68), (size * 0.90, size * 0.68), (size * 0.98, size * 0.84), (size * 0.02, size * 0.84)], fill=(*c, 230))
    return img


def _draw_globe(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = max(2, int(size * 0.06))
    pad = int(size * 0.10)
    d.ellipse((pad, pad, size - pad, size - pad), outline=(*c, 255), width=sw)
    d.arc((size * 0.28, pad, size * 0.72, size - pad), 0, 360, fill=(*c, 255), width=sw)
    d.line((pad, size * 0.5, size - pad, size * 0.5), fill=(*c, 255), width=sw)
    d.arc((pad, size * 0.28, size - pad, size * 0.72), 0, 360, fill=(*c, 255), width=max(2, sw - 1))
    return img


def _draw_bell(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.pieslice((size * 0.20, size * 0.16, size * 0.80, size * 0.80), 180, 0, fill=(*c, 255))
    d.rectangle((size * 0.20, size * 0.48, size * 0.80, size * 0.68), fill=(*c, 255))
    d.ellipse((size * 0.44, size * 0.70, size * 0.56, size * 0.84), fill=(*c, 255))
    d.ellipse((size * 0.42, size * 0.10, size * 0.58, size * 0.24), fill=(*c, 255))
    return img


def _draw_camera(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    d.rounded_rectangle((size * 0.10, size * 0.32, size * 0.90, size * 0.84), radius=10, fill=(*c, 255))
    d.rounded_rectangle((size * 0.36, size * 0.20, size * 0.64, size * 0.36), radius=4, fill=(*c, 255))
    r = size * 0.16
    d.ellipse((size * 0.5 - r, size * 0.56 - r, size * 0.5 + r, size * 0.56 + r), fill=(240, 244, 250, 255))
    d.ellipse((size * 0.5 - r * 0.45, size * 0.56 - r * 0.45, size * 0.5 + r * 0.45, size * 0.56 + r * 0.45), fill=(*c, 255))
    return img


def _draw_mic(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = _stroke(size)
    d.rounded_rectangle((size * 0.38, size * 0.10, size * 0.62, size * 0.58), radius=int(size * 0.12), fill=(*c, 255))
    d.arc((size * 0.26, size * 0.32, size * 0.74, size * 0.74), 0, 180, fill=(*c, 255), width=sw)
    d.line((size * 0.50, size * 0.74, size * 0.50, size * 0.86), fill=(*c, 255), width=sw)
    d.line((size * 0.34, size * 0.86, size * 0.66, size * 0.86), fill=(*c, 255), width=sw)
    return img


def _draw_spark(size, color, fill):
    img, d = _canvas(size)
    c = fill or (242, 186, 40)
    sw = max(2, int(size * 0.07))
    d.line((size * 0.5, size * 0.08, size * 0.5, size * 0.92), fill=(*c, 255), width=sw)
    d.line((size * 0.12, size * 0.5, size * 0.88, size * 0.5), fill=(*c, 255), width=sw)
    d.line((size * 0.22, size * 0.22, size * 0.78, size * 0.78), fill=(*c, 255), width=sw)
    d.line((size * 0.78, size * 0.22, size * 0.22, size * 0.78), fill=(*c, 255), width=sw)
    return img


def _draw_list(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = max(3, int(size * 0.07))
    for i, y in enumerate((0.25, 0.50, 0.75)):
        r = size * 0.07
        d.ellipse((size * 0.14 - r, size * y - r, size * 0.14 + r, size * y + r), fill=(*c, 255))
        d.line((size * 0.30, size * y, size * 0.86, size * y), fill=(*c, 255), width=sw)
    return img


def _draw_target(size, color, fill):
    img, d = _canvas(size)
    c = fill or color
    sw = max(2, int(size * 0.06))
    cx = cy = size / 2
    for r in (0.42, 0.28, 0.15):
        d.ellipse((cx - size * r, cy - size * r, cx + size * r, cy + size * r), outline=(*c, 255), width=sw)
    rr = size * 0.06
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*c, 255))
    return img


_DRAW = {
    "check": _draw_check, "close": _draw_close, "warning": _draw_warning,
    "lightbulb": _draw_lightbulb, "lock": _draw_lock, "unlock": _draw_unlock,
    "shield": _draw_shield, "chart": _draw_chart, "wallet": _draw_wallet,
    "robot": _draw_robot, "chat": _draw_chat, "search": _draw_search,
    "user": _draw_user, "clock": _draw_clock, "arrow": _draw_arrow,
    "coin": _draw_coin, "heart": _draw_heart, "star": _draw_star,
    "book": _draw_book, "gear": _draw_gear, "cloud": _draw_cloud,
    "link": _draw_link, "phone": _draw_phone, "calendar": _draw_calendar,
    "document": _draw_document, "megaphone": _draw_megaphone, "house": _draw_house,
    "building": _draw_building, "scale": _draw_scale, "flame": _draw_flame,
    "flag": _draw_flag, "wifi": _draw_wifi, "key": _draw_key, "folder": _draw_folder,
    "play": _draw_play, "save": _draw_save, "thumbs_up": _draw_thumbs_up,
    "thumbs_down": _draw_thumbs_down, "question": _draw_question, "info": _draw_info,
    "brain": _draw_brain, "laptop": _draw_laptop, "globe": _draw_globe,
    "bell": _draw_bell, "camera": _draw_camera, "mic": _draw_mic,
    "spark": _draw_spark, "list": _draw_list, "target": _draw_target,
}


def known_icon(name: str) -> str:
    """Normalkan nama ikon; fallback 'info'."""
    n = (name or "").lower().strip().replace("-", "_")
    aliases = {"x": "close", "tick": "check", "cek": "check", "hp": "phone",
               "lampu": "lightbulb", "dokumen": "document", "kalender": "calendar",
               "centang": "check"}
    n = aliases.get(n, n)
    return n if n in _DRAW else "info"
