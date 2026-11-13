"""Gaya C: kolase scrapbook (latar solid, kertas robek, potongan foto, mesin tik)."""

from __future__ import annotations

import io
import logging
import math
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.captions import chunk_captions
from reels_autopilot.config import (
    HARD_MAX_DURATION,
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    Settings,
    get_settings,
)
from reels_autopilot.drawutil import SAFE_LEFT, SAFE_RIGHT, SAFE_WIDTH, load_font, wrap_words
from reels_autopilot.encode import encode_video
from reels_autopilot.fact_guard import validate_kolase_facts
from reels_autopilot.providers.tts import TTSResult, atempo_fit
from reels_autopilot.sfx import events_from_scene_starts, mix_events, mix_to_wav, somber_piano
from reels_autopilot.styles import STYLE_KOLASE

log = logging.getLogger("reels.kolase")

PALETTES = (
    {"bg": (46, 28, 24), "paper": (236, 224, 204), "ink": (32, 22, 18), "trace": (90, 62, 48), "accent": (196, 140, 64), "label": (248, 239, 220)},
    {"bg": (22, 36, 38), "paper": (228, 232, 220), "ink": (16, 28, 28), "trace": (58, 92, 88), "accent": (214, 180, 92), "label": (240, 244, 232)},
    {"bg": (28, 26, 46), "paper": (232, 226, 214), "ink": (24, 20, 36), "trace": (72, 64, 110), "accent": (200, 120, 90), "label": (244, 238, 226)},
    {"bg": (40, 32, 22), "paper": (240, 228, 200), "ink": (36, 26, 14), "trace": (96, 78, 46), "accent": (180, 86, 60), "label": (250, 242, 220)},
)

STRUKTUR = ("hook", "timeline", "twist", "tanya")


def _ease_push(u: float) -> float:
    u = max(0.0, min(1.0, u))
    # smoothstep
    return u * u * (3.0 - 2.0 * u)


def _pop_scale(t: float, t0: float, dur: float = 0.38) -> float:
    if t < t0:
        return 0.0
    u = (t - t0) / dur
    if u >= 1.0:
        return 1.0
    # overshoot
    return 1.12 * math.sin(u * math.pi * 0.62) / math.sin(0.62 * math.pi) if u < 0.7 else 1.0 + 0.12 * (1.0 - (u - 0.7) / 0.3)


def torn_polygon(box: tuple[int, int, int, int], rng: random.Random, jag: int = 16) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box
    pts: list[tuple[int, int]] = []

    def edge(ax, ay, bx, by, n: int) -> None:
        for i in range(n):
            u = i / n
            x = ax + (bx - ax) * u
            y = ay + (by - ay) * u
            # jags mostly inward
            nx, ny = (by - ay), (ax - bx)
            ln = math.hypot(nx, ny) or 1.0
            nx, ny = nx / ln, ny / ln
            amp = rng.uniform(0, jag) if i not in (0,) else 0
            pts.append((int(x + nx * amp), int(y + ny * amp)))

    w, h = x1 - x0, y1 - y0
    edge(x0, y0, x1, y0, max(6, w // 40))
    edge(x1, y0, x1, y1, max(6, h // 50))
    edge(x1, y1, x0, y1, max(6, w // 40))
    edge(x0, y1, x0, y0, max(6, h // 50))
    return pts


def _draw_torn_paper(
    dest: Image.Image,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    rng: random.Random,
    *,
    jag: int = 18,
    shadow: bool = True,
    rotation: float = 0.0,
) -> None:
    x0, y0, x1, y1 = box
    pad = 40
    layer = Image.new("RGBA", (x1 - x0 + pad * 2, y1 - y0 + pad * 2), (0, 0, 0, 0))
    pts = torn_polygon((pad, pad, pad + (x1 - x0), pad + (y1 - y0)), rng, jag)
    if shadow:
        sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).polygon(pts, fill=(0, 0, 0, 90))
        sh = sh.filter(ImageFilter.GaussianBlur(6))
        layer.alpha_composite(sh, (4, 6))
    ImageDraw.Draw(layer).polygon(pts, fill=(*fill, 255))
    # serat kertas tipis
    dr = ImageDraw.Draw(layer)
    for _ in range(18):
        ax, ay = rng.randint(pad, pad + x1 - x0), rng.randint(pad, pad + y1 - y0)
        dr.line((ax, ay, ax + rng.randint(-30, 30), ay + rng.randint(-8, 8)), fill=(fill[0] - 18, fill[1] - 16, fill[2] - 14, 40), width=1)
    if abs(rotation) > 0.1:
        layer = layer.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False)
    dest.alpha_composite(layer, (x0 - pad, y0 - pad))


def draw_circuit_border(img: Image.Image, color: tuple[int, int, int], *, margin: int = 42, seed: int = 7) -> None:
    dr = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    rng = random.Random(seed)
    col = (*color, 170)
    pad_col = (*tuple(min(255, c + 40) for c in color), 200)
    # bingkai luar
    for t in range(2):
        m = margin + t * 10
        dr.rectangle((m, m, w - m, h - m), outline=col, width=2)
    # jejak 90 derajat di tepi
    def traces(horizontal: bool, count: int) -> None:
        for _ in range(count):
            if horizontal:
                y = rng.randint(margin - 8, margin + 28)
                if rng.random() > 0.5:
                    y = h - y
                x0 = rng.randint(margin, w // 2)
                x1 = x0 + rng.randint(40, 180)
                mid = x0 + (x1 - x0) // 2
                y2 = y + rng.choice((-18, 18, -26, 26))
                dr.line((x0, y, mid, y, mid, y2, x1, y2), fill=col, width=2)
                for x, yy in ((x0, y), (x1, y2), (mid, y)):
                    dr.ellipse((x - 3, yy - 3, x + 3, yy + 3), fill=pad_col)
            else:
                x = rng.randint(margin - 8, margin + 28)
                if rng.random() > 0.5:
                    x = w - x
                y0 = rng.randint(margin, h // 2)
                y1 = y0 + rng.randint(40, 220)
                mid = y0 + (y1 - y0) // 2
                x2 = x + rng.choice((-18, 18, -26, 26))
                dr.line((x, y0, x, mid, x2, mid, x2, y1), fill=col, width=2)
                for xx, y in ((x, y0), (x2, y1), (x, mid)):
                    dr.ellipse((xx - 3, y - 3, xx + 3, y + 3), fill=pad_col)
    traces(True, 14)
    traces(False, 16)


def approximate_cutout(im: Image.Image) -> Image.Image:
    """Hapus latar kira-kira (sudut seragam) atau potong tepi robek. rembg opsional."""
    im = im.convert("RGBA")
    try:
        from rembg import remove  # type: ignore

        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG")
        out = remove(buf.getvalue())
        cut = Image.open(io.BytesIO(out)).convert("RGBA")
        if cut.size != im.size:
            cut = cut.resize(im.size, Image.Resampling.LANCZOS)
        return cut
    except Exception:
        pass
    px = im.load()
    w, h = im.size
    corners = [px[1, 1], px[w - 2, 1], px[1, h - 2], px[w - 2, h - 2]]
    avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    # sebaran sudut: jika seragam, flood-ish by threshold
    spread = max(abs(corners[a][i] - avg[i]) for a in range(4) for i in range(3))
    if spread < 28:
        thr = 38
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if abs(r - avg[0]) < thr and abs(g - avg[1]) < thr and abs(b - avg[2]) < thr:
                    px[x, y] = (r, g, b, 0)
        im = im.filter(ImageFilter.SMOOTH)
    # tepi robek selalu, supaya potongan terasa tempelan
    mask = Image.new("L", (w, h), 0)
    rng = random.Random(w * 13 + h)
    pts = torn_polygon((8, 8, w - 8, h - 8), rng, jag=22)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(0.6))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, (0, 0))
    alpha = out.split()[-1]
    alpha = ImageChops_multiply(alpha, mask)
    out.putalpha(alpha)
    return out


def ImageChops_multiply(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops

    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.BILINEAR)
    return ImageChops.multiply(a, b)


def make_illustration(query: str, size: tuple[int, int] = (720, 960), seed: int = 11) -> Image.Image:
    """Ilustrasi buatan sendiri jika foto Commons tidak ada."""
    rng = random.Random(seed + sum(map(ord, query or "")))
    pal = PALETTES[rng.randint(0, len(PALETTES) - 1)]
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(im, "RGBA")
    w, h = size
    # siluet ukiran
    cx, cy = w // 2, int(h * 0.46)
    dr.ellipse((cx - 160, cy - 200, cx + 160, cy + 160), fill=(*pal["ink"], 230))
    dr.ellipse((cx - 90, cy - 230, cx + 90, cy - 40), fill=(*pal["paper"], 255))  # kepala
    # bahu
    dr.pieslice((cx - 200, cy + 40, cx + 200, cy + 360), 180, 0, fill=(*pal["ink"], 230))
    # stempel tahun / inisial
    initials = "".join(ch[0].upper() for ch in (query or "PC").split()[:2]) or "PC"
    try:
        font = load_font(72, 800)
    except Exception:
        font = ImageFont.load_default()
    tw = font.getlength(initials) if hasattr(font, "getlength") else 80
    dr.text(((w - tw) / 2, h * 0.78), initials, font=font, fill=(*pal["accent"], 255))
    return approximate_cutout(im)


def credit_line(assets: list[dict]) -> str:
    bits = []
    seen = set()
    for a in assets or []:
        attr = (a.get("attribution") or "").strip()
        if not attr or attr in seen:
            continue
        seen.add(attr)
        bits.append(attr)
    if not bits:
        return ""
    return "Foto: " + " · ".join(bits)


def append_credit(caption: str, credits: str) -> str:
    cap = (caption or "").rstrip()
    cred = (credits or "").strip()
    if not cred:
        return cap
    if cred.lower() in cap.lower():
        return cap
    return (cap + "\n\n" + cred).strip()


def derive_kolase(script: dict) -> dict:
    """Normalisasi bab hook/timeline/twist/tanya dan jaga angka/sumber."""
    s = dict(script or {})
    s["style"] = STYLE_KOLASE
    bab = list(s.get("bab") or s.get("adegan") or [])
    # pastikan 4 bab sesuai struktur
    by_name = {}
    for b in bab:
        if not isinstance(b, dict):
            continue
        nama = (b.get("nama") or b.get("id") or "").lower()
        if nama in STRUKTUR:
            by_name[nama] = b
        elif "hook" in nama:
            by_name.setdefault("hook", b)
        elif "twist" in nama or "balik" in nama:
            by_name.setdefault("twist", b)
        elif "tanya" in nama or "cta" in nama or "komentar" in nama:
            by_name.setdefault("tanya", b)
        elif "time" in nama or "linimasa" in nama or "sejarah" in nama:
            by_name.setdefault("timeline", b)
    # isi dari narasi jika kurang
    narasi = (s.get("narasi_penuh") or "").strip()
    parts = [p.strip() for p in re_split_sentences(narasi) if p.strip()]
    defaults_label = {
        "hook": (s.get("hook") or (parts[0] if parts else s.get("judul") or ""))[:80],
        "timeline": "LINIMASA",
        "twist": "YANG JARANG DIINGAT",
        "tanya": "TULIS DI KOMENTAR",
    }
    out_bab = []
    for i, nama in enumerate(STRUKTUR):
        b = dict(by_name.get(nama) or {})
        b["nama"] = nama
        b["label"] = (b.get("label") or b.get("teks_layar") or defaults_label[nama]).strip()
        b.setdefault("gambar_query", b.get("image_query") or "")
        b.setdefault("kata_kunci", b.get("keyword") or [])
        if isinstance(b["kata_kunci"], str):
            b["kata_kunci"] = [b["kata_kunci"]] if b["kata_kunci"] else []
        pal = PALETTES[i % len(PALETTES)]
        if not b.get("latar"):
            b["latar"] = pal["bg"]
        elif isinstance(b.get("latar"), str) and str(b["latar"]).startswith("#"):
            h = b["latar"].lstrip("#")
            if len(h) == 6:
                b["latar"] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        out_bab.append(b)
    s["bab"] = out_bab
    s["struktur"] = list(STRUKTUR)
    return s


def re_split_sentences(text: str) -> list[str]:
    import re

    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text or "") if p.strip()]


def _windows_from_script(script: dict, words: list, duration: float) -> list[tuple[float, float, dict]]:
    bab = (script.get("bab") or [])
    n = max(1, len(bab))
    # bagi durasi: hook lebih singkat, tanya sedang
    weights = {"hook": 0.18, "timeline": 0.32, "twist": 0.30, "tanya": 0.20}
    fracs = [weights.get((b.get("nama") or ""), 1.0 / n) for b in bab]
    tot = sum(fracs) or 1.0
    fracs = [f / tot for f in fracs]
    windows = []
    t = 0.0
    for b, f in zip(bab, fracs):
        end = min(duration, t + duration * f)
        windows.append((t, end, b))
        t = end
    if windows:
        a, _, b = windows[-1]
        windows[-1] = (a, duration, b)
    return windows


def _hex_or_tuple(c) -> tuple[int, int, int]:
    if isinstance(c, (tuple, list)) and len(c) >= 3:
        return int(c[0]), int(c[1]), int(c[2])
    return PALETTES[0]["bg"]


def fetch_kolase_assets(script: dict, out_dir: Path, *, settings: Settings | None = None) -> list[dict]:
    """Unduh foto Commons berlisensi atau buat ilustrasi sendiri. Catat lisensi+pembuat."""
    from reels_autopilot.providers.images import ImageClient

    settings = settings or get_settings()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ImageClient(settings)
    assets: list[dict] = []
    for i, bab in enumerate(script.get("bab") or []):
        q = (bab.get("gambar_query") or bab.get("image_query") or script.get("image_query") or script.get("subjek") or "").strip()
        rec: dict = {"query": q, "path": "", "license": "", "author": "", "source_url": "", "attribution": "", "provider": "illustration"}
        dest_stem = f"cutout_{i+1}"
        if q:
            try:
                img = client.search_commons(q, out_dir, stem=dest_stem)
                rec.update({
                    "path": str(img.path),
                    "license": img.license,
                    "author": img.photographer,
                    "source_url": img.source_url,
                    "attribution": img.attribution,
                    "provider": img.provider_id,
                })
            except Exception as e:
                log.info("Commons gagal (%s): %s — ilustrasi sendiri", q, e)
            time.sleep(0.6)
        if not rec["path"]:
            ill = make_illustration(q or script.get("judul") or "Po Chai", seed=20 + i)
            path = out_dir / f"{dest_stem}_ill.png"
            ill.save(path, "PNG")
            rec.update({
                "path": str(path),
                "license": "original",
                "author": "Po Chai",
                "source_url": "",
                "attribution": "Ilustrasi: Po Chai (karya sendiri)",
                "provider": "illustration",
            })
        # siapkan cutout RGBA
        try:
            raw = Image.open(rec["path"])
            cut = approximate_cutout(raw)
            cut_path = out_dir / f"{dest_stem}_cut.png"
            cut.save(cut_path, "PNG")
            rec["cutout"] = str(cut_path)
        except Exception as e:
            log.info("cutout gagal: %s", e)
            rec["cutout"] = rec["path"]
        bab["asset"] = rec
        assets.append(rec)
    script["gambar"] = assets
    script["credits"] = credit_line([a for a in assets if a.get("provider") == "wikimedia"])
    if not script["credits"]:
        # tetap catat ilustrasi sendiri bila tidak ada foto
        script["credits"] = ""
    return assets


def _typewriter_n(text: str, t: float, t0: float, cps: float = 18.0) -> int:
    if t < t0:
        return 0
    n = int((t - t0) * cps)
    return max(0, min(len(text), n))


def _prepare_cutout(path: str | Path, max_h: int = 980) -> Image.Image | None:
    p = Path(path) if path else None
    if not p or not p.exists():
        return None
    im = Image.open(p).convert("RGBA")
    if im.height > max_h:
        ratio = max_h / im.height
        im = im.resize((max(1, int(im.width * ratio)), max_h), Image.Resampling.LANCZOS)
    return im


def render_kolase_scene(
    bab: dict,
    t: float,
    start: float,
    duration: float,
    words,
    chunks,
    fonts: dict,
    pal: dict,
) -> Image.Image:
    bg = _hex_or_tuple(bab.get("latar") or pal["bg"])
    img = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (*bg, 255))
    draw_circuit_border(img, pal["trace"], seed=hash(bab.get("nama") or "x") % 997)
    rng = random.Random(hash(bab.get("nama") or "x") % 10_000)

    # potongan foto
    asset = bab.get("asset") or {}
    cut = _prepare_cutout(asset.get("cutout") or asset.get("path") or "")
    pop_t = start + 0.12
    sc = _pop_scale(t, pop_t)
    if cut is not None and sc > 0:
        cw, ch = cut.size
        cut2 = cut.resize((max(1, int(cw * sc)), max(1, int(ch * sc))), Image.Resampling.LANCZOS)
        x = (TARGET_WIDTH - cut2.width) // 2
        y = 280 + int((1.0 - min(1.0, sc)) * 40)
        # sedikit miring
        tilt = -3 if (bab.get("nama") == "hook") else (2 if bab.get("nama") == "twist" else 0)
        if tilt:
            cut2 = cut2.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True)
        img.alpha_composite(cut2, (x, y))

    # label kertas robek + mesin tik
    label = (bab.get("label") or "").strip()
    if label:
        n = _typewriter_n(label, t, start + 0.2, cps=22.0)
        shown = label[:n]
        cursor = "_" if (int(t * 4) % 2 == 0 and n < len(label)) else ""
        text = shown + cursor
        font: ImageFont.ImageFont = fonts["label"]
        lines = wrap_words(text or " ", font, SAFE_WIDTH - 80)
        line_h = 64
        box_h = max(120, 50 + line_h * len(lines))
        box = (SAFE_LEFT, 1380, SAFE_RIGHT, min(TARGET_HEIGHT - 180, 1380 + box_h))
        _draw_torn_paper(img, box, pal["label"], rng, jag=14, rotation=rng.uniform(-1.2, 1.2))
        dr = ImageDraw.Draw(img)
        y = box[1] + 28
        for ln in lines:
            tw = font.getlength(ln)
            dr.text(((TARGET_WIDTH - tw) / 2, y), ln, font=font, fill=pal["ink"])
            y += line_h

    # nama bab kecil di atas
    dr = ImageDraw.Draw(img)
    chapter = {"hook": "01 / HOOK", "timeline": "02 / LINIMASA", "twist": "03 / TWIST", "tanya": "04 / TANYA"}.get(bab.get("nama") or "", "")
    if chapter:
        cf = fonts["chapter"]
        tw = cf.getlength(chapter)
        pill = (int((TARGET_WIDTH - tw) / 2 - 24), 188, int((TARGET_WIDTH + tw) / 2 + 24), 242)
        _draw_torn_paper(img, pill, pal["label"], rng, jag=8, rotation=-1.0)
        dr = ImageDraw.Draw(img)
        dr.text(((TARGET_WIDTH - tw) / 2, 198), chapter, font=cf, fill=pal["ink"])

    # brand
    bf = fonts["brand"]
    dr.text((SAFE_LEFT, 1688), "Po Chai  ·  Kreator AI", font=bf, fill=(pal["label"][0], pal["label"][1], pal["label"][2], 200))
    # progress
    frac = 0 if duration <= 0 else min(1.0, max(0.0, t / duration))
    dr.rectangle((0, TARGET_HEIGHT - 8, TARGET_WIDTH, TARGET_HEIGHT), fill=(10, 8, 8, 255))
    dr.rectangle((0, TARGET_HEIGHT - 8, int(TARGET_WIDTH * frac), TARGET_HEIGHT), fill=(*pal["accent"], 255))
    return img


def render_kolase_frame(
    script: dict,
    t: float,
    duration: float,
    words,
    chunks,
    windows: list[tuple[float, float, dict]],
    fonts: dict,
) -> Image.Image:
    # transisi dorong vertikal 0.45 dtk
    push = 0.45
    idx = 0
    for i, (a, b, _sc) in enumerate(windows):
        if t >= a:
            idx = i
    a, b, bab = windows[idx] if windows else (0.0, duration, {})
    pal_i = idx % len(PALETTES)
    pal = {**PALETTES[pal_i], "bg": _hex_or_tuple(bab.get("latar") or PALETTES[pal_i]["bg"])}
    frame = render_kolase_scene(bab, t, a, duration, words, chunks, fonts, pal)
    # push masuk dari bawah di awal bab (kecuali pertama)
    if idx > 0 and t - a < push:
        prev_a, prev_b, prev = windows[idx - 1]
        ppal = {**PALETTES[(idx - 1) % len(PALETTES)], "bg": _hex_or_tuple(prev.get("latar") or PALETTES[0]["bg"])}
        prev_frame = render_kolase_scene(prev, prev_b - 0.01, prev_a, duration, words, chunks, fonts, ppal)
        u = _ease_push((t - a) / push)
        y = int(TARGET_HEIGHT * (1.0 - u))
        canvas = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0, 255))
        canvas.paste(prev_frame, (0, -int(TARGET_HEIGHT * u)))
        canvas.paste(frame, (0, y))
        return canvas
    return frame


def render_kolase(
    script: dict,
    tts: TTSResult,
    dest: Path,
    *,
    settings: Settings | None = None,
    fps: int = TARGET_FPS,
    assets_dir: Path | None = None,
) -> Path:
    settings = settings or get_settings()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    original = script
    script = derive_kolase(script)
    work = Path(assets_dir or (dest.parent / (dest.stem + "_assets")))
    if not any((b.get("asset") or {}).get("path") for b in script.get("bab") or []):
        fetch_kolase_assets(script, work, settings=settings)
    for key in ("bab", "gambar", "credits", "klaim", "style"):
        if key in script:
            original[key] = script[key]
    duration = tts.duration or 0.0
    words = list(tts.words or [])
    audio = tts.audio_path
    if duration > HARD_MAX_DURATION and audio:
        fit_dest = Path(audio).with_name(Path(audio).stem + "_fit.wav")
        audio, words, duration = atempo_fit(audio, words, duration, HARD_MAX_DURATION - 0.25, dest=fit_dest)
        log.warning("TTS kolase dipercepat ke %.1fs", duration)
    elif duration <= 0:
        duration = 1.0 / max(1, fps)
    chunks = chunk_captions(words, audio_duration=duration)
    windows = _windows_from_script(script, words, duration)
    fonts = {
        "brand": load_font(24, 600, settings),
        "chapter": load_font(26, 700, settings),
        "label": load_font(48, 650, settings),
        "caption": load_font(40, 550, settings),
    }
    ev = events_from_scene_starts(windows)
    sfx = mix_events(ev, duration, gain=0.32)
    music = somber_piano(duration, gain=0.08)
    mixed = dest.parent / (dest.stem + "_mix.wav")
    try:
        audio = mix_to_wav(
            mixed, duration,
            voice=audio, music=music, sfx=sfx,
            voice_gain=1.0, music_gain=1.0, sfx_gain=1.0,
            loudnorm_on=True,
        )
    except Exception as e:
        log.warning("campur piano kolase gagal, pakai VO: %s", e)

    n = max(1, int(round(duration * fps)))

    def frames():
        for i in range(n):
            tt = i / fps
            yield render_kolase_frame(script, tt, duration, words, chunks, windows, fonts)

    return encode_video(dest, audio, duration, frames(), fps=fps)


# ---- naskah cadangan + caption ----

KARTINI_SOURCES = (
    {
        "teks": "Kartini lahir 21 April 1879 di Jepara",
        "sumber_url": "https://www.britannica.com/biography/Raden-Adjeng-Kartini",
        "sumber_nama": "Encyclopaedia Britannica",
    },
    {
        "teks": "Surat-suratnya dalam bahasa Belanda membahas pendidikan perempuan, dan kumpulan surat terbit setelah ia wafat sebagai Door Duisternis tot Licht / Habis Gelap Terbitlah Terang",
        "sumber_url": "https://www.britannica.com/biography/Raden-Adjeng-Kartini",
        "sumber_nama": "Encyclopaedia Britannica",
    },
)

NARASI_KARTINI = (
    "Kartini menulis surat dalam bahasa Belanda, bukan merancang poster atau pidato resmi. "
    "Tapi yang kita rayakan setiap tahun adalah hari lahirnya. "
    "Ia lahir 21 April 1879 di Jepara. "
    "Dalam surat-suratnya ia membahas pendidikan bagi perempuan, pada masa akses itu masih sangat sempit. "
    "Yang jarang diingat: kumpulan surat itu baru terbit setelah ia wafat, "
    "kemudian dikenal di Indonesia sebagai Habis Gelap Terbitlah Terang. "
    "Jadi yang kita baca hari ini adalah warisan yang disusun dari surat pribadinya. "
    "Kalau Kartini hidup sekarang, menurutmu dia akan tulis tentang apa? Tulis jawabanmu di komentar."
)

CAPTION_KARTINI = """Kartini menulis surat dalam bahasa Belanda. Yang kita rayakan setiap tahun adalah hari lahirnya.

Ia lahir 21 April 1879 di Jepara. Kumpulan suratnya terbit setelah ia wafat, lalu dikenal sebagai Habis Gelap Terbitlah Terang.

Kalau Kartini hidup sekarang, menurutmu dia akan tulis tentang apa? Tulis di komentar.

#KreatorAI #PoChai #Sejarah #Kartini #ReelsIndonesia"""


def fallback_kolase(topic: dict | None = None, *, educational: bool = False) -> dict:
    """Templat aman. Profil Kartini hanya jika topik memang tentang Kartini; selain itu edukasi sumber."""
    topic = topic or {}
    blob = " ".join(
        str(topic.get(k) or "") for k in ("judul", "hook", "angle", "subjek")
    ).lower()
    if (not educational) and "kartini" in blob:
        return sample_kartini_script()
    # templat edukasi: tanpa klaim orang nyata / angka tahun
    narasi = (
        "Banyak video profil orang terkenal terdengar lancar, padahal sumbernya kosong. "
        "Kalau ada tanggal, gelar, atau jumlah, tanya dulu dari mana angkanya. "
        "Kalau tidak ada tautan resmi, jangan langsung percaya. "
        "Skandal, mundur jabatan, atau kabar duka apalagi: tanpa sumber, jangan disebar. "
        "Simpan video ini, dan kalau ada yang mau kamu cek, tulis di komentar."
    )
    script = {
        "style": STYLE_KOLASE,
        "judul": topic.get("judul") or "Jangan percaya profil tanpa sumber",
        "hook": "Banyak video profil orang terkenal terdengar lancar, padahal sumbernya kosong.",
        "angle": "Cek sumber sebelum menyebar kisah orang nyata.",
        "subjek": "",
        "bahasa": "id",
        "durasi_target_detik": 35,
        "narasi_penuh": narasi,
        "caption": (
            "Banyak video profil terdengar lancar, padahal sumbernya kosong.\n\n"
            "Kalau ada tanggal atau jumlah, tanya sumbernya. Klaim berat tanpa tautan resmi jangan disebar.\n\n"
            "Kalau ada yang mau kamu cek, tulis di komentar.\n\n"
            "#KreatorAI #PoChai #CekSumber #ReelsIndonesia"
        ),
        "cta": "Tulis di komentar kalau ada yang mau kamu cek.",
        "hashtag": ["#KreatorAI", "#PoChai", "#CekSumber", "#ReelsIndonesia"],
        "klaim": [],
        "fakta_yang_wajib_dicek": [],
        "is_ai_generated": True,
        "cover_text": "CEK SUMBER",
        "image_query": "",
        "bab": [
            {"nama": "hook", "label": "LANCAR, TAPI KOSONG?", "gambar_query": "", "kata_kunci": ["lancar"]},
            {"nama": "timeline", "label": "TANYA SUMBERNYA", "gambar_query": "", "kata_kunci": ["sumber"]},
            {"nama": "twist", "label": "TANPA TAUTAN, JANGAN SEBAR", "gambar_query": "", "kata_kunci": ["jangan"]},
            {"nama": "tanya", "label": "MAU CEK APA? TULIS DI KOMENTAR", "gambar_query": "", "kata_kunci": ["komentar"]},
        ],
        "llm_provider": "template",
    }
    return derive_kolase(script)


def sample_kartini_script() -> dict:
    script = {
        "style": STYLE_KOLASE,
        "judul": "Kartini menulis surat, bukan pidato resmi",
        "hook": "Kartini menulis surat dalam bahasa Belanda, bukan merancang poster atau pidato resmi.",
        "angle": "Hari Kartini merayakan hari lahir; kumpulan surat terbit setelah ia wafat.",
        "subjek": "Raden Ajeng Kartini",
        "bahasa": "id",
        "durasi_target_detik": 35,
        "narasi_penuh": NARASI_KARTINI,
        "caption": CAPTION_KARTINI,
        "cta": "Tulis jawabanmu di komentar.",
        "hashtag": ["#KreatorAI", "#PoChai", "#Sejarah", "#Kartini", "#ReelsIndonesia"],
        "klaim": [dict(x) for x in KARTINI_SOURCES],
        "fakta_yang_wajib_dicek": [c["teks"] for c in KARTINI_SOURCES],
        "is_ai_generated": True,
        "cover_text": "KARTINI",
        "image_query": "Kartini 1961 Indonesia stamp",
        "bab": [
            {"nama": "hook", "label": "SURAT, BUKAN PIDATO", "gambar_query": "Kartini 1961 Indonesia stamp", "kata_kunci": ["surat"]},
            {"nama": "timeline", "label": "21 APRIL 1879, JEPARA", "gambar_query": "R.A. Kartini Museum Jepara", "kata_kunci": ["1879"]},
            {"nama": "twist", "label": "TERBIT SETELAH IA WAFAT", "gambar_query": "Kartini 19 April 1947 KR", "kata_kunci": ["wafat"]},
            {"nama": "tanya", "label": "KALAU HIDUP SEKARANG? TULIS DI KOMENTAR", "gambar_query": "Raden Atjeng Kartini 9197315323", "kata_kunci": ["komentar"]},
        ],
        "llm_provider": "template",
    }
    s = derive_kolase(script)
    issues = validate_kolase_facts(s)
    if issues:
        log.warning("sampel Kartini issues: %s", issues)
    issues2 = public_caption_issues(s.get("caption") or "")
    if issues2:
        log.warning("caption Kartini: %s", issues2)
    return s


def kolase_caption(script: dict) -> str:
    cap = (script.get("caption") or "").strip()
    cred = (script.get("credits") or "").strip()
    cap = append_credit(cap, cred)
    return cap
