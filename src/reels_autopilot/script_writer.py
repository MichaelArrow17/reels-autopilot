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
                data["llm_provider"] = provider
                return data
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
        "caption": data.get("caption") or "",
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
        "Naskah ditulis untuk telinga. Hook selesai dalam dua detik. Satu gagasan per adegan, setiap klaim dicek. "
        "Suara otomatis, stickman dirender, lalu file dijadwalkan. Kamu setujui atau tolak lewat Telegram. "
        "AI yang kerja, kamu yang punya arah. Simpan video ini."
    )
    # jika topik spesifik, bungkus hook + kerangka tanpa mengarang fakta
    if topic.get("judul") and "kamera" not in judul.lower() and "reels" not in (hook.lower()):
        narasi = (
            f"{hook.rstrip('.')}. "
            f"Banyak yang sudah mendengar soal “{judul.rstrip('?')}”, tapi jarang dijelaskan pelan. "
            "Kita mulai dari rasa penasaran, bukan definisi. Satu gagasan per adegan, biar mudah diingat. "
            "Klaim hanya yang bisa dicek — tidak ada angka yang dikarang. "
            "Visualnya sederhana: stickman, teks di layar, suara yang jelas. "
            "Tujuannya biar kamu tahan nonton sampai akhir, lalu bisa coba sendiri. "
            "Kalau nyambung, simpan videonya. AI bisa bantu naskah, arah tetap di tangan kamu."
        )
    adegan = [
        {"id": 1, "nama": "hook", "narasi": hook, "teks_layar": hook, "pose": "idle", "keyword": "HOOK", "latar": "", "image_query": ""},
        {"id": 2, "nama": "konteks", "narasi": beats[0] if beats else "", "teks_layar": "Bukan sihir", "pose": "think", "keyword": "WORKFLOW", "latar": "", "image_query": ""},
        {"id": 3, "nama": "konflik", "narasi": beats[1] if len(beats) > 1 else "", "teks_layar": "Satu gagasan, satu adegan", "pose": "point", "keyword": "1 IDE", "latar": "", "image_query": ""},
        {"id": 4, "nama": "payoff", "narasi": beats[2] if len(beats) > 2 else "", "teks_layar": "Cek fakta, baru tayang", "pose": "typing", "keyword": "CEK FAKTA", "latar": "", "image_query": ""},
        {"id": 5, "nama": "cta", "narasi": "Simpan video ini kalau mau ikut alurnya.", "teks_layar": "Simpan · Follow", "pose": "cheer", "keyword": "SIMPAN", "latar": "", "image_query": ""},
    ]
    caption = (
        f"{hook}\n\n"
        "Explainer singkat untuk kreator Indonesia. Tanpa angka karangan.\n"
        "Simpan kalau mau dipraktekkan.\n\n"
        "Menurutmu, bagian mana yang paling susah: naskah, suara, atau jadwal?\n\n"
        "#KreatorAI #PoChai #ReelsIndonesia #FacelessContent #VideoAI"
    )
    return enforce_script_budget({
        "judul": judul,
        "hook": hook,
        "angle": angle,
        "bahasa": "id",
        "durasi_target_detik": int(TARGET_DURATION),
        "narasi_penuh": narasi,
        "adegan": adegan,
        "caption": caption,
        "cta": "Simpan video ini.",
        "hashtag": ["#KreatorAI", "#PoChai", "#ReelsIndonesia", "#FacelessContent", "#VideoAI"],
        "fakta_yang_wajib_dicek": topic.get("fakta_yang_wajib_dicek") or [],
        "is_ai_generated": True,
        "cover_text": hook if len(hook.split()) <= 8 else " ".join(hook.split()[:6]),
        "image_query": "dark studio creative desk indonesia",
        "llm_provider": "template",
    })


def fallback_captions(script: dict) -> dict:
    hook = script.get("hook") or script.get("judul") or "Tonton sampai akhir."
    return {
        "varian": [
            {
                "baris1": hook[:90],
                "isi": "Explainer singkat, satu gagasan per adegan. Tanpa angka yang dikarang.",
                "cta": script.get("cta") or "Simpan video ini.",
                "pertanyaan": "Bagian mana yang mau kamu coba dulu?",
                "hashtag": script.get("hashtag") or ["#KreatorAI", "#PoChai"],
            }
        ],
        "cover": script.get("cover_text") or hook,
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
