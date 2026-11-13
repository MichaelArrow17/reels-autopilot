"""Penulis naskah Reels (JSON) — LLM dengan failover, template lokal sebagai cadangan.

Fokus monetisasi: hook selesai <2 detik, 30–40 dtk (batas 45), 1 gagasan/adegan,
caption karaoke-friendly, CTA tunggal, tanpa angka karangan, bahasa Indonesia santai.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from reels_autopilot.config import (
    HARD_MAX_DURATION,
    TARGET_DURATION,
    TARGET_WORDS,
    TARGET_WORDS_MAX,
    TARGET_WORDS_MIN,
    Settings,
    get_settings,
)
from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.providers.llm import LLMClient
from reels_autopilot.providers.router import ProviderRouter

log = logging.getLogger("reels.script")

POSES = ("idle", "point", "think", "cheer", "typing", "walk", "shrug", "sit")


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def trim_to_word_budget(text: str, max_words: int = TARGET_WORDS_MAX) -> str:
    """Potong naskah di batas kalimat terakhir yang masih muat dalam anggaran kata."""
    tokens = (text or "").split()
    if len(tokens) <= max_words:
        return (text or "").strip()
    cut = tokens[:max_words]
    # cari titik/tanya/seru paling belakang di jendela anggaran
    last_end = -1
    for i, tok in enumerate(cut):
        if re.search(r"[.!?…]+$", tok):
            last_end = i
    # sisakan minimal ~70% anggaran supaya hook+isi tidak putus terlalu awal
    min_keep = max(TARGET_WORDS_MIN - 10, int(max_words * 0.7))
    if last_end + 1 >= min_keep:
        cut = cut[: last_end + 1]
    return " ".join(cut).strip()


def clamp_duration_target(seconds: int | float | None) -> int:
    try:
        d = int(seconds or TARGET_DURATION)
    except (TypeError, ValueError):
        d = int(TARGET_DURATION)
    return int(min(HARD_MAX_DURATION, max(30, d)))


def enforce_script_budget(script: dict, max_words: int = TARGET_WORDS_MAX) -> dict:
    narasi = trim_to_word_budget(script.get("narasi_penuh") or "", max_words)
    script["narasi_penuh"] = narasi
    script["durasi_target_detik"] = clamp_duration_target(script.get("durasi_target_detik"))
    return script



def is_thin_hook(hook: str) -> bool:
    """Hook tipis: kosong atau kurang dari 8 kata (mis. hanya 'cara pakai ai?')."""
    words = re.findall(r"\w+", hook or "", flags=re.UNICODE)
    return len(words) < 8


def enrich_hook_line(hook: str, judul: str | None = None) -> str:
    """Baris hook caption: pertahankan yang sudah utuh, perkaya yang hanya judul pendek."""
    raw = (hook or "").strip() or (judul or "").strip()
    if raw and not is_thin_hook(raw):
        if raw[-1] not in ".!?…":
            raw = raw + "."
        return raw
    topic = (judul or hook or "AI").strip()
    topic = re.sub(r"[?!.]+$", "", topic).strip() or "AI"
    # jangan mengarang fakta; bungkus topik jadi hook rasa penasaran
    return f"Masih bingung soal {topic}? Ini cara praktis yang bisa kamu coba."


def template_value_lines(topic: str = "") -> list[str]:
    """1–2 baris nilai tentang topik, bukan instruksi gaya/rubrik."""
    clean = re.sub(r"[?!.]+$", "", (topic or "").strip()) or "ini"
    return [
        f"Banyak yang sudah dengar soal {clean}, tapi jarang dijelaskan pelan biar bisa langsung dicoba.",
        "Ambil satu langkah kecil hari ini, lalu lihat sendiri hasilnya.",
    ]


def template_hashtags(
    judul: str = "",
    hook: str = "",
    existing: list[str] | None = None,
) -> list[str]:
    """3–5 hashtag relevan, utamakan bahasa Indonesia."""
    text = f"{judul} {hook}".lower()
    out: list[str] = []

    def add(tag: str) -> None:
        tag = (tag or "").strip()
        if not tag:
            return
        if not tag.startswith("#"):
            tag = "#" + tag
        if tag not in out and len(out) < 5:
            out.append(tag)

    for t in existing or []:
        add(t)
    for t in ("#KreatorAI", "#PoChai", "#ReelsIndonesia"):
        add(t)
    extras: list[str] = []
    if any(k in text for k in ("ai", "chatgpt", "gemini", "llm", "kecerdasan")):
        extras += ["#TipsAI", "#BelajarAI"]
    if any(k in text for k in ("reels", "konten", "kreator", "faceless", "video", "caption", "hook")):
        extras.append("#KontenKreator")
    extras += ["#TipsKonten", "#BelajarAI", "#TipsAI", "#KontenKreator"]
    for t in extras:
        add(t)
    return out[:5]


def build_template_caption(
    *,
    hook: str = "",
    judul: str = "",
    cta: str | None = None,
    hashtag: list[str] | None = None,
) -> str:
    """Caption cadangan: hook + 1–2 baris nilai + CTA + 3–5 hashtag."""
    hook_line = enrich_hook_line(hook, judul)
    values = template_value_lines(judul or hook)
    cta_line = (cta or "Simpan video ini, atau follow buat tip berikutnya.").strip()
    tags = template_hashtags(judul, hook, hashtag)
    parts = [hook_line, "", values[0]]
    if len(values) > 1:
        parts.append(values[1])
    parts += ["", cta_line, "", " ".join(tags)]
    text = "\n".join(parts)
    if public_caption_issues(text):
        raise RuntimeError("template caption masih memuat instruksi internal")
    return text


def assemble_public_caption(script: dict, caps: dict | None = None) -> str:
    """Susun caption publik dari varian LLM, atau template bersih jika bocor/kosong."""
    if caps and caps.get("varian"):
        v0 = caps["varian"][0] or {}
        text = "\n".join(
            filter(
                None,
                [
                    v0.get("baris1"),
                    v0.get("isi"),
                    v0.get("cta"),
                    v0.get("pertanyaan"),
                    " ".join(v0.get("hashtag") or []),
                ],
            )
        )
        if text.strip() and not public_caption_issues(text):
            return text
    raw = (script.get("caption") or "").strip()
    if raw and not public_caption_issues(raw):
        return raw
    return build_template_caption(
        hook=script.get("hook") or "",
        judul=script.get("judul") or "",
        cta=script.get("cta"),
        hashtag=script.get("hashtag") if isinstance(script.get("hashtag"), list) else None,
    )


def _caption_pack_is_clean(data: dict) -> bool:
    for varian in data.get("varian") or []:
        if not isinstance(varian, dict):
            return False
        blob = " ".join(
            str(varian.get(k) or "")
            for k in ("baris1", "isi", "cta", "pertanyaan")
        )
        blob += " " + " ".join(varian.get("hashtag") or [])
        if public_caption_issues(blob):
            return False
    return bool(data.get("varian"))


class ScriptWriter:
    def __init__(self, settings: Settings | None = None, router: ProviderRouter | None = None):
        self.settings = settings or get_settings()
        self.router = router or ProviderRouter(self.settings)
        self.llm = LLMClient(self.settings, self.router)

    def write(self, topic: dict) -> dict:
        system = _load_prompt(self.settings, "script_writer.txt", _DEFAULT_SCRIPT_PROMPT)
        user = json.dumps(
            {
                "TOPIK": topic,
                "DURASI_TARGET_DETIK": int(TARGET_DURATION),
                "DURASI_MAKS_DETIK": int(HARD_MAX_DURATION),
                "KATA_TARGET": TARGET_WORDS,
                "KATA_MIN": TARGET_WORDS_MIN,
                "KATA_MAX": TARGET_WORDS_MAX,
                "BAHASA": "Indonesia santai, orang kedua (kamu)",
                "GAYA": "explainer stickman Po Chai, Kreator AI",
            },
            ensure_ascii=False,
        )
        try:
            data, provider = self.llm.generate_json(user, system=system)
        except Exception as e:
            log.warning("LLM naskah gagal (%s), pakai template", e)
            data, provider = {"_template": True}, "template"
        if provider == "template" or (isinstance(data, dict) and data.get("_template")):
            script = enforce_script_budget(fallback_script(topic))
            script["llm_provider"] = "template"
            return script
        script = enforce_script_budget(_normalize(data, topic))
        script["llm_provider"] = provider
        return script

    def captions(self, script: dict) -> dict:
        """3 varian caption (playbook 9.4). Template jika LLM absen."""
        system = _load_prompt(self.settings, "caption.txt", _DEFAULT_CAPTION_PROMPT)
        try:
            data, provider = self.llm.generate_json(
                json.dumps({"judul": script.get("judul"), "naskah": script.get("narasi_penuh")}, ensure_ascii=False),
                system=system,
            )
            if provider != "template" and isinstance(data, dict) and not data.get("_template"):
                if _caption_pack_is_clean(data):
                    data["llm_provider"] = provider
                    return data
                log.warning("Caption LLM memuat instruksi internal; ganti template bersih")
        except Exception as e:
            log.info("caption LLM gagal: %s", e)
        return fallback_captions(script)


def _load_prompt(settings: Settings, name: str, default: str) -> str:
    p = settings.prompts_dir / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return default


def _normalize(data: dict, topic: dict) -> dict:
    narasi = (data.get("narasi_penuh") or "").strip()
    if _word_count(narasi) < TARGET_WORDS_MIN:
        # terlalu pendek — gabung dari adegan
        parts = [a.get("narasi") or "" for a in data.get("adegan") or []]
        if parts:
            narasi = " ".join(parts)
    narasi = trim_to_word_budget(narasi, TARGET_WORDS_MAX)
    adegan = data.get("adegan") or []
    clean = []
    for i, a in enumerate(adegan[:6], 1):
        pose = (a.get("pose") or "idle").lower()
        if pose not in POSES:
            pose = POSES[(i - 1) % len(POSES)]
        clean.append({
            "id": a.get("id", i),
            "nama": a.get("nama") or f"adegan_{i}",
            "narasi": a.get("narasi") or "",
            "teks_layar": a.get("teks_layar") or a.get("keyword") or "",
            "pose": pose,
            "keyword": a.get("keyword") or "",
            "latar": a.get("latar") or "",
            "image_query": a.get("image_query") or "",
        })
    if not clean:
        return fallback_script(topic)
    hook = data.get("hook") or topic.get("hook") or (narasi.split(".")[0] if narasi else topic.get("judul"))
    return {
        "judul": data.get("judul") or topic.get("judul") or "Tanpa judul",
        "hook": hook,
        "angle": data.get("angle") or topic.get("angle") or "",
        "bahasa": "id",
        "durasi_target_detik": clamp_duration_target(data.get("durasi_target_detik")),
        "narasi_penuh": narasi,
        "adegan": clean,
        "caption": (
            data.get("caption")
            if (data.get("caption") and not public_caption_issues(data.get("caption")))
            else build_template_caption(
                hook=str(hook or ""),
                judul=str(data.get("judul") or topic.get("judul") or ""),
                cta=data.get("cta"),
                hashtag=data.get("hashtag") if isinstance(data.get("hashtag"), list) else None,
            )
        ),
        "cta": data.get("cta") or "Simpan video ini.",
        "hashtag": data.get("hashtag") or ["#KreatorAI", "#PoChai", "#ReelsIndonesia", "#FacelessContent"],
        "fakta_yang_wajib_dicek": data.get("fakta_yang_wajib_dicek") or topic.get("fakta_yang_wajib_dicek") or [],
        "is_ai_generated": True,
        "cover_text": data.get("cover_text") or hook,
        "image_query": data.get("image_query") or "",
    }


def fallback_script(topic: dict) -> dict:
    """Naskah template retensi-friendly, tanpa angka karangan."""
    judul = topic.get("judul") or "Kenapa kreator bisa unggah Reels tanpa kamera"
    hook = topic.get("hook") or "Kamu nggak perlu kamera untuk mulai unggah Reels."
    angle = topic.get("angle") or "Workflow programmatic untuk kreator Indonesia."
    beats = topic.get("beats") or [
        "Hook: tanpa kamera pun bisa mulai.",
        "Tubuh: naskah, suara, render, jadwal.",
        "Payoff: ukur retensi, ulang yang berhasil.",
    ]
    # ~75–100 kata, orang kedua, tanpa "di video ini", 1 CTA, target 30–40 dtk
    narasi = (
        f"{hook.rstrip('.')}. "
        "Satu naskah, satu suara, dan gambar dari kode sudah cukup jadi video vertikal siap tayang. "
        "Bukan sihir, dan bukan aplikasi yang tinggal ketik prompt lalu selesai. Ini workflow programmatic. "
        "Pagi, pilih topik yang punya rasa penasaran, buang yang berbahaya atau sudah pernah dibuat. "
        "Naskahnya singkat, hook-nya cepat, dan tiap langkah jelas. "
        "Suara otomatis, gambar dirender, lalu file dijadwalkan. Kamu setujui atau tolak lewat Telegram. "
        "AI yang kerja, kamu yang punya arah. Simpan video ini."
    )
    # jika topik spesifik, bungkus hook + kerangka tanpa mengarang fakta
    if topic.get("judul") and "kamera" not in judul.lower() and "reels" not in (hook.lower()):
        narasi = (
            f"{hook.rstrip('.')}. "
            f"Banyak yang sudah mendengar soal “{judul.rstrip('?')}”, tapi jarang dijelaskan pelan. "
            "Kita mulai dari rasa penasaran, bukan definisi, biar mudah diingat. "
            "Yang dibahas hanya yang masuk akal dan bisa kamu cek sendiri. "
            "Visualnya sederhana: karakter, teks di layar, suara yang jelas. "
            "Tujuannya biar kamu tahan nonton sampai akhir, lalu bisa coba sendiri. "
            "Kalau nyambung, simpan videonya. AI bisa bantu naskah, arah tetap di tangan kamu."
        )
    adegan = [
        {"id": 1, "nama": "hook", "narasi": hook, "teks_layar": hook, "pose": "idle", "keyword": "HOOK", "latar": "", "image_query": ""},
        {"id": 2, "nama": "konteks", "narasi": beats[0] if beats else "", "teks_layar": "Bukan sihir", "pose": "think", "keyword": "WORKFLOW", "latar": "", "image_query": ""},
        {"id": 3, "nama": "konflik", "narasi": beats[1] if len(beats) > 1 else "", "teks_layar": "Satu ide, satu langkah", "pose": "point", "keyword": "1 IDE", "latar": "", "image_query": ""},
        {"id": 4, "nama": "payoff", "narasi": beats[2] if len(beats) > 2 else "", "teks_layar": "Cek fakta, baru tayang", "pose": "typing", "keyword": "CEK FAKTA", "latar": "", "image_query": ""},
        {"id": 5, "nama": "cta", "narasi": "Simpan video ini kalau mau ikut alurnya.", "teks_layar": "Simpan · Follow", "pose": "cheer", "keyword": "SIMPAN", "latar": "", "image_query": ""},
    ]
    caption = build_template_caption(hook=hook, judul=judul, cta="Simpan video ini, atau follow buat tip berikutnya.")
    return enforce_script_budget({
        "judul": judul,
        "hook": hook,
        "angle": angle,
        "bahasa": "id",
        "durasi_target_detik": int(TARGET_DURATION),
        "narasi_penuh": narasi,
        "adegan": adegan,
        "caption": caption,
        "cta": "Simpan video ini, atau follow buat tip berikutnya.",
        "hashtag": template_hashtags(judul, hook),
        "fakta_yang_wajib_dicek": topic.get("fakta_yang_wajib_dicek") or [],
        "is_ai_generated": True,
        "cover_text": hook if len(hook.split()) <= 8 else " ".join(hook.split()[:6]),
        "image_query": "dark studio creative desk indonesia",
        "llm_provider": "template",
    })


def fallback_captions(script: dict) -> dict:
    hook = script.get("hook") or script.get("judul") or "Tonton sampai akhir."
    judul = script.get("judul") or hook
    hook_line = enrich_hook_line(hook, judul)
    values = template_value_lines(judul)
    tags = template_hashtags(judul, hook, script.get("hashtag"))
    cta = script.get("cta") or "Simpan video ini, atau follow buat tip berikutnya."
    return {
        "varian": [
            {
                "baris1": hook_line[:90],
                "isi": " ".join(values),
                "cta": cta,
                "pertanyaan": "Bagian mana yang mau kamu coba dulu?",
                "hashtag": tags,
            }
        ],
        "cover": script.get("cover_text") or hook_line,
        "komentar_pin": "Pertanyaan? Tulis di komentar, bro.",
        "llm_provider": "template",
    }


_DEFAULT_SCRIPT_PROMPT = """PERAN: Kamu penulis naskah voice-over untuk Reels explainer stickman berbahasa Indonesia santai, akun "Po Chai" (Kreator AI + Penulis).
ATURAN:
- Tulis untuk TELINGA: satu ide per kalimat, campur pendek & panjang, tanpa jargon.
- Hook SELESAI dalam 2 detik pertama. Dilarang: "Di video ini...", "Halo guys...".
- Durasi target 35 detik ≈ 90 kata (75–100 kata, ±2,5–3 kata/detik). Target 30–40 detik, batas keras 45 detik.
- Setiap angka di layar harus diucapkan. JANGAN menambah angka yang tidak ada di input.
- Akhiri dengan SATU ajakan (simpan ATAU follow part 2).
- Orang kedua ("kamu"), tanpa kata sifat pengisi.
- 5 adegan. Pose stickman hanya: idle, point, think, cheer, typing, walk, shrug, sit.
- Adegan 1 (2 detik pertama) adalah hook: karakter BELUM muncul (teks masalah penonton).
OUTPUT HANYA JSON valid:
{"judul":"","hook":"","angle":"","durasi_target_detik":35,"narasi_penuh":"",
 "adegan":[{"id":1,"nama":"hook","narasi":"","teks_layar":"","pose":"idle","keyword":"","latar":"","image_query":""}],
 "caption":"","cta":"","hashtag":[],"fakta_yang_wajib_dicek":[],"cover_text":"","is_ai_generated":true}
"""

_DEFAULT_CAPTION_PROMPT = """PERAN: copywriter caption Reels "Po Chai" (Kreator AI + Penulis).
Buat 3 varian: baris 1 ≤90 karakter (ulangi hook), 2–3 baris isi HANYA dari naskah, 1 CTA, 1 pertanyaan komentar, 3–5 hashtag (ID + 1 EN).
OUTPUT HANYA JSON: {"varian":[...],"cover":"","komentar_pin":""}
"""
