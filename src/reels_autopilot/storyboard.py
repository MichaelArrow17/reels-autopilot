"""Skema storyboard gaya cerita + validasi. LLM hanya mengisi JSON, tidak menulis kode.

Jika keluaran tidak valid, jatuh ke templat aman (pustaka tetap).
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from reels_autopilot.config import HARD_MAX_DURATION

log = logging.getLogger("reels.storyboard")

ENVIRONMENTS = ("underwater", "staircase", "mountain", "road", "office", "scale")

# Alias Indonesia / sinonim → kanonis
ENV_ALIASES = {
    "laut": "underwater", "bawah laut": "underwater", "dalam laut": "underwater",
    "underwater": "underwater", "air": "underwater", "lautan": "underwater",
    "tangga": "staircase", "staircase": "staircase", "stairs": "staircase",
    "gunung": "mountain", "mountain": "mountain", "bukit": "mountain",
    "jalan": "road", "road": "road", "balapan": "road", "race": "road",
    "kantor": "office", "office": "office", "meja": "office",
    "timbangan": "scale", "scale": "scale", "neraca": "scale", "imbangan": "scale",
}

ACTIONS = (
    "idle", "walk", "climb", "swim", "sink", "fall", "push", "celebrate",
    "sit", "reach", "limp", "stand", "look", "struggle", "kneel", "wave",
)

ACTION_ALIASES = {
    "diam": "idle", "berdiri": "stand", "jalan": "walk", "berjalan": "walk",
    "panjat": "climb", "naik": "climb", "mendaki": "climb",
    "renang": "swim", "berenang": "swim",
    "tenggelam": "sink", "turun": "sink",
    "jatuh": "fall", "dorong": "push",
    "rayakan": "celebrate", "menang": "celebrate", "pesta": "celebrate",
    "duduk": "sit", "meraih": "reach", "terkulai": "limp", "roboh": "limp",
    "lihat": "look", "berjuang": "struggle", "berusaha": "struggle",
    "lutut": "kneel", "melambai": "wave",
}

PROPS = ("chain_ball", "chain", "ball", "ladder", "wall", "rope", "coin", "none")
PROP_ALIASES = {
    "rantai": "chain_ball", "bola rantai": "chain_ball", "bola": "ball",
    "chain+ball": "chain_ball", "chain_and_ball": "chain_ball",
    "tangga": "ladder", "dinding": "wall", "tembok": "wall",
    "tali": "rope", "koin": "coin", "uang": "coin",
}

EFFECTS = ("bubbles", "sparks", "glow", "break", "splash", "dust", "none")
EFFECT_ALIASES = {
    "gelembung": "bubbles", "bunga api": "sparks", "cahaya": "glow",
    "putus": "break", "pecah": "break", "cipratan": "splash", "debu": "dust",
}

CHAR_COLORS = {
    "kuning": "kuning", "yellow": "kuning", "emas": "kuning", "gold": "kuning",
    "abu": "abu", "grey": "abu", "gray": "abu", "abu-abu": "abu", "silver": "abu",
    "oranye": "oranye", "orange": "oranye",
    "biru": "biru", "blue": "biru",
    "hijau": "hijau", "green": "hijau",
    "merah": "merah", "red": "merah",
    "putih": "putih", "white": "putih",
}

# Layout yang diakui gaya penjelas
PENJELAS_LAYOUTS = (
    "kinetic_title", "hero_number", "comparison", "steps", "progress",
    "card", "cta", "icons", "bullets",
)

CERITA_MIN_S = 20.0
CERITA_MAX_S = 30.0
CERITA_DEFAULT_S = 24.0

_NUM_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w.])"
)


def extract_narration_numbers(text: str) -> set[float]:
    """Angka yang boleh tampil di layar: hanya yang ada di naskah/topik."""
    found: set[float] = set()
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group(1).replace(".", "").replace(",", ".") if "," in m.group(1) and "." not in m.group(1) else m.group(1)
        # "20.160.000" indonesian thousands — treat as int if multiple dots
        if raw.count(".") > 1:
            raw = raw.replace(".", "")
        try:
            found.add(float(raw))
        except ValueError:
            continue
    # angka kata umum (hanya jika muncul sebagai kata)
    words = {
        "nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
        "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
        "pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5,
    }
    low = (text or "").lower()
    for w, n in words.items():
        if re.search(rf"(?<![a-z]){w}(?![a-z])", low):
            found.add(float(n))
    return found


def number_allowed(n: float | int | None, allowed: set[float], *, tol: float = 1e-6) -> bool:
    if n is None:
        return False
    try:
        v = float(n)
    except (TypeError, ValueError):
        return False
    for a in allowed:
        if abs(a - v) <= tol:
            return True
    return False


def _canon(value: str, aliases: dict[str, str], allowed: tuple[str, ...], default: str) -> str:
    raw = (value or "").strip().lower()
    if raw in allowed:
        return raw
    if raw in aliases:
        return aliases[raw]
    # partial
    for k, v in aliases.items():
        if raw and (raw in k or k in raw):
            return v
    return default


def _clamp_dur(d: Any, lo: float = CERITA_MIN_S, hi: float = CERITA_MAX_S, default: float = CERITA_DEFAULT_S) -> float:
    try:
        v = float(d)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _xy(val: Any, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return (max(0.05, min(0.95, float(val[0]))), max(0.05, min(0.95, float(val[1]))))
        except (TypeError, ValueError):
            return default
    if isinstance(val, dict):
        try:
            return (
                max(0.05, min(0.95, float(val.get("x", default[0])))),
                max(0.05, min(0.95, float(val.get("y", default[1])))),
            )
        except (TypeError, ValueError):
            return default
    return default


def _action_obj(raw: Any, default_xy: tuple[float, float]) -> dict:
    if isinstance(raw, str):
        return {"nama": _canon(raw, ACTION_ALIASES, ACTIONS, "idle"), "x": default_xy[0], "y": default_xy[1], "hadap": "kanan"}
    if not isinstance(raw, dict):
        return {"nama": "idle", "x": default_xy[0], "y": default_xy[1], "hadap": "kanan"}
    nama = raw.get("nama") or raw.get("aksi") or raw.get("pose") or "idle"
    xy = _xy({"x": raw.get("x", default_xy[0]), "y": raw.get("y", default_xy[1])}, default_xy)
    hadap = raw.get("hadap") or raw.get("facing") or ""
    hadap = "kiri" if str(hadap).lower() in {"kiri", "left", "l"} else (
        "kanan" if str(hadap).lower() in {"kanan", "right", "r"} else ""
    )
    return {"nama": _canon(str(nama), ACTION_ALIASES, ACTIONS, "idle"), "x": xy[0], "y": xy[1], "hadap": hadap}


def _prop_list(raw: Any) -> list[dict]:
    out: list[dict] = []
    if not raw:
        return out
    items = raw if isinstance(raw, list) else [raw]
    for it in items:
        if isinstance(it, str):
            jenis = _canon(it, PROP_ALIASES, PROPS, "none")
            if jenis != "none":
                out.append({"jenis": jenis, "pada": ""})
        elif isinstance(it, dict):
            jenis = _canon(str(it.get("jenis") or it.get("nama") or ""), PROP_ALIASES, PROPS, "none")
            if jenis == "none":
                continue
            pada = str(it.get("pada") or it.get("karakter") or it.get("on") or "")
            out.append({"jenis": jenis, "pada": pada})
    return out


def _effects(raw: Any) -> list[str]:
    out: list[str] = []
    items = raw if isinstance(raw, list) else ([raw] if raw else [])
    for it in items:
        e = _canon(str(it), EFFECT_ALIASES, EFFECTS, "none")
        if e != "none" and e not in out:
            out.append(e)
    return out


def _color(raw: Any, default: str) -> str:
    return _canon(str(raw or ""), CHAR_COLORS, tuple(set(CHAR_COLORS.values())), default)


def _safe_text(s: Any, max_len: int = 80) -> str:
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    # tolak potongan yang terlihat seperti kode
    if re.search(r"\b(import |def |class |pygame|moviepy|eval\(|exec\()", t, re.I):
        return ""
    return t[:max_len]


def fallback_cerita(topic: dict | None = None, environment: str | None = None) -> dict:
    """Templat cerita aman (pustaka tetap). Lingkungan dipilih dari topik bila ada."""
    judul = (topic or {}).get("judul") or "Yang terus berusaha sampai ke permukaan"
    hook = (topic or {}).get("hook") or "Yang menyerah tetap di dasar. Yang terus berusaha sampai ke permukaan."
    env = _canon(environment or (topic or {}).get("environment") or "", ENV_ALIASES, ENVIRONMENTS, "")
    if not env:
        # pilih dari topik
        blob = f"{judul} {hook}".lower()
        if any(k in blob for k in ("tangga", "naik", "langkah")):
            env = "staircase"
        elif any(k in blob for k in ("gunung", "puncak", "mendaki")):
            env = "mountain"
        elif any(k in blob for k in ("lintasan", "balapan", "finish", "garis")):
            env = "road"
        elif any(k in blob for k in ("kantor", "kerja", "meja", "deadline")):
            env = "office"
        elif any(k in blob for k in ("timbang", "alasan", "seimbang")):
            env = "scale"
        else:
            env = "underwater"
    return _TEMPLATES[env](judul, hook)


def _tpl_underwater(judul: str, hook: str) -> dict:
    return {
        "style": "cerita",
        "environment": "underwater",
        "durasi_detik": 24.0,
        "label_kiri": "MENYERAH",
        "label_kanan": "BERUSAHA",
        "judul": judul,
        "hook": hook,
        "karakter": [
            {"id": "a", "warna": "abu", "peran": "menyerah"},
            {"id": "b", "warna": "kuning", "peran": "berjuang"},
        ],
        "beats": [
            {
                "t": 0.0, "durasi": 3.5,
                "aksi_a": {"nama": "swim", "x": 0.30, "y": 0.55, "hadap": "kanan"},
                "aksi_b": {"nama": "swim", "x": 0.68, "y": 0.52, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}, {"jenis": "chain_ball", "pada": "b"}],
                "gelembung_a": "Buat apa dicoba?",
                "gelembung_b": "",
                "efek": ["bubbles"],
                "sfx": ["bubble"],
            },
            {
                "t": 3.5, "durasi": 4.0,
                "aksi_a": {"nama": "struggle", "x": 0.30, "y": 0.62, "hadap": "kanan"},
                "aksi_b": {"nama": "swim", "x": 0.66, "y": 0.46, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}, {"jenis": "chain_ball", "pada": "b"}],
                "gelembung_a": "",
                "gelembung_b": "Sedikit lagi.",
                "efek": ["bubbles"],
                "sfx": ["bubble"],
            },
            {
                "t": 7.5, "durasi": 4.0,
                "aksi_a": {"nama": "sink", "x": 0.30, "y": 0.78, "hadap": "kanan"},
                "aksi_b": {"nama": "struggle", "x": 0.64, "y": 0.44, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}, {"jenis": "chain_ball", "pada": "b"}],
                "gelembung_a": "Aku nyerah.",
                "gelembung_b": "Masih bisa.",
                "efek": ["bubbles"],
                "sfx": ["thud"],
            },
            {
                "t": 11.5, "durasi": 4.0,
                "aksi_a": {"nama": "limp", "x": 0.28, "y": 0.86, "hadap": "kanan"},
                "aksi_b": {"nama": "swim", "x": 0.62, "y": 0.36, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}, {"jenis": "chain_ball", "pada": "b"}],
                "gelembung_a": "",
                "gelembung_b": "",
                "efek": ["bubbles"],
                "sfx": ["chain"],
            },
            {
                "t": 15.5, "durasi": 3.5,
                "aksi_a": {"nama": "sit", "x": 0.28, "y": 0.87, "hadap": "kanan"},
                "aksi_b": {"nama": "reach", "x": 0.62, "y": 0.26, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}],
                "gelembung_a": "",
                "gelembung_b": "",
                "efek": ["bubbles", "break", "glow"],
                "sfx": ["break"],
                "klimaks": True,
                "teks_klimaks": "",
            },
            {
                "t": 19.0, "durasi": 5.0,
                "aksi_a": {"nama": "limp", "x": 0.30, "y": 0.88, "hadap": "kanan"},
                "aksi_b": {"nama": "celebrate", "x": 0.62, "y": 0.16, "hadap": "kanan"},
                "properti": [{"jenis": "chain_ball", "pada": "a"}],
                "gelembung_a": "Dia cuma beruntung.",
                "gelembung_b": "",
                "efek": ["glow", "sparks"],
                "sfx": ["chime"],
            },
        ],
        "klimaks": {"t": 15.5, "jenis": "break_chain", "pemenang": "b"},
        "narasi_penuh": "",
        "pakai_vo": False,
        "moral": "Yang terus berusaha sampai ke permukaan. Yang menyerah tetap di dasar.",
    }


def _tpl_staircase(judul: str, hook: str) -> dict:
    return {
        "style": "cerita",
        "environment": "staircase",
        "durasi_detik": 24.0,
        "label_kiri": "BERHENTI",
        "label_kanan": "SATU LANGKAH LAGI",
        "judul": judul, "hook": hook,
        "karakter": [
            {"id": "a", "warna": "abu", "peran": "berhenti"},
            {"id": "b", "warna": "kuning", "peran": "naik"},
        ],
        "beats": [
            {"t": 0.0, "durasi": 3.5, "aksi_a": {"nama": "walk", "x": 0.28, "y": 0.78}, "aksi_b": {"nama": "walk", "x": 0.58, "y": 0.78},
             "gelembung_a": "Capek, udah cukup.", "gelembung_b": "", "efek": [], "sfx": ["whoosh"]},
            {"t": 3.5, "durasi": 4.0, "aksi_a": {"nama": "sit", "x": 0.30, "y": 0.72}, "aksi_b": {"nama": "climb", "x": 0.55, "y": 0.64},
             "gelembung_a": "", "gelembung_b": "Sedikit lagi.", "efek": [], "sfx": ["pop"]},
            {"t": 7.5, "durasi": 4.5, "aksi_a": {"nama": "sit", "x": 0.30, "y": 0.72}, "aksi_b": {"nama": "climb", "x": 0.58, "y": 0.48},
             "gelembung_a": "Nanti aja.", "gelembung_b": "", "efek": ["dust"], "sfx": []},
            {"t": 12.0, "durasi": 4.0, "aksi_a": {"nama": "look", "x": 0.30, "y": 0.72}, "aksi_b": {"nama": "climb", "x": 0.62, "y": 0.32},
             "gelembung_a": "", "gelembung_b": "Hampir.", "efek": [], "sfx": []},
            {"t": 16.0, "durasi": 3.5, "aksi_a": {"nama": "look", "x": 0.30, "y": 0.72}, "aksi_b": {"nama": "reach", "x": 0.66, "y": 0.20},
             "gelembung_a": "", "gelembung_b": "", "efek": ["glow"], "sfx": ["chime"], "klimaks": True},
            {"t": 19.5, "durasi": 4.5, "aksi_a": {"nama": "sit", "x": 0.30, "y": 0.72}, "aksi_b": {"nama": "celebrate", "x": 0.68, "y": 0.16},
             "gelembung_a": "Dia cuma beruntung.", "gelembung_b": "", "efek": ["glow", "sparks"], "sfx": ["sparkle"]},
        ],
        "klimaks": {"t": 16.0, "jenis": "reach_top", "pemenang": "b"},
        "narasi_penuh": "", "pakai_vo": False,
        "moral": "Yang duduk di tangga tidak pernah lihat pemandangannya.",
    }


def _tpl_mountain(judul: str, hook: str) -> dict:
    sb = _tpl_staircase(judul, hook)
    sb["environment"] = "mountain"
    sb["label_kiri"] = "BALIK ARAH"
    sb["label_kanan"] = "SAMPAI PUNCAK"
    sb["moral"] = "Puncak hanya terlihat oleh yang terus mendaki."
    return sb


def _tpl_road(judul: str, hook: str) -> dict:
    return {
        "style": "cerita",
        "environment": "road",
        "durasi_detik": 24.0,
        "label_kiri": "NYERAH DI TENGAH",
        "label_kanan": "SAMPAI FINISH",
        "judul": judul, "hook": hook,
        "karakter": [
            {"id": "a", "warna": "abu", "peran": "berhenti"},
            {"id": "b", "warna": "kuning", "peran": "lari"},
        ],
        "beats": [
            {"t": 0.0, "durasi": 3.5, "aksi_a": {"nama": "walk", "x": 0.22, "y": 0.70}, "aksi_b": {"nama": "walk", "x": 0.40, "y": 0.70},
             "gelembung_a": "", "gelembung_b": "", "efek": [], "sfx": ["whoosh"]},
            {"t": 3.5, "durasi": 4.0, "aksi_a": {"nama": "walk", "x": 0.36, "y": 0.70}, "aksi_b": {"nama": "walk", "x": 0.55, "y": 0.70},
             "gelembung_a": "Udah capek.", "gelembung_b": "", "efek": ["dust"], "sfx": []},
            {"t": 7.5, "durasi": 4.0, "aksi_a": {"nama": "sit", "x": 0.40, "y": 0.72}, "aksi_b": {"nama": "walk", "x": 0.68, "y": 0.70},
             "gelembung_a": "Berhenti di sini.", "gelembung_b": "Masih ada jalan.", "efek": [], "sfx": ["thud"]},
            {"t": 11.5, "durasi": 4.5, "aksi_a": {"nama": "sit", "x": 0.40, "y": 0.72}, "aksi_b": {"nama": "walk", "x": 0.78, "y": 0.68},
             "gelembung_a": "", "gelembung_b": "", "efek": ["dust"], "sfx": []},
            {"t": 16.0, "durasi": 3.5, "aksi_a": {"nama": "look", "x": 0.40, "y": 0.72}, "aksi_b": {"nama": "celebrate", "x": 0.86, "y": 0.62},
             "gelembung_a": "", "gelembung_b": "", "efek": ["glow", "sparks"], "sfx": ["chime"], "klimaks": True},
            {"t": 19.5, "durasi": 4.5, "aksi_a": {"nama": "limp", "x": 0.40, "y": 0.74}, "aksi_b": {"nama": "wave", "x": 0.86, "y": 0.62},
             "gelembung_a": "Jalurnya memang mudah.", "gelembung_b": "", "efek": ["glow"], "sfx": ["sparkle"]},
        ],
        "klimaks": {"t": 16.0, "jenis": "finish_line", "pemenang": "b"},
        "narasi_penuh": "", "pakai_vo": False,
        "moral": "Garis finish hanya ketemu yang tidak berhenti di tengah jalan.",
    }


def _tpl_office(judul: str, hook: str) -> dict:
    return {
        "style": "cerita",
        "environment": "office",
        "durasi_detik": 24.0,
        "label_kiri": "SCROLL TERUS",
        "label_kanan": "KERJAKAN SEKARANG",
        "judul": judul, "hook": hook,
        "karakter": [
            {"id": "a", "warna": "abu", "peran": "scroll"},
            {"id": "b", "warna": "kuning", "peran": "kerja"},
        ],
        "beats": [
            {"t": 0.0, "durasi": 4.0, "aksi_a": {"nama": "sit", "x": 0.28, "y": 0.70}, "aksi_b": {"nama": "idle", "x": 0.68, "y": 0.70},
             "gelembung_a": "Nanti dulu.", "gelembung_b": "", "properti": [], "efek": [], "sfx": ["click"]},
            {"t": 4.0, "durasi": 4.0, "aksi_a": {"nama": "sit", "x": 0.28, "y": 0.70}, "aksi_b": {"nama": "push", "x": 0.68, "y": 0.70},
             "gelembung_a": "", "gelembung_b": "Satu tugas.", "efek": [], "sfx": ["pop"]},
            {"t": 8.0, "durasi": 4.5, "aksi_a": {"nama": "look", "x": 0.28, "y": 0.70}, "aksi_b": {"nama": "push", "x": 0.68, "y": 0.70},
             "gelembung_a": "Masih banyak waktu.", "gelembung_b": "", "efek": [], "sfx": []},
            {"t": 12.5, "durasi": 4.0, "aksi_a": {"nama": "sit", "x": 0.28, "y": 0.70}, "aksi_b": {"nama": "walk", "x": 0.70, "y": 0.70},
             "gelembung_a": "", "gelembung_b": "Selesai.", "efek": ["sparks"], "sfx": ["click"]},
            {"t": 16.5, "durasi": 3.5, "aksi_a": {"nama": "look", "x": 0.28, "y": 0.70}, "aksi_b": {"nama": "celebrate", "x": 0.70, "y": 0.66},
             "gelembung_a": "", "gelembung_b": "", "efek": ["glow"], "sfx": ["chime"], "klimaks": True},
            {"t": 20.0, "durasi": 4.0, "aksi_a": {"nama": "limp", "x": 0.28, "y": 0.72}, "aksi_b": {"nama": "wave", "x": 0.70, "y": 0.66},
             "gelembung_a": "Dia cuma lebih beruntung.", "gelembung_b": "", "efek": ["glow"], "sfx": ["sparkle"]},
        ],
        "klimaks": {"t": 16.5, "jenis": "task_done", "pemenang": "b"},
        "narasi_penuh": "", "pakai_vo": False,
        "moral": "Yang dikerjakan hari ini selesai hari ini. Yang ditunda, tetap di layar.",
    }


def _tpl_scale(judul: str, hook: str) -> dict:
    return {
        "style": "cerita",
        "environment": "scale",
        "durasi_detik": 24.0,
        "label_kiri": "ALASAN",
        "label_kanan": "TINDAKAN",
        "judul": judul, "hook": hook,
        "karakter": [
            {"id": "a", "warna": "abu", "peran": "alasan"},
            {"id": "b", "warna": "kuning", "peran": "tindakan"},
        ],
        "beats": [
            {"t": 0.0, "durasi": 4.0, "aksi_a": {"nama": "stand", "x": 0.28, "y": 0.55}, "aksi_b": {"nama": "stand", "x": 0.72, "y": 0.55},
             "gelembung_a": "Besok saja.", "gelembung_b": "", "efek": [], "sfx": ["pop"]},
            {"t": 4.0, "durasi": 4.0, "aksi_a": {"nama": "push", "x": 0.28, "y": 0.52}, "aksi_b": {"nama": "idle", "x": 0.72, "y": 0.58},
             "gelembung_a": "Banyak alasan.", "gelembung_b": "", "efek": [], "sfx": ["thud"]},
            {"t": 8.0, "durasi": 4.0, "aksi_a": {"nama": "idle", "x": 0.28, "y": 0.50}, "aksi_b": {"nama": "push", "x": 0.72, "y": 0.58},
             "gelembung_a": "", "gelembung_b": "Satu langkah.", "efek": [], "sfx": ["pop"]},
            {"t": 12.0, "durasi": 4.5, "aksi_a": {"nama": "struggle", "x": 0.28, "y": 0.48}, "aksi_b": {"nama": "push", "x": 0.72, "y": 0.62},
             "gelembung_a": "", "gelembung_b": "Lagi.", "efek": ["dust"], "sfx": []},
            {"t": 16.5, "durasi": 3.5, "aksi_a": {"nama": "fall", "x": 0.28, "y": 0.42}, "aksi_b": {"nama": "celebrate", "x": 0.72, "y": 0.68},
             "gelembung_a": "", "gelembung_b": "", "efek": ["glow", "sparks"], "sfx": ["chime"], "klimaks": True},
            {"t": 20.0, "durasi": 4.0, "aksi_a": {"nama": "limp", "x": 0.28, "y": 0.42}, "aksi_b": {"nama": "wave", "x": 0.72, "y": 0.68},
             "gelembung_a": "Timbangan ini curang.", "gelembung_b": "", "efek": ["glow"], "sfx": ["sparkle"]},
        ],
        "klimaks": {"t": 16.5, "jenis": "scale_tips", "pemenang": "b"},
        "narasi_penuh": "", "pakai_vo": False,
        "moral": "Alasan terasa berat, sampai tindakan mulai dikerjakan.",
    }


_TEMPLATES = {
    "underwater": _tpl_underwater,
    "staircase": _tpl_staircase,
    "mountain": _tpl_mountain,
    "road": _tpl_road,
    "office": _tpl_office,
    "scale": _tpl_scale,
}


def validate_cerita(data: Any, topic: dict | None = None) -> tuple[dict, bool, list[str]]:
    """Validasi storyboard. Kembalikan (storyboard, dipakai_fallback, errors).

    Fallback penuh hanya jika struktur tidak bisa dipakai (bukan kode, tidak ada beat).
    Aksi/lingkungan tidak dikenal dinormalisasi, tidak otomatis memicu fallback penuh.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("storyboard bukan objek")
        return fallback_cerita(topic), True, errors

    # Tolak jika LLM mencoba menyertakan kode
    blob = " ".join(str(v) for k, v in data.items() if k in {"kode", "code", "python", "script", "source"})
    if re.search(r"\b(import |pygame|moviepy|def |class )", blob or "", re.I):
        errors.append("storyboard memuat kode — ditolak")
        return fallback_cerita(topic), True, errors

    env = _canon(str(data.get("environment") or data.get("lingkungan") or ""), ENV_ALIASES, ENVIRONMENTS, "")
    beats_raw = data.get("beats") or data.get("adegan") or []
    if not env or not isinstance(beats_raw, list) or len(beats_raw) < 3:
        errors.append("lingkungan atau beat kurang")
        # coba pakai lingkungan yang ada, fallback template itu
        return fallback_cerita(topic, env or None), True, errors

    dur = _clamp_dur(data.get("durasi_detik") or data.get("durasi") or CERITA_DEFAULT_S)
    chars_raw = data.get("karakter") or []
    chars = []
    defaults = [
        {"id": "a", "warna": "abu", "peran": "menyerah"},
        {"id": "b", "warna": "kuning", "peran": "berjuang"},
    ]
    for i, ch in enumerate(chars_raw[:2] if isinstance(chars_raw, list) else []):
        if not isinstance(ch, dict):
            chars.append(defaults[i])
            continue
        chars.append({
            "id": str(ch.get("id") or ("a" if i == 0 else "b"))[:8],
            "warna": _color(ch.get("warna") or ch.get("color"), defaults[i]["warna"]),
            "peran": _safe_text(ch.get("peran") or ch.get("role") or defaults[i]["peran"], 40),
        })
    while len(chars) < 2:
        chars.append(defaults[len(chars)])
    if chars[0]["id"] == chars[1]["id"]:
        chars[1]["id"] = "b"

    beats: list[dict] = []
    t_cursor = 0.0
    for i, raw in enumerate(beats_raw[:10]):
        if not isinstance(raw, dict):
            errors.append(f"beat {i} bukan objek")
            continue
        try:
            t = float(raw.get("t") if raw.get("t") is not None else t_cursor)
        except (TypeError, ValueError):
            t = t_cursor
        t = max(0.0, min(dur - 0.4, t))
        if beats and t < beats[-1]["t"]:
            t = beats[-1]["t"] + 0.2
            errors.append(f"beat {i} waktu mundur, dirapikan")
        try:
            d = float(raw.get("durasi") or raw.get("duration") or 3.0)
        except (TypeError, ValueError):
            d = 3.0
        d = max(1.2, min(10.0, d))
        xa = (0.28, 0.62) if env != "road" else (0.25, 0.70)
        aksi_a = _action_obj(raw.get("aksi_a") or raw.get("aksi1"), (xa[0], 0.65))
        aksi_b = _action_obj(raw.get("aksi_b") or raw.get("aksi2"), (xa[1], 0.55))
        beat = {
            "t": t,
            "durasi": d,
            "aksi_a": aksi_a,
            "aksi_b": aksi_b,
            "properti": _prop_list(raw.get("properti") or raw.get("props")),
            "gelembung_a": _safe_text(raw.get("gelembung_a") or raw.get("bubble_a") or raw.get("teks_a"), 56),
            "gelembung_b": _safe_text(raw.get("gelembung_b") or raw.get("bubble_b") or raw.get("teks_b"), 56),
            "efek": _effects(raw.get("efek") or raw.get("effects")),
            "sfx": [str(s) for s in (raw.get("sfx") if isinstance(raw.get("sfx"), list) else ([raw.get("sfx")] if raw.get("sfx") else [])) if s],
            "klimaks": bool(raw.get("klimaks") or raw.get("climax")),
            "teks_klimaks": _safe_text(raw.get("teks_klimaks") or "", 40),
        }
        beats.append(beat)
        t_cursor = t + d

    if len(beats) < 3:
        errors.append("beat valid < 3")
        return fallback_cerita(topic, env), True, errors

    # jika beat pertama terlambat, geser ke 0 supaya tidak ada jeda kosong
    if beats[0]["t"] > 1.0:
        shift = beats[0]["t"]
        for b in beats:
            b["t"] = max(0.0, b["t"] - shift)
        errors.append("beat awal digeser ke 0")

    # rapikan durasi total
    last_end = beats[-1]["t"] + beats[-1]["durasi"]
    if last_end < CERITA_MIN_S:
        extra = CERITA_MIN_S - last_end
        beats[-1]["durasi"] += extra
        last_end = CERITA_MIN_S
    if last_end > CERITA_MAX_S:
        # skala waktu
        scale = CERITA_MAX_S / last_end
        for b in beats:
            b["t"] *= scale
            b["durasi"] *= scale
        last_end = CERITA_MAX_S
    dur = max(CERITA_MIN_S, min(CERITA_MAX_S, last_end))

    # klimaks: pastikan ada satu
    klimaks = data.get("klimaks") if isinstance(data.get("klimaks"), dict) else {}
    if not any(b.get("klimaks") for b in beats):
        # tandai beat ke-2 dari belakang
        idx = max(1, len(beats) - 2)
        beats[idx]["klimaks"] = True
        if "glow" not in beats[idx]["efek"]:
            beats[idx]["efek"].append("glow")
    k_t = klimaks.get("t")
    try:
        k_t = float(k_t) if k_t is not None else next(b["t"] for b in beats if b.get("klimaks"))
    except (TypeError, ValueError, StopIteration):
        k_t = beats[max(1, len(beats) - 2)]["t"]

    judul = _safe_text(data.get("judul") or (topic or {}).get("judul") or "", 90) or "Cerita singkat"
    hook = _safe_text(data.get("hook") or (topic or {}).get("hook") or "", 140)
    moral = _safe_text(data.get("moral") or "", 160)
    if not moral:
        moral = f"{_safe_text(data.get('label_kanan') or 'Yang berusaha', 40)} sampai di ujung. {_safe_text(data.get('label_kiri') or 'Yang menyerah', 40)} tetap di tempat."

    sb = {
        "style": "cerita",
        "environment": env,
        "durasi_detik": round(dur, 2),
        "label_kiri": _safe_text(data.get("label_kiri") or data.get("label_a") or "MENYERAH", 28) or "MENYERAH",
        "label_kanan": _safe_text(data.get("label_kanan") or data.get("label_b") or "BERUSAHA", 28) or "BERUSAHA",
        "judul": judul,
        "hook": hook,
        "karakter": chars,
        "beats": beats,
        "klimaks": {
            "t": float(k_t),
            "jenis": _safe_text(klimaks.get("jenis") or "climax", 32) or "climax",
            "pemenang": str(klimaks.get("pemenang") or "b")[:8],
        },
        "narasi_penuh": _safe_text(data.get("narasi_penuh") or "", 400),
        "pakai_vo": bool(data.get("pakai_vo")) and bool(_safe_text(data.get("narasi_penuh") or "", 400)),
        "moral": moral,
    }
    return sb, False, errors


# ---------- gaya penjelas: visual dari naskah ----------

def derive_penjelas_visual(script: dict) -> dict:
    """Lengkapi field visual gaya penjelas dari adegan yang ada, tanpa menambah angka baru."""
    script = dict(script or {})
    narasi = script.get("narasi_penuh") or ""
    hook = script.get("hook") or ""
    allowed = extract_narration_numbers(narasi + " " + hook + " " + (script.get("judul") or ""))
    adegan = list(script.get("adegan") or [])
    visual = script.get("visual") if isinstance(script.get("visual"), dict) else {}
    mode = (visual.get("mode") or script.get("visual_mode") or "light").lower()
    if mode not in {"light", "dark"}:
        mode = "light"
    bab_in = visual.get("bab") if isinstance(visual.get("bab"), list) else []
    n = max(len(adegan), len(bab_in), 1)
    # pastikan 3–6 bab
    if not adegan and not bab_in:
        adegan = [{"nama": "hook", "teks_layar": hook, "keyword": "", "narasi": narasi}]
        n = 1
    babs: list[dict] = []
    total = min(6, max(n, len(adegan) or 1))
    for i in range(total):
        sc = adegan[i] if i < len(adegan) else {}
        src = bab_in[i] if i < len(bab_in) and isinstance(bab_in[i], dict) else {}
        layout = (src.get("layout") or "").lower()
        if layout not in PENJELAS_LAYOUTS:
            # tebak dari konten
            if i == 0:
                layout = "kinetic_title"
            elif i == total - 1:
                layout = "cta"
            elif src.get("perbandingan") or sc.get("perbandingan") or "banding" in ((sc.get("nama") or "") + (sc.get("teks_layar") or "")).lower():
                layout = "comparison"
            elif src.get("counter") or src.get("langkah") or (sc.get("keyword") or "").replace(" ", "").isdigit():
                layout = "steps" if src.get("langkah") or total >= 3 else "hero_number"
            elif src.get("progress_poin"):
                layout = "progress"
            elif src.get("ikon") or sc.get("ikon"):
                layout = "icons"
            else:
                layout = "bullets" if i not in (0, total - 1) else "kinetic_title"
        judul_layar = _safe_text(src.get("judul_layar") or sc.get("teks_layar") or sc.get("keyword") or (hook if i == 0 else ""), 48)
        subjudul = _safe_text(src.get("subjudul") or sc.get("narasi") or "", 90)
        kata_kunci = []
        raw_kk = src.get("kata_kunci") or []
        if isinstance(raw_kk, list):
            for it in raw_kk:
                if isinstance(it, dict):
                    kata = _safe_text(it.get("kata") or it.get("word") or "", 24)
                    warna = str(it.get("warna") or it.get("color") or "aksen").lower()
                    if warna not in {"merah", "hijau", "aksen", "emas", "abu"}:
                        warna = "aksen"
                    if kata:
                        kata_kunci.append({"kata": kata, "warna": warna})
                elif isinstance(it, str) and it.strip():
                    kata_kunci.append({"kata": _safe_text(it, 24), "warna": "aksen"})
        if not kata_kunci and sc.get("keyword"):
            kata_kunci.append({"kata": _safe_text(sc.get("keyword"), 24), "warna": "aksen"})
        ikon = []
        for raw in (src.get("ikon") or sc.get("ikon") or []):
            if isinstance(raw, str) and raw.strip():
                ikon.append(raw.strip().lower()[:24])
        # counter hanya jika angkanya ada di naskah
        counter = None
        raw_c = src.get("counter")
        if isinstance(raw_c, dict):
            try:
                ke = raw_c.get("ke")
                ke_f = float(ke) if ke is not None else None
            except (TypeError, ValueError):
                ke_f = None
            if ke_f is not None and number_allowed(ke_f, allowed):
                try:
                    dari = float(raw_c.get("dari") or 0)
                except (TypeError, ValueError):
                    dari = 0.0
                if dari and not number_allowed(dari, allowed | {0.0}):
                    dari = 0.0
                counter = {
                    "dari": dari,
                    "ke": ke_f,
                    "label": _safe_text(raw_c.get("label") or "", 24),
                    "awalan": _safe_text(raw_c.get("awalan") or "", 8),
                }
        langkah = []
        for it in (src.get("langkah") or []):
            s = _safe_text(it, 40)
            if s:
                langkah.append(s)
        # perbandingan
        perbandingan = None
        raw_p = src.get("perbandingan") or sc.get("perbandingan")
        if isinstance(raw_p, dict):
            def _side(key_opts, default_judul, default_warna):
                side = None
                for k in key_opts:
                    if isinstance(raw_p.get(k), dict):
                        side = raw_p[k]
                        break
                side = side or {}
                nilai = side.get("nilai")
                # buang nilai angka yang tidak ada di naskah
                nilai_s = _safe_text(nilai, 16) if nilai is not None else ""
                if nilai_s:
                    try:
                        nv = float(re.sub(r"[^\d.,-]", "", nilai_s).replace(",", ".") or "nan")
                        if nv == nv and not number_allowed(nv, allowed):
                            nilai_s = ""
                    except (TypeError, ValueError):
                        pass
                return {
                    "judul": _safe_text(side.get("judul") or default_judul, 22),
                    "nilai": nilai_s,
                    "poin": [_safe_text(p, 36) for p in (side.get("poin") or []) if _safe_text(p, 36)][:4],
                    "warna": str(side.get("warna") or default_warna).lower(),
                    "ikon": _safe_text(side.get("ikon") or "", 16),
                }
            perbandingan = {
                "kiri": _side(("kiri", "left", "lama", "salah"), "LAMA", "abu"),
                "kanan": _side(("kanan", "right", "baru", "benar"), "BARU", "hijau"),
            }
        progress_poin = []
        for it in (src.get("progress_poin") or []):
            if isinstance(it, dict):
                lab = _safe_text(it.get("label") or "", 24)
                try:
                    val = float(it.get("nilai") or 0)
                except (TypeError, ValueError):
                    val = 0.0
                # nilai 0–100 sebagai proporsi visual, bukan klaim — izinkan
                progress_poin.append({"label": lab, "nilai": max(0.0, min(100.0, val))})
            elif isinstance(it, str) and it.strip():
                progress_poin.append({"label": _safe_text(it, 24), "nilai": 0.0})

        sfx = src.get("sfx") or (["pop"] if i == 0 else ["whoosh", "pop"])
        if isinstance(sfx, str):
            sfx = [sfx]
        babs.append({
            "id": i + 1,
            "label": f"{i+1:02d}/{total:02d}",
            "nama": _safe_text(src.get("nama") or sc.get("nama") or f"bab_{i+1}", 24),
            "narasi": sc.get("narasi") or "",
            "layout": layout,
            "judul_layar": judul_layar,
            "subjudul": subjudul,
            "kata_kunci": kata_kunci,
            "ikon": ikon[:4],
            "perbandingan": perbandingan,
            "counter": counter,
            "langkah": langkah[:6],
            "progress_poin": progress_poin[:5],
            "sfx": [str(s) for s in sfx if s][:3],
        })
    script["style"] = "penjelas"
    script["visual"] = {"mode": mode, "bab": babs}
    return script


def cerita_caption(sb: dict) -> str:
    """Caption publik untuk gaya cerita (bukan instruksi internal)."""
    from reels_autopilot.script_writer import build_template_caption, template_hashtags

    hook = (sb.get("hook") or sb.get("moral") or "").strip()
    judul = (sb.get("judul") or "").strip()
    moral = (sb.get("moral") or "").strip()
    if not hook:
        hook = moral or "Yang terus berusaha sampai di ujung."
    # bangun manual supaya moral jadi isi, bukan rubrik
    from reels_autopilot.script_writer import enrich_hook_line
    hook_line = enrich_hook_line(hook, judul)
    isi = moral if moral and moral.lower() not in hook_line.lower() else (
        f"{sb.get('label_kiri') or 'Yang menyerah'} tetap di tempat. "
        f"{sb.get('label_kanan') or 'Yang berusaha'} sampai di ujung."
    )
    cta = "Simpan video ini, biar kamu ingat saat mau nyerah."
    tags = template_hashtags(judul, hook, ["#KreatorAI", "#PoChai", "#Motivasi"])
    parts = [hook_line, "", isi, "", cta, "", " ".join(tags)]
    from reels_autopilot.caption_guard import public_caption_issues
    text = "\n".join(parts)
    if public_caption_issues(text):
        return build_template_caption(hook=hook, judul=judul, cta=cta, hashtag=tags)
    return text
