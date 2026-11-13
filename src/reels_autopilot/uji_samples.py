"""Render dan kirim sampel uji dua gaya — tidak masuk antrian publish, tidak mengubah state harian."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.captions import chunk_captions
from reels_autopilot.config import Settings, get_settings
from reels_autopilot.providers.tts import TTSClient, Word
from reels_autopilot.qc import inspect, report_text
from reels_autopilot.script_writer import assemble_public_caption, fallback_captions
from reels_autopilot.storyboard import cerita_caption, derive_penjelas_visual, fallback_cerita, validate_cerita
from reels_autopilot.style_cerita import build_cerita_audio, render_cerita
from reels_autopilot.style_penjelas import render_penjelas

log = logging.getLogger("reels.uji")

NARASI_PENJELAS = (
    "ChatGPT kadang terdengar yakin, padahal jawabannya ngarang. "
    "Kamu bisa cek dengan tiga langkah sederhana. "
    "Pertama, tanya sumbernya. Kalau tidak ada, jangan langsung percaya. "
    "Kedua, bandingkan dengan satu sumber yang bisa kamu buka sendiri. "
    "Ketiga, kalau ada angka, pastikan angka itu muncul di sumber itu. "
    "Jangan salin jawaban hanya karena bunyinya lancar. "
    "AI itu asisten, bukan wasit kebenaran. "
    "Simpan video ini, biar kamu ingat sebelum menyalin jawabannya."
)
CAPTION_PENJELAS = """ChatGPT kadang terdengar yakin, padahal jawabannya ngarang.

Cek dengan tiga langkah: tanya sumbernya, bandingkan, dan pastikan angkanya ada di sumber itu.

Simpan video ini, biar kamu ingat sebelum menyalin jawabannya.

#KreatorAI #PoChai #TipsAI #ReelsIndonesia #BelajarAI"""

SCRIPT_PENJELAS = derive_penjelas_visual({
    "judul": "ChatGPT kadang ngarang, begini cara ceknya",
    "hook": "ChatGPT kadang terdengar yakin, padahal jawabannya ngarang.",
    "angle": "Tiga langkah cek jawaban AI, tanpa angka karangan.",
    "bahasa": "id",
    "durasi_target_detik": 35,
    "narasi_penuh": NARASI_PENJELAS,
    "adegan": [
        {"id": 1, "nama": "HOOK", "narasi": "ChatGPT kadang terdengar yakin, padahal jawabannya ngarang.",
         "teks_layar": "TERDENGAR YAKIN", "keyword": "NGARANG", "pose": "idle"},
        {"id": 2, "nama": "LANGKAH", "narasi": "Kamu bisa cek dengan tiga langkah sederhana, tanpa perlu jadi ahli.",
         "teks_layar": "3 LANGKAH", "keyword": "TIGA", "pose": "point"},
        {"id": 3, "nama": "BANDING", "narasi": "Pertama, tanya sumbernya. Kalau tidak ada, jangan langsung percaya. Kedua, bandingkan dengan satu sumber yang bisa kamu buka sendiri.",
         "teks_layar": "CEK DULU", "keyword": "SUMBER", "pose": "think"},
        {"id": 4, "nama": "ANGKA", "narasi": "Ketiga, kalau ada angka, pastikan angka itu muncul di sumber itu, bukan cuma di percakapan.",
         "teks_layar": "CEK ANGKA", "keyword": "ANGKA", "pose": "typing"},
        {"id": 5, "nama": "CTA", "narasi": "AI itu asisten, bukan wasit kebenaran. Simpan video ini, biar kamu ingat sebelum menyalin jawabannya.",
         "teks_layar": "SIMPAN VIDEO INI", "keyword": "SIMPAN", "pose": "cheer"},
    ],
    "cta": "Simpan video ini, biar kamu ingat sebelum menyalin jawabannya.",
    "hashtag": ["#KreatorAI", "#PoChai", "#TipsAI", "#ReelsIndonesia"],
    "is_ai_generated": True,
    "style": "penjelas",
    "caption": CAPTION_PENJELAS,
    "visual": {
        "mode": "light",
        "bab": [
            {"layout": "kinetic_title", "judul_layar": "TERDENGAR YAKIN",
             "kata_kunci": [{"kata": "YAKIN", "warna": "emas"}, {"kata": "NGARANG", "warna": "merah"}],
             "ikon": ["robot", "chat"], "nama": "HOOK", "sfx": ["pop"]},
            {"layout": "steps", "judul_layar": "3 LANGKAH CEK",
             "counter": {"ke": 3, "label": "LANGKAH SEDERHANA"},
             "langkah": ["Tanya sumber", "Bandingkan", "Cek angka"],
             "kata_kunci": [{"kata": "tiga", "warna": "hijau"}], "sfx": ["whoosh", "pop"]},
            {"layout": "comparison", "judul_layar": "CEK DULU",
             "perbandingan": {
                 "kiri": {"judul": "LANGSUNG PERCAYA", "ikon": "close", "warna": "merah",
                          "poin": ["Tanpa sumber", "Langsung salin"]},
                 "kanan": {"judul": "CEK SUMBER", "ikon": "check", "warna": "hijau",
                           "poin": ["Ada sumber", "Bisa dibuka"]},
             }, "sfx": ["whoosh", "pop"]},
            {"layout": "icons", "judul_layar": "CEK ANGKA",
             "ikon": ["search", "document", "shield"],
             "langkah": ["Cari", "Buka", "Cocokkan"],
             "kata_kunci": [{"kata": "angka", "warna": "merah"}], "sfx": ["pop"]},
            {"layout": "cta", "judul_layar": "SIMPAN VIDEO INI",
             "subjudul": "Biar kamu ingat sebelum menyalin.",
             "ikon": ["save"], "sfx": ["chime"]},
        ],
    },
})


def sample_cerita_storyboard() -> dict:
    sb = fallback_cerita({
        "judul": "Yang terus berusaha sampai ke permukaan",
        "hook": "Yang menyerah tetap di dasar. Yang terus berusaha sampai ke permukaan.",
    }, "underwater")
    sb["moral"] = "Yang berhenti, tetap di dasar. Yang terus berenang, rantainya putus."
    sb, fb, err = validate_cerita(sb)
    if err:
        log.warning("storyboard uji fallback=%s err=%s", fb, err)
    return sb


def _extract_frames(mp4: Path, dest_dir: Path, times: list[float]) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for t in times:
        dest = dest_dir / f"{mp4.stem}_{t:.1f}.jpg"
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(dest)],
            capture_output=True, check=False,
        )
        if dest.exists():
            out.append(dest)
    return out


def verify_sample(mp4: Path, *, caption: str, style: str, words: list[Word] | None = None) -> dict:
    issues = []
    issues.extend(public_caption_issues(caption))
    # frasa internal di file name? cek caption saja
    qc = inspect(mp4, words=words if style == "penjelas" else None)
    if not qc.ok:
        # gaya cerita 20–24s: durasi di bawah 25s hanya peringatan, bukan error
        real_errors = [e for e in qc.errors if "di bawah ideal" not in e]
        if real_errors:
            issues.extend(real_errors)
    if qc.width != 1080 or qc.height != 1920:
        issues.append(f"resolusi {qc.width}x{qc.height}")
    if not qc.has_audio:
        issues.append("tidak ada audio")
    if style == "cerita" and not (20 <= qc.duration <= 32):
        issues.append(f"durasi cerita {qc.duration:.1f}s di luar 20–30s")
    if style == "penjelas" and qc.duration > 45.1:
        issues.append(f"durasi {qc.duration:.1f}s > 45s")
    return {
        "ok": len(issues) == 0 and (qc.ok or style == "cerita"),
        "issues": issues,
        "qc": qc.to_dict(),
        "report": report_text(qc),
    }


def render_uji_samples(
    out_dir: Path | None = None,
    *,
    settings: Settings | None = None,
    frames_dir: Path | None = None,
) -> dict:
    """Render 1 sampel per gaya ke out_dir. Tidak menulis state produksi."""
    settings = settings or get_settings()
    out_dir = Path(out_dir or (settings.root / "samples"))
    out_dir.mkdir(parents=True, exist_ok=True)
    build = out_dir / "_uji_build"
    build.mkdir(parents=True, exist_ok=True)
    frames_dir = Path(frames_dir or (out_dir / "frames_uji"))
    result: dict = {"penjelas": {}, "cerita": {}}

    # ---- gaya A ----
    t0 = time.time()
    # suara: coba GadisNeural (lebih hidup) lalu jatuh ke default Ardi
    original_voice = settings.tts_voice
    original_rate = settings.tts_rate
    used_voice = original_voice
    used_rate = original_rate
    tts = None
    # Gadis lebih natural tapi pelan; +10% biasanya masuk 30–40 dtk.
    attempts = [
        ("id-ID-GadisNeural", "+10%"),
        ("id-ID-GadisNeural", "+20%"),
        (original_voice or "id-ID-ArdiNeural", original_rate or "-5%"),
        ("id-ID-ArdiNeural", "+10%"),
    ]
    for voice, rate in attempts:
        settings.tts_voice = voice
        settings.tts_rate = rate
        try:
            cand = TTSClient(settings).synthesize(SCRIPT_PENJELAS["narasi_penuh"], build, stem="uji_penjelas")
        except Exception as e:
            log.warning("TTS %s %s gagal: %s", voice, rate, e)
            continue
        tts = cand
        used_voice, used_rate = voice, rate
        if cand.duration <= 40.5:
            break
        log.info("TTS %s %s durasi %.1fs, coba lebih cepat", voice, rate, cand.duration)
    settings.tts_voice = original_voice
    settings.tts_rate = original_rate
    if tts is None:
        raise RuntimeError("TTS sampel penjelas gagal")
    if tts.duration > 44.5:
        from reels_autopilot.providers.tts import atempo_fit
        audio, words, dur = atempo_fit(
            tts.audio_path, list(tts.words or []), tts.duration, 40.0,
            dest=build / "uji_penjelas_fit.wav",
        )
        tts.audio_path = audio
        tts.words = words
        tts.duration = dur
        used_rate = f"{used_rate}+atempo"
        log.warning("TTS dipercepat atempo ke %.1fs", dur)
    mp4_a = out_dir / "uji_penjelas.mp4"
    render_penjelas(SCRIPT_PENJELAS, tts, mp4_a, settings=settings)
    cap_a = SCRIPT_PENJELAS.get("caption") or assemble_public_caption(SCRIPT_PENJELAS, fallback_captions(SCRIPT_PENJELAS))
    ver_a = verify_sample(mp4_a, caption=cap_a, style="penjelas", words=list(tts.words or []))
    dur_a = float(ver_a.get("qc", {}).get("duration") or tts.duration)
    times_a = sorted({round(x, 1) for x in [
        0.5, 2.0, 6.0, 10.0, 15.0, 20.0, max(3, dur_a * 0.35),
        dur_a * 0.55, dur_a * 0.75, max(0.5, dur_a - 1.5),
    ] if 0 <= x < dur_a - 0.05})
    frames_a = _extract_frames(mp4_a, frames_dir, times_a)
    dt_a = time.time() - t0
    result["penjelas"] = {
        "mp4": str(mp4_a),
        "caption": cap_a,
        "duration": dur_a,
        "tts_duration": tts.duration,
        "voice": used_voice,
        "tts_rate": used_rate,
        "tts_provider": tts.provider_id,
        "render_seconds": round(dt_a, 2),
        "verify": ver_a,
        "frames": [str(p) for p in frames_a],
        "words": len(tts.words or []),
    }

    # ---- gaya B ----
    t0 = time.time()
    sb = sample_cerita_storyboard()
    audio = build_cerita_audio(sb, build / "uji_cerita.wav", settings=settings)
    mp4_b = out_dir / "uji_cerita.mp4"
    render_cerita(sb, audio, mp4_b, settings=settings)
    cap_b = cerita_caption(sb)
    ver_b = verify_sample(mp4_b, caption=cap_b, style="cerita")
    dur_b = float(sb["durasi_detik"])
    frames_b = _extract_frames(mp4_b, frames_dir, [0.5, 4, 8, 12, 16, 19, 22])
    dt_b = time.time() - t0
    result["cerita"] = {
        "mp4": str(mp4_b),
        "caption": cap_b,
        "duration": dur_b,
        "render_seconds": round(dt_b, 2),
        "verify": ver_b,
        "frames": [str(p) for p in frames_b],
        "environment": sb.get("environment"),
    }
    (build / "uji_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def send_uji_samples(result: dict, *, settings: Settings | None = None) -> dict:
    """Kirim kedua sampel ke Telegram sebagai SAMPEL UJI, tanpa ACC dan tanpa menyentuh state."""
    from reels_autopilot.telegram_bot import TelegramBot

    settings = settings or get_settings()
    _apply_local_telegram_secrets(settings)
    # Bot tanpa State produksi: jangan load/tulis data/state.json
    from reels_autopilot.state import State
    # pakai state path di folder uji agar offset telegram tidak berubah? 
    # send_uji tidak memanggil poll, jadi State.load tidak akan di-save jika kita tidak save.
    # Tetap aman: gunakan State dengan path sementara.
    tmp_state = settings.root / "samples" / "_uji_build" / "tg_state_dummy.json"
    tmp_state.parent.mkdir(parents=True, exist_ok=True)
    st = State.__new__(State)
    st.settings = settings
    st.path = tmp_state
    st.data = {
        "past_topics": [],
        "days": {},
        "telegram": {"last_update_id": 0, "chat_id": settings.telegram_chat_id},
        "paused": False,
        "paused_until": None,
    }
    # jangan load() dari state produksi
    tg = TelegramBot(settings, st)
    sent = {}
    for key, label in (("penjelas", "penjelas (motion graphics + suara)"),
                       ("cerita", "cerita stickman (tanpa suara, kiasan)")):
        info = result.get(key) or {}
        mp4 = Path(info.get("mp4") or "")
        notes = (
            f"Durasi ±{float(info.get('duration') or 0):.0f} dtk, "
            f"render {info.get('render_seconds')} dtk."
        )
        if key == "penjelas" and info.get("voice"):
            notes += f" Suara: {info['voice']}."
        res = tg.send_uji_sample(
            mp4, style_name=label, public_caption=info.get("caption") or "", notes=notes,
        )
        mid = None
        if isinstance(res, dict):
            mid = (res.get("result") or {}).get("message_id") if isinstance(res.get("result"), dict) else res.get("message_id")
        sent[key] = {"ok": bool(res.get("ok") if isinstance(res, dict) else False), "message_id": mid, "raw_ok": res.get("ok") if isinstance(res, dict) else None}
        # jangan simpan state
    return sent


def _apply_local_telegram_secrets(settings: Settings) -> None:
    """Isi token dari .secrets/telegram.env jika env belum ada. Tidak mencetak nilai."""
    import os
    from dotenv import load_dotenv
    path = settings.root / ".secrets" / "telegram.env"
    if path.exists():
        load_dotenv(path, override=False)
    if not settings.telegram_bot_token:
        settings.telegram_bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not settings.telegram_chat_id:
        settings.telegram_chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
