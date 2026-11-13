"""Gaya A — penjelas: motion graphics 2D, tipografi kinetik, ikon, perbandingan, counter."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from reels_autopilot.captions import CaptionChunk, chunk_at_time, chunk_captions
from reels_autopilot.config import (
    HARD_MAX_DURATION,
    Settings,
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    get_settings,
)
from reels_autopilot.drawutil import (
    SAFE_LEFT,
    SAFE_RIGHT,
    SAFE_WIDTH,
    blit,
    draw_centered_lines,
    draw_pill,
    draw_words_colored,
    fit_text,
    hex_rgb,
    load_font,
    make_blob_sprite,
    rounded_rect,
    wrap_words,
)
from reels_autopilot.encode import encode_video
from reels_autopilot.icons import draw_icon, known_icon
from reels_autopilot.motion import clamp, ease_out_cubic, entrance, lerp, spring_settle
from reels_autopilot.providers.tts import TTSResult, Word, atempo_fit, normalize_word_timings
from reels_autopilot.sfx import events_from_scene_starts, mix_events, mix_to_wav, soft_pad
from reels_autopilot.storyboard import derive_penjelas_visual

log = logging.getLogger("reels.penjelas")

W, H = TARGET_WIDTH, TARGET_HEIGHT

PALETTES = {
    "light": {
        "bg": (246, 244, 239),
        "grid": (226, 222, 214),
        "text": (20, 22, 26),
        "muted": (118, 122, 130),
        "red": (230, 57, 70),
        "green": (15, 155, 95),
        "accent": (242, 140, 40),
        "gold": (220, 160, 20),
        "abu": (140, 144, 150),
        "card": (255, 255, 255),
        "pill": (22, 24, 28),
        "pill_text": (255, 255, 255),
        "brand": (242, 140, 40),
        "shadow": (0, 0, 0, 35),
        "blobs": [
            ((230, 80, 90), 70, 280, 220, 200),
            ((150, 190, 230), 80, 220, 860, 500),
            ((190, 220, 190), 70, 300, 200, 1500),
            ((220, 210, 190), 60, 200, 900, 1600),
        ],
    },
    "dark": {
        "bg": (12, 16, 26),
        "grid": (30, 38, 52),
        "text": (244, 247, 251),
        "muted": (139, 163, 199),
        "red": (255, 80, 90),
        "green": (61, 220, 151),
        "accent": (242, 140, 40),
        "gold": (255, 200, 60),
        "abu": (120, 130, 145),
        "card": (28, 34, 50),
        "pill": (244, 247, 251),
        "pill_text": (16, 18, 24),
        "brand": (242, 140, 40),
        "shadow": (0, 0, 0, 80),
        "blobs": [
            ((180, 40, 50), 50, 300, 200, 300),
            ((40, 90, 160), 45, 340, 900, 1600),
            ((200, 150, 30), 40, 260, 800, 400),
            ((40, 140, 100), 35, 220, 200, 1500),
        ],
    },
}


def _kw_color(name: str, pal: dict) -> tuple[int, int, int]:
    return {
        "merah": pal["red"],
        "hijau": pal["green"],
        "emas": pal["gold"],
        "abu": pal["abu"],
        "aksen": pal["accent"],
        "red": pal["red"],
        "green": pal["green"],
        "gold": pal["gold"],
    }.get((name or "").lower(), pal["accent"])


def _base_bg(mode: str) -> Image.Image:
    pal = PALETTES[mode]
    img = Image.new("RGB", (W, H), pal["bg"])
    d = ImageDraw.Draw(img)
    step = 56
    g = pal["grid"]
    for x in range(0, W, step):
        d.line((x, 0, x, H), fill=g, width=1)
    for y in range(0, H, step):
        d.line((0, y, W, y), fill=g, width=1)
    return img


_BG_CACHE: dict[str, Image.Image] = {}
_BLOB_CACHE: dict[tuple, Image.Image] = {}


def _bg(mode: str) -> Image.Image:
    if mode not in _BG_CACHE:
        _BG_CACHE[mode] = _base_bg(mode)
    return _BG_CACHE[mode]


def _blob(color, alpha, radius) -> Image.Image:
    key = (color, alpha, radius)
    if key not in _BLOB_CACHE:
        _BLOB_CACHE[key] = make_blob_sprite(radius, color, alpha=alpha, blur=max(24, radius // 4))
    return _BLOB_CACHE[key]


def paint_background(mode: str, t: float) -> Image.Image:
    pal = PALETTES[mode]
    img = _bg(mode).copy()
    for i, (col, alpha, radius, x, y) in enumerate(pal["blobs"]):
        spr = _blob(col, alpha, radius)
        dx = math.sin(t * 0.25 + i * 1.3) * 30
        dy = math.cos(t * 0.18 + i) * 22
        blit(img, spr, (int(x + dx - spr.width / 2), int(y + dy - spr.height / 2)))
    return img


def draw_chrome(
    img: Image.Image,
    t: float,
    duration: float,
    pal: dict,
    fonts: dict,
    *,
    chapter: str = "",
    chapter_title: str = "",
) -> None:
    d = ImageDraw.Draw(img)
    d.text((SAFE_LEFT, 56), "PO CHAI", font=fonts["brand"], fill=pal["brand"])
    right = "KREATOR AI"
    tw = fonts["brand"].getlength(right)
    d.text((W - SAFE_LEFT - tw, 56), right, font=fonts["brand"], fill=pal["muted"])
    if chapter:
        draw_pill(
            img, chapter, cx=W // 2, y=50,
            font=fonts["chapter"], fill=pal["pill"], text_fill=pal["pill_text"],
            pad_x=18, pad_y=8,
        )
    # progress bawah
    y = H - 10
    d.rectangle((0, y, W, H), fill=pal["grid"])
    frac = 0 if duration <= 0 else clamp(t / duration)
    d.rectangle((0, y, int(W * frac), H), fill=pal["accent"])


def rolling(t: float, start: float, dur: float, a: float, b: float) -> float:
    u = ease_out_cubic(clamp((t - start) / max(0.05, dur)))
    return a + (b - a) * u


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 0.05:
        return str(int(round(v)))
    return f"{v:.1f}".replace(".", ",")


def _keyword_map(bab: dict) -> dict[str, str]:
    out = {}
    for it in bab.get("kata_kunci") or []:
        k = re.sub(r"[^\w]+", "", (it.get("kata") or "").lower(), flags=re.UNICODE)
        if k:
            out[k] = it.get("warna") or "aksen"
    return out


def _norm_tok(w: str) -> str:
    return re.sub(r"[^\w]+", "", (w or "").lower(), flags=re.UNICODE)


def draw_kinetic_phrase(
    img: Image.Image,
    chunk: CaptionChunk | None,
    t: float,
    pal: dict,
    fonts: dict,
    *,
    y: int = 1280,
    kata_kunci: dict | None = None,
    appear_t: float = 0.0,
    max_size: int = 86,
) -> tuple[int, int, int, int] | None:
    if not chunk or not chunk.words:
        return None
    hi = chunk.highlight_index(t)
    scale = 0.85 + 0.15 * spring_settle(clamp((t - max(chunk.start, appear_t)) / 0.38))
    items = []
    kk = kata_kunci or {}
    for i, w in enumerate(chunk.words):
        is_hi = i == hi
        tok = w.word
        key = _norm_tok(tok)
        if key in kk:
            col = _kw_color(kk[key], pal)
        elif is_hi:
            col = pal["accent"]
        else:
            col = pal["text"]
        weight = 850 if is_hi or key in kk else 700
        size = int((max_size + (10 if is_hi else 0)) * scale)
        font = fonts["_cache"](size, weight)
        items.append((tok, col, font))
    return draw_words_colored(
        ImageDraw.Draw(img), items, cx=W // 2, y=int(y), max_width=SAFE_WIDTH - 20, gap=18
    )


def _enter(t: float, start: float) -> float:
    return entrance(t, start, 0.42, "back")


def layout_kinetic_title(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    # pil opsional
    nama = (bab.get("nama") or "").upper()
    if nama and nama not in {"HOOK", "BAB_1", "HOOK_1"}:
        fy = int(lerp(280, 320, e))
        fill = pal["red"] if pal["bg"][0] > 80 else pal["red"]
        draw_pill(img, nama[:28], cx=W // 2, y=fy, font=fonts["pill"], fill=fill, text_fill=(255, 255, 255), pad_x=28, pad_y=12, scale=e)
    judul = bab.get("judul_layar") or ""
    # jika judul berbeda dari chunk, tampilkan sebagai judul besar di atas
    y_main = 520
    if judul:
        lines, font, sz = fit_text(judul, max_width=SAFE_WIDTH, max_height=420, max_size=int(110 * e + 10), min_size=36, weight=850, max_lines=3)
        # warnai kata kunci di dalam judul
        kk = kata_kunci or {}
        items = []
        for line in lines:
            # kita gambar per baris terpusat lewat draw_words_colored — gabung satu daftar lalu wrap
            pass
        # sederhana: tiap kata
        words = judul.split()
        for tok in words:
            key = _norm_tok(tok)
            col = _kw_color(kk[key], pal) if key in kk else pal["text"]
            items.append((tok, col, font))
        bbox = draw_words_colored(ImageDraw.Draw(img), items, cx=W // 2, y=int(lerp(y_main + 40, y_main, e)), max_width=SAFE_WIDTH, gap=20)
        y_sub = bbox[3] + 30 if bbox else y_main + 200
    else:
        y_sub = y_main
    sub = bab.get("subjudul") or ""
    if sub:
        sl, sf, _ = fit_text(sub, max_width=SAFE_WIDTH - 40, max_height=200, max_size=48, min_size=26, weight=550, max_lines=3)
        draw_centered_lines(ImageDraw.Draw(img), sl, sf, cx=W // 2, y=y_sub, fill=pal["text"])
    # ikon, kelompok terpusat
    ikon = (bab.get("ikon") or [])[:3]
    if ikon:
        gap, sz = 48, 160
        total = len(ikon) * sz + (len(ikon) - 1) * gap
        x0 = (W - total) // 2
        for i, name in enumerate(ikon):
            ic = draw_icon(known_icon(name), sz, pal["text"], pal["accent"] if i == 0 else None)
            blit(img, ic, (x0 + i * (sz + gap), 1080), scale=e, alpha=e)
    # frase kinetik di bawah jika ada chunk
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1380, kata_kunci=kata_kunci, appear_t=start, max_size=64)


def layout_hero_number(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    ctr = bab.get("counter") or {}
    ke = ctr.get("ke")
    dari = ctr.get("dari") or 0
    if ke is None:
        # coba dari judul
        m = re.search(r"\d+", bab.get("judul_layar") or "")
        ke = float(m.group()) if m else None
    y = int(lerp(520, 460, e))
    if ke is not None:
        val = rolling(t, start + 0.1, 0.85, float(dari), float(ke))
        text = (ctr.get("awalan") or "") + _fmt_num(val)
        font = fonts["_cache"](int(280 * (0.7 + 0.3 * e)), 900)
        col = pal["green"] if (bab.get("nama") or "").lower() in {"baru", "payoff"} else pal["text"]
        # kata kunci "benar/baru" hijau
        if any(k.get("warna") == "hijau" for k in (bab.get("kata_kunci") or [])):
            col = pal["green"]
        if any(k.get("warna") == "merah" for k in (bab.get("kata_kunci") or [])):
            col = pal["red"]
        tw = font.getlength(text)
        ImageDraw.Draw(img).text(((W - tw) / 2, y), text, font=font, fill=col)
        y += int(280 * 0.85)
    label = (ctr.get("label") or bab.get("judul_layar") or "").upper()
    if label and not (ke is not None and _fmt_num(float(ke)) in label and len(label) < 4):
        # jangan duplikasi angka saja
        lf = fonts["_cache"](92, 850)
        # jika label mengandung kata kunci
        items = []
        for tok in label.split()[:6]:
            key = _norm_tok(tok)
            col = _kw_color((kata_kunci or {}).get(key, "merah" if ke is not None else "aksen"), pal) if (kata_kunci or {}).get(key) else pal["red"]
            items.append((tok, col, lf))
        if items:
            draw_words_colored(ImageDraw.Draw(img), items, cx=W // 2, y=y, max_width=SAFE_WIDTH, gap=16)
            y += 120
    sub = bab.get("subjudul") or ""
    if sub:
        sl, sf, _ = fit_text(sub, max_width=SAFE_WIDTH - 40, max_height=220, max_size=48, min_size=26, weight=550, max_lines=3)
        draw_centered_lines(ImageDraw.Draw(img), sl, sf, cx=W // 2, y=y + 10, fill=pal["text"])
    for i, name in enumerate((bab.get("ikon") or [])[:2]):
        ic = draw_icon(known_icon(name), 180, pal["text"])
        blit(img, ic, (W // 2 - 90, 280), scale=e, alpha=min(1, e + 0.2))
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1450, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_comparison(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    draw_pill(img, "PERBANDINGAN", cx=W // 2, y=260, font=fonts["pill"], fill=pal["pill"], text_fill=pal["pill_text"], pad_x=26, pad_y=10, scale=e)
    perc = bab.get("perbandingan") or {
        "kiri": {"judul": "LAMA", "nilai": "", "poin": [], "warna": "abu", "ikon": "close"},
        "kanan": {"judul": "BARU", "nilai": "", "poin": [], "warna": "hijau", "ikon": "check"},
    }
    sides = [perc.get("kiri") or {}, perc.get("kanan") or {}]
    # kartu
    gap = 28
    cw = (SAFE_WIDTH - gap) // 2
    ch = 820
    y0 = 360
    bar_max = 360
    for i, side in enumerate(sides):
        x0 = SAFE_LEFT + i * (cw + gap)
        # masuk dari kiri/kanan
        slide = (1 - e) * (80 if i == 0 else -80)
        xx = int(x0 + slide)
        warna = (side.get("warna") or ("abu" if i == 0 else "hijau")).lower()
        col = _kw_color(warna if warna != "abu" else "abu", pal)
        rounded_rect(img, (xx, y0, xx + cw, y0 + ch), 28, pal["card"], shadow=12, shadow_color=pal["shadow"])
        d = ImageDraw.Draw(img)
        judul = (side.get("judul") or ("LAMA" if i == 0 else "BARU")).upper()
        jf = fonts["_cache"](32, 750)
        tw = jf.getlength(judul)
        d.text((xx + (cw - tw) / 2, y0 + 36), judul, font=jf, fill=col)
        nilai = side.get("nilai") or ""
        if nilai:
            nf = fonts["_cache"](int(140 * (0.5 + 0.5 * e)), 900)
            # animasi angka jika numerik
            m = re.search(r"[-+]?\d+(?:[.,]\d+)?", nilai)
            text = nilai
            if m:
                try:
                    target = float(m.group().replace(",", "."))
                    cur = rolling(t, start + 0.15, 0.8, 0, target)
                    text = nilai[: m.start()] + _fmt_num(cur) + nilai[m.end():]
                except ValueError:
                    pass
            tw = nf.getlength(text)
            d.text((xx + (cw - tw) / 2, y0 + 110), text, font=nf, fill=col)
        # ikon
        icn = side.get("ikon") or ("close" if i == 0 else "check")
        ic = draw_icon(known_icon(icn), 120, (255, 255, 255), col)
        blit(img, ic, (xx + cw // 2 - 60, y0 + 200), scale=min(1, e + 0.1), alpha=e)
        # poin di atas batang, tidak boleh tertutup
        py = y0 + 350
        for p in (side.get("poin") or [])[:3]:
            sl, sf, _ = fit_text(p, max_width=cw - 48, max_height=64, max_size=26, min_size=18, weight=550, max_lines=2)
            draw_centered_lines(d, sl, sf, cx=xx + cw // 2, y=py, fill=pal["text"])
            py += 62
        # batang di bagian bawah kartu
        hbar = int(200 * (0.85 if i == 0 else 0.55) * e)
        if nilai:
            m = re.search(r"[-+]?\d+(?:[.,]\d+)?", nilai)
            if m:
                try:
                    target = float(m.group().replace(",", "."))
                    vals = []
                    for s2 in sides:
                        mm = re.search(r"[-+]?\d+(?:[.,]\d+)?", s2.get("nilai") or "")
                        if mm:
                            vals.append(float(mm.group().replace(",", ".")))
                    mx = max(vals) if vals else target
                    hbar = int(200 * (target / mx) * e) if mx else hbar
                except ValueError:
                    pass
        bx0 = xx + 50
        bx1 = xx + cw - 50
        by1 = y0 + ch - 48
        bar_top = max(py + 8, by1 - max(24, hbar))
        rounded_rect(img, (bx0, bar_top, bx1, by1), 16, col)
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1460, kata_kunci=kata_kunci, appear_t=start, max_size=52)


def layout_steps(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or "LANGKAH"
    lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=220, max_size=72, min_size=32, weight=850, max_lines=2)
    draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=280, fill=pal["text"])
    langkah = bab.get("langkah") or []
    # jika kosong, pecah kata kunci / subjudul
    if not langkah:
        langkah = [k["kata"] for k in (bab.get("kata_kunci") or []) if k.get("kata")]
    n = max(len(langkah), 3)
    n = min(n, 6)
    if not langkah:
        langkah = [str(i + 1) for i in range(n)]
    # aktif: berdasarkan kemajuan adegan
    # coba dari chunk/t
    elapsed = max(0.0, t - start)
    aktif = int(clamp(elapsed / max(0.4, (bab.get("_durasi") or 6) * 0.85)) * n)
    aktif = min(n - 1, max(0, aktif))
    # kotak angka
    box = 140
    gap = 22
    total_w = n * box + (n - 1) * gap
    while total_w > SAFE_WIDTH and box > 80:
        box -= 8
        total_w = n * box + (n - 1) * gap
    x0 = (W - total_w) // 2
    y0 = 560
    d = ImageDraw.Draw(img)
    nf = fonts["_cache"](int(box * 0.48), 850)
    for i in range(n):
        appear = entrance(t, start + 0.12 * i, 0.32, "back")
        if appear <= 0:
            continue
        x = x0 + i * (box + gap)
        y = y0 - int((1 - appear) * 24)
        # selesai=hijau, sedang=emas, belum=abu (merah disimpan untuk "salah")
        fill = pal["gold"] if i == aktif else pal["abu"]
        if i < aktif:
            fill = pal["green"]
        rounded_rect(img, (x, y, x + box, y + box), 24, fill, shadow=8, shadow_color=pal["shadow"])
        txt = str(i + 1)
        tw = nf.getlength(txt)
        d.text((x + (box - tw) / 2, y + box * 0.22), txt, font=nf, fill=(255, 255, 255))
        if i < len(langkah):
            sl, sf, _ = fit_text(langkah[i], max_width=box + 8, max_height=100, max_size=24, min_size=14, weight=600, max_lines=3)
            draw_centered_lines(d, sl, sf, cx=x + box // 2, y=y + box + 16, fill=pal["text"])
    # badge tahun/label
    if bab.get("counter"):
        lab = (bab["counter"].get("label") or "").upper()
        if lab:
            draw_pill(img, lab, cx=W // 2, y=1100, font=fonts["pill"], fill=pal["pill"], text_fill=pal["pill_text"], pad_x=28, pad_y=12)
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1420, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_progress(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or ""
    if judul:
        lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=200, max_size=72, min_size=32, weight=850, max_lines=2)
        draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=280, fill=pal["text"])
    poin = bab.get("progress_poin") or []
    if not poin:
        poin = [{"label": "Langkah " + str(i + 1), "nilai": (i + 1) * 25} for i in range(3)]
    card_y = 520
    card_h = 120 + len(poin) * 160
    rounded_rect(img, (SAFE_LEFT, card_y, SAFE_RIGHT, card_y + card_h), 28, pal["card"], shadow=14, shadow_color=pal["shadow"])
    d = ImageDraw.Draw(img)
    lf = fonts["_cache"](30, 650)
    y = card_y + 50
    for i, p in enumerate(poin):
        appear = entrance(t, start + 0.15 * i, 0.45, "cubic")
        lab = p.get("label") or ""
        d.text((SAFE_LEFT + 48, y), lab, font=lf, fill=pal["text"])
        # track
        tx0, tx1 = SAFE_LEFT + 48, SAFE_RIGHT - 48
        ty = y + 50
        rounded_rect(img, (tx0, ty, tx1, ty + 22), 11, pal["grid"])
        val = float(p.get("nilai") or 0) * appear
        fw = int((tx1 - tx0) * clamp(val / 100.0))
        col = pal["green"] if val >= 80 else pal["accent"]
        if fw > 8:
            rounded_rect(img, (tx0, ty, tx0 + fw, ty + 22), 11, col)
        y += 160
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1460, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_card(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or ""
    if judul:
        lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=200, max_size=70, min_size=32, weight=850, max_lines=2)
        draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=int(lerp(300, 260, e)), fill=pal["text"])
    cw, ch = 760, 620
    x0 = (W - cw) // 2
    y0 = int(lerp(520, 470, e))
    rounded_rect(img, (x0, y0, x0 + cw, y0 + ch), 32, pal["card"], shadow=16, shadow_color=pal["shadow"])
    d = ImageDraw.Draw(img)
    # garis-garis dokumen
    ink = pal["muted"]
    for i, yy in enumerate((80, 150, 220, 290, 360)):
        wline = 0.7 if i < 4 else 0.4
        d.rounded_rectangle((x0 + 70, y0 + yy, x0 + 70 + int((cw - 140) * wline), y0 + yy + 16), radius=6, fill=ink)
    # stempel
    stamp = pal["green"]
    d.ellipse((x0 + cw - 200, y0 + ch - 200, x0 + cw - 60, y0 + ch - 60), outline=stamp, width=6)
    tf = fonts["_cache"](22, 750)
    tw = tf.getlength("RESMI")
    d.text((x0 + cw - 130 - tw / 2, y0 + ch - 148), "RESMI", font=tf, fill=stamp)
    sub = bab.get("subjudul") or ""
    if sub:
        sl, sf, _ = fit_text(sub, max_width=SAFE_WIDTH - 40, max_height=160, max_size=44, min_size=24, weight=550, max_lines=3)
        draw_centered_lines(d, sl, sf, cx=W // 2, y=y0 + ch + 40, fill=pal["text"])
    for name in (bab.get("ikon") or [])[:1]:
        ic = draw_icon(known_icon(name), 140, pal["text"])
        blit(img, ic, (x0 + 40, y0 + 40), scale=e, alpha=e)
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1460, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_cta(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or "SIMPAN VIDEO INI"
    lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=360, max_size=int(90 * (0.7 + 0.3 * e)), min_size=36, weight=900, max_lines=3)
    draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=int(lerp(560, 500, e)), fill=pal["text"])
    sub = bab.get("subjudul") or "Simpan, atau follow buat tip berikutnya."
    draw_pill(
        img, sub[:42], cx=W // 2, y=900,
        font=fonts["pill"], fill=pal["green"], text_fill=(255, 255, 255),
        pad_x=32, pad_y=16, scale=e,
    )
    ic = draw_icon("save", 200, (255, 255, 255), pal["accent"])
    blit(img, ic, (W // 2 - 100, 1080), scale=0.7 + 0.3 * e, alpha=e)
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1450, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_icons(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or ""
    if judul:
        lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=220, max_size=70, min_size=32, weight=850, max_lines=2)
        draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=300, fill=pal["text"])
    ikon = (bab.get("ikon") or ["lightbulb", "search", "shield", "check"])[:4]
    n = len(ikon)
    gap = 40
    sz = 180
    total = n * sz + (n - 1) * gap
    x0 = (W - total) // 2
    labels = bab.get("langkah") or []
    for i, name in enumerate(ikon):
        appear = entrance(t, start + 0.14 * i, 0.36, "back")
        if appear <= 0:
            continue
        x = x0 + i * (sz + gap)
        y = 620 - int((1 - appear) * 30)
        bg = pal["card"]
        rounded_rect(img, (x - 16, y - 16, x + sz + 16, y + sz + 80), 28, bg, shadow=10, shadow_color=pal["shadow"])
        ic = draw_icon(known_icon(name), sz, pal["text"], pal["accent"])
        blit(img, ic, (x, y), scale=appear, alpha=appear)
        if i < len(labels):
            sl, sf, _ = fit_text(labels[i], max_width=sz + 20, max_height=80, max_size=26, min_size=16, weight=650, max_lines=2)
            draw_centered_lines(ImageDraw.Draw(img), sl, sf, cx=x + sz // 2, y=y + sz + 8, fill=pal["text"])
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1420, kata_kunci=kata_kunci, appear_t=start, max_size=56)


def layout_bullets(img, bab, t, start, pal, fonts, chunk, kata_kunci) -> None:
    e = _enter(t, start)
    if e <= 0:
        return
    judul = bab.get("judul_layar") or ""
    if judul:
        lines, font, _ = fit_text(judul, max_width=SAFE_WIDTH, max_height=200, max_size=70, min_size=32, weight=850, max_lines=2)
        draw_centered_lines(ImageDraw.Draw(img), lines, font, cx=W // 2, y=280, fill=pal["text"])
    items = bab.get("langkah") or [k["kata"] for k in (bab.get("kata_kunci") or [])]
    if not items:
        sub = bab.get("subjudul") or ""
        items = [s.strip() for s in re.split(r"[.;]", sub) if s.strip()][:4]
    if not items:
        items = ["Satu gagasan", "Dicek dulu", "Baru dipakai"]
    y = 520
    for i, it in enumerate(items[:5]):
        appear = entrance(t, start + 0.16 * i, 0.34, "back")
        if appear <= 0:
            continue
        yy = y - int((1 - appear) * 20)
        ic = draw_icon("check", 88, (255, 255, 255), pal["green"])
        blit(img, ic, (SAFE_LEFT, yy), scale=appear, alpha=appear)
        sl, sf, _ = fit_text(it, max_width=SAFE_WIDTH - 140, max_height=120, max_size=42, min_size=24, weight=650, max_lines=2)
        draw_centered_lines(ImageDraw.Draw(img), sl, sf, cx=SAFE_LEFT + 130 + (SAFE_WIDTH - 140) // 2, y=yy + 10, fill=pal["text"])
        # left-align-ish: rewrite x
        d = ImageDraw.Draw(img)
        # actually draw_centered is fine for mid; let's left-align manually
        d.rectangle((SAFE_LEFT + 110, yy, SAFE_RIGHT, yy + 110), fill=pal["bg"] if False else None)
        # already drawn centered — leave it, but the check is left. OK visual.
        y += 150
    draw_kinetic_phrase(img, chunk, t, pal, fonts, y=1460, kata_kunci=kata_kunci, appear_t=start, max_size=56)


LAYOUTS = {
    "kinetic_title": layout_kinetic_title,
    "hero_number": layout_hero_number,
    "comparison": layout_comparison,
    "steps": layout_steps,
    "progress": layout_progress,
    "card": layout_card,
    "cta": layout_cta,
    "icons": layout_icons,
    "bullets": layout_bullets,
}


def _windows_from_script(script: dict, words: list[Word], duration: float):
    from reels_autopilot.renderer import build_windows, scene_for_time
    return build_windows(script, words, duration), scene_for_time


def render_penjelas_frame(
    script: dict,
    t: float,
    duration: float,
    words: list[Word],
    chunks: list[CaptionChunk],
    windows,
    scene_for_time,
    fonts: dict,
    pal: dict,
    mode: str,
) -> Image.Image:
    img = paint_background(mode, t)
    visual = (script.get("visual") or {})
    babs = visual.get("bab") or []
    sc = scene_for_time(windows, t)
    # index bab
    idx = 0
    for i, (a, b, s) in enumerate(windows):
        if a <= t < b:
            idx = i
            break
    else:
        idx = max(0, len(windows) - 1)
    bab = babs[idx] if idx < len(babs) else (babs[-1] if babs else {})
    # durasi adegan untuk steps
    if idx < len(windows):
        bab = dict(bab)
        bab["_durasi"] = windows[idx][1] - windows[idx][0]
    chapter = bab.get("label") or (f"{idx+1:02d}/{max(1,len(babs)):02d}" if babs else "")
    start = windows[idx][0] if windows else 0.0
    draw_chrome(img, t, duration, pal, fonts, chapter=chapter)
    chunk = chunk_at_time(chunks or [], t)
    kk = _keyword_map(bab)
    layout = bab.get("layout") or "kinetic_title"
    fn = LAYOUTS.get(layout, layout_kinetic_title)
    fn(img, bab, t, start, pal, fonts, chunk, kk)
    return img


def render_penjelas(
    script: dict,
    tts: TTSResult,
    dest: Path,
    *,
    settings: Settings | None = None,
    fps: int = TARGET_FPS,
    mix_sfx: bool = True,
    mix_music: bool = True,
) -> Path:
    settings = settings or get_settings()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    script = derive_penjelas_visual(script)
    duration = tts.duration or 0.0
    words = list(tts.words or [])
    audio = tts.audio_path
    if duration > HARD_MAX_DURATION and audio:
        # Jangan potong kalimat: percepat audio + skala timestamp.
        fit_dest = Path(audio).with_name(Path(audio).stem + "_fit.wav")
        audio, words, duration = atempo_fit(audio, words, duration, HARD_MAX_DURATION - 0.25, dest=fit_dest)
        log.warning("TTS dipercepat ke %.1fs agar muat batas %s dtk", duration, HARD_MAX_DURATION)
    elif duration <= 0:
        duration = 1.0 / max(1, fps)
    chunks = chunk_captions(words, audio_duration=duration)
    mode = ((script.get("visual") or {}).get("mode") or "light").lower()
    if mode not in PALETTES:
        mode = "light"
    pal = PALETTES[mode]
    _font_memo: dict[tuple[int, int], object] = {}

    def _cache(size: int, weight: int = 400):
        key = (int(size), int(weight))
        if key not in _font_memo:
            _font_memo[key] = load_font(size, weight, settings)
        return _font_memo[key]

    fonts = {
        "brand": load_font(26, 650, settings),
        "chapter": load_font(24, 700, settings),
        "pill": load_font(28, 700, settings),
        "hook": load_font(72, 850, settings),
        "caption": load_font(44, 550, settings),
        "caption_hi": load_font(48, 800, settings),
        "_cache": _cache,
    }
    windows, scene_for_time = _windows_from_script(script, words, duration)
    # audio: VO (sudah di-fit jika perlu) + SFX + pad
    voice_path = audio
    if mix_sfx or mix_music:
        ev = events_from_scene_starts(windows)
        sfx = mix_events(ev, duration, gain=0.42) if mix_sfx else None
        music = soft_pad(duration, gain=0.055) if mix_music else None
        mixed = dest.parent / (dest.stem + "_mix.wav")
        try:
            audio = mix_to_wav(
                mixed, duration,
                voice=voice_path,
                music=music, sfx=sfx,
                voice_gain=1.0, music_gain=1.0, sfx_gain=1.0,
                loudnorm_on=True,
            )
        except Exception as e:
            log.warning("campur SFX gagal, pakai VO saja: %s", e)
            audio = voice_path

    n = max(1, int(round(duration * fps)))

    def frames():
        for i in range(n):
            tt = i / fps
            yield render_penjelas_frame(
                script, tt, duration, words, chunks, windows, scene_for_time, fonts, pal, mode
            )

    return encode_video(dest, audio, duration, frames(), fps=fps)
