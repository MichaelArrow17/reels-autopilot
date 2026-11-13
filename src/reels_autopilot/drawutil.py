"""Utilitas gambar bersama: font, teks muat, pil, kartu, area aman Reels."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reels_autopilot.config import Settings, TARGET_HEIGHT, TARGET_WIDTH, get_settings

# Area aman: jauh dari UI IG (atas username, bawah tombol).
SAFE_LEFT = 72
SAFE_RIGHT = TARGET_WIDTH - 72
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT
SAFE_TOP = 170
SAFE_BOTTOM = 1680
MAIN_TOP = 230
MAIN_BOTTOM = 1500


def font_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
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
    path = font_path(settings)
    font = ImageFont.truetype(str(path), size=max(8, int(size)))
    try:
        font.set_variation_by_axes([min(32, max(14, size * 0.3)), float(weight)])
    except Exception:
        pass
    return font


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def with_alpha(color: tuple[int, ...], a: int) -> tuple[int, ...]:
    rgb = tuple(color[:3])
    return (*rgb, int(max(0, min(255, a))))


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


def _truncate(line: str, font: ImageFont.ImageFont, max_w: int) -> str:
    if font.getlength(line) <= max_w:
        return line
    ell = "…"
    for n in range(len(line), 0, -1):
        s = line[:n].rstrip() + ell
        if font.getlength(s) <= max_w:
            return s
    return ell


def fit_text(
    text: str,
    *,
    max_width: int,
    max_height: int,
    max_size: int,
    min_size: int = 22,
    weight: int = 700,
    max_lines: int = 6,
    settings: Settings | None = None,
) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Kembalikan (baris, font, ukuran) yang muat di kotak. Tidak pernah overflow."""
    text = (text or "").strip()
    if not text:
        font = load_font(min_size, weight, settings)
        return [""], font, min_size
    size = max_size
    font = load_font(size, weight, settings)
    lines = wrap_words(text, font, max_width)
    line_h = int(size * 1.18)
    while size > min_size and (len(lines) > max_lines or len(lines) * line_h > max_height):
        size -= 2
        font = load_font(size, weight, settings)
        lines = wrap_words(text, font, max_width)
        line_h = int(size * 1.18)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _truncate(lines[-1], font, max_width)
    # jika satu kata lebih lebar dari max_width
    lines = [_truncate(ln, font, max_width) for ln in lines]
    return lines, font, size


def text_size(text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    if hasattr(font, "getbbox"):
        b = font.getbbox(text or " ")
        return int(b[2] - b[0]), int(b[3] - b[1])
    return int(font.getlength(text or " ")), int(getattr(font, "size", 24))


def draw_centered_lines(
    dr: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.ImageFont,
    *,
    cx: int,
    y: int,
    fill,
    line_h: int | None = None,
    stroke_width: int = 0,
    stroke_fill=None,
) -> tuple[int, int, int, int]:
    """Gambar baris terpusat. Kembalikan bbox (l, t, r, b)."""
    if not lines:
        return (cx, y, cx, y)
    size = getattr(font, "size", 40)
    lh = line_h or int(size * 1.18)
    widths = [font.getlength(ln) for ln in lines]
    max_w = max(widths) if widths else 0
    top = y
    for i, ln in enumerate(lines):
        x = cx - widths[i] / 2
        kwargs = {"font": font, "fill": fill}
        if stroke_width:
            kwargs["stroke_width"] = stroke_width
            kwargs["stroke_fill"] = stroke_fill or (0, 0, 0)
        dr.text((x, y), ln, **kwargs)
        y += lh
    return (int(cx - max_w / 2), int(top), int(cx + max_w / 2), int(y))


def draw_words_colored(
    dr: ImageDraw.ImageDraw,
    items: list[tuple[str, tuple[int, ...], ImageFont.ImageFont]],
    *,
    cx: int,
    y: int,
    max_width: int,
    gap: int = 16,
    align: str = "center",
) -> tuple[int, int, int, int]:
    """Gambar rangkaian kata berwarna, bungkus jika perlu. items: (kata, warna, font)."""
    if not items:
        return (cx, y, cx, y)
    # pecah ke baris
    rows: list[list[tuple[str, tuple[int, ...], ImageFont.ImageFont, float]]] = [[]]
    row_w = 0.0
    for word, color, font in items:
        w = font.getlength(word)
        extra = gap if rows[-1] else 0
        if rows[-1] and row_w + extra + w > max_width:
            rows.append([(word, color, font, w)])
            row_w = w
        else:
            rows[-1].append((word, color, font, w))
            row_w += extra + w
    # tinggi baris
    max_size = max(getattr(f, "size", 40) for _, _, f in items)
    lh = int(max_size * 1.2)
    top = y
    max_row = 0.0
    for row in rows:
        total = sum(w for *_, w in row) + gap * (len(row) - 1)
        max_row = max(max_row, total)
        x = cx - total / 2 if align == "center" else (cx if align == "left" else cx - total)
        for word, color, font, w in row:
            dr.text((x, y), word, font=font, fill=color)
            x += w + gap
        y += lh
    return (int(cx - max_row / 2), int(top), int(cx + max_row / 2), int(y))


def rounded_rect(
    img: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 0,
    shadow: int = 0,
    shadow_color=(0, 0, 0, 50),
) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        return
    if shadow:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle(
            (x0 + 4, y0 + 6, x1 + 4, y1 + 8), radius=radius, fill=shadow_color
        )
        layer = layer.filter(ImageFilter.GaussianBlur(min(12, shadow)))
        base = img.convert("RGBA")
        img_rgba = Image.alpha_composite(base, layer)
        img.paste(img_rgba.convert(img.mode))
    dr = ImageDraw.Draw(img)
    kwargs = {"fill": fill}
    if outline is not None and width:
        kwargs["outline"] = outline
        kwargs["width"] = width
    dr.rounded_rectangle((x0, y0, x1, y1), radius=radius, **kwargs)


def draw_pill(
    img: Image.Image,
    text: str,
    *,
    cx: int,
    y: int,
    font: ImageFont.ImageFont,
    fill,
    text_fill,
    pad_x: int = 28,
    pad_y: int = 12,
    radius: int | None = None,
    outline=None,
    outline_w: int = 0,
    scale: float = 1.0,
) -> tuple[int, int, int, int]:
    tw = font.getlength(text)
    th = getattr(font, "size", 28)
    w = int((tw + pad_x * 2) * scale)
    h = int((th + pad_y * 2) * scale)
    x0 = int(cx - w / 2)
    y0 = int(y)
    r = radius if radius is not None else h // 2
    rounded_rect(img, (x0, y0, x0 + w, y0 + h), r, fill, outline=outline, width=outline_w)
    dr = ImageDraw.Draw(img)
    # vertikal hampir tengah
    ty = y0 + (h - th) / 2 - th * 0.12
    dr.text((cx - tw * scale / 2, ty), text, font=font, fill=text_fill)
    return (x0, y0, x0 + w, y0 + h)


def blit(dest: Image.Image, src: Image.Image, xy: tuple[int, int], *, alpha: float = 1.0, scale: float = 1.0) -> None:
    if src is None:
        return
    im = src
    if scale != 1.0 and scale > 0:
        nw = max(1, int(im.width * scale))
        nh = max(1, int(im.height * scale))
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    if alpha < 0.99:
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        a = im.split()[-1].point(lambda p: int(p * max(0.0, min(1.0, alpha))))
        im = im.copy()
        im.putalpha(a)
    if im.mode == "RGBA":
        dest.paste(im, (int(xy[0]), int(xy[1])), im)
    else:
        dest.paste(im, (int(xy[0]), int(xy[1])))


def make_blob_sprite(radius: int, color: tuple[int, int, int], alpha: int = 70, blur: int = 40) -> Image.Image:
    s = (radius + blur) * 2
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(
        (blur, blur, s - blur, s - blur), fill=(*color[:3], alpha)
    )
    return layer.filter(ImageFilter.GaussianBlur(blur))


def assert_bbox_in_safe(
    bbox: tuple[int, int, int, int],
    *,
    left: int = SAFE_LEFT,
    right: int = SAFE_RIGHT,
    top: int = SAFE_TOP,
    bottom: int = SAFE_BOTTOM,
    pad: int = 0,
) -> list[str]:
    """Kembalikan daftar pelanggaran overflow (kosong = lolos)."""
    l, t, r, b = bbox
    errors = []
    if l < left - pad:
        errors.append(f"overflow kiri {l} < {left}")
    if r > right + pad:
        errors.append(f"overflow kanan {r} > {right}")
    if t < top - pad:
        errors.append(f"overflow atas {t} < {top}")
    if b > bottom + pad:
        errors.append(f"overflow bawah {b} > {bottom}")
    return errors
