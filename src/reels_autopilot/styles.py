"""Pemilih gaya visual: penjelas, cerita stickman, kolase scrapbook; rotasi agar 3 gaya muncul tiap hari."""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("reels.styles")

STYLE_PENJELAS = "penjelas"
STYLE_CERITA = "cerita"
STYLE_KOLASE = "kolase"
# Gaya lama (renderer stickman+keyword asli) TIDAK masuk daftar ini — tidak bisa dipilih.
STYLES = (STYLE_PENJELAS, STYLE_CERITA, STYLE_KOLASE)

# Kata kunci topik info (teknologi, AI, keuangan, tips).
_INFO_WORDS = (
    "ai", "chatgpt", "gemini", "llm", "gpt", "kecerdasan", "algoritma", "prompt",
    "teknologi", "teknologi", "aplikasi", "software", "gadget", "iphone", "android",
    "hp", "ponsel", "internet", "data", "privasi", "keamanan", "password", "sandi",
    "investasi", "saham", "keuangan", "finansial", "uang", "bank", "tabungan",
    "bunga", "inflasi", "pajak", "gaji", "crypto", "bitcoin", "reksadana",
    "tips", "cara", "tutorial", "belajar", "panduan", "langkah", "fitur",
    "reels", "instagram", "konten", "kreator", "capcut", "editing", "caption",
    "hook", "tools", "tool", "otomasi", "otonom", "robot", "chatbot",
    "hukum", "undang", "kontrak", "kerja", "kesehatan", "sains", "riset",
    "apple", "google", "meta", "tesla", "xpeng", "startup", "saham",
    "cek fakta", "halusinasi", "sumber", "fact",
)

# Kata kunci motivasi / kiasan.
_MOTIV_WORDS = (
    "motivasi", "semangat", "menyerah", "nyerah", "berhasil", "gagal",
    "mimpi", "perjuangan", "berjuang", "kebiasaan", "disiplin", "fokus",
    "mental", "inspirasi", "bangkit", "rantai", "metafora", "kiasan",
    "sabar", "konsisten", "usaha", "berusaha", "sukses", "takut",
    "comfort zone", "zona nyaman", "prokrastinasi", "malas", "tekun",
    "pantang", "tabah", "harapan", "impian", "tujuan", "komitmen",
    "jangan nyerah", "terus mencoba", "bangkit lagi", "lebih kuat",
    "nasib", "keberuntungan", "usaha penuh",
)

# Kata kunci profil / sejarah / biografi → kolase scrapbook.
_PROFIL_WORDS = (
    "profil", "biografi", "biografis", "riwayat hidup", "kisah hidup",
    "tokoh", "tokoh sejarah", "sejarah hidup", "sejarahnya",
    "pendiri", "penemu", "penemuannya", "founder", "inventor",
    "lahir tahun", "lahir pada", "dilahirkan",
    "masa muda", "warisan hidup", "jejak hidup",
    "timeline hidup", "perjalanan hidup", "kisah tokoh",
    "siapa dia", "siapa beliau", "mengenal sosok",
)

_WORD_RE = re.compile(r"[a-z0-9]+", re.I)


def _blob(topic: dict | str | None) -> str:
    if topic is None:
        return ""
    if isinstance(topic, str):
        return topic.lower()
    parts = [
        topic.get("judul") or "",
        topic.get("hook") or "",
        topic.get("angle") or "",
        topic.get("tipe") or "",
        topic.get("kategori") or "",
        " ".join(topic.get("tags") or []),
        " ".join(topic.get("alasan") or []) if isinstance(topic.get("alasan"), list) else (topic.get("alasan") or ""),
    ]
    return " ".join(str(p) for p in parts).lower()


def _score(text: str, words: tuple[str, ...]) -> int:
    if not text:
        return 0
    score = 0
    for w in words:
        if " " in w:
            if w in text:
                score += 2
        else:
            # batas kata kasar
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text):
                score += 1
    return score


def classify_topic(topic: dict | str | None) -> tuple[str, int, int, int]:
    """Kembalikan (gaya_pilihan, skor_info, skor_motivasi, skor_profil)."""
    text = _blob(topic)
    info = _score(text, _INFO_WORDS)
    motiv = _score(text, _MOTIV_WORDS)
    profil = _score(text, _PROFIL_WORDS)
    best = max(info, motiv, profil)
    if best == 0:
        return "", info, motiv, profil
    winners = []
    if info == best:
        winners.append(STYLE_PENJELAS)
    if motiv == best:
        winners.append(STYLE_CERITA)
    if profil == best:
        winners.append(STYLE_KOLASE)
    if len(winners) == 1:
        return winners[0], info, motiv, profil
    return "", info, motiv, profil  # seri / tidak jelas


def _history_styles(history: list[dict] | None) -> list[str]:
    out = []
    for item in history or []:
        if isinstance(item, dict):
            s = item.get("style")
        else:
            s = item
        if s in STYLES:
            out.append(s)
    return out


def _streak(styles: list[str]) -> tuple[str, int]:
    if not styles:
        return "", 0
    last = styles[-1]
    n = 0
    for s in reversed(styles):
        if s == last:
            n += 1
        else:
            break
    return last, n



def _next_style(last: str) -> str:
    if last in STYLES:
        return STYLES[(STYLES.index(last) + 1) % len(STYLES)]
    return STYLE_PENJELAS


def _least_recent(styles: list[str], *, exclude: str | None = None) -> str:
    """Gaya yang paling lama tidak muncul (atau belum pernah), selain exclude."""
    remaining = [s for s in STYLES if s != exclude]
    if not remaining:
        return _next_style(exclude or STYLE_PENJELAS)
    last_seen = {s: -1 for s in remaining}
    for i, s in enumerate(styles):
        if s in last_seen:
            last_seen[s] = i
    # yang belum pernah (-1) dulu, urutan STYLES stabil
    return min(remaining, key=lambda s: (last_seen[s], STYLES.index(s)))


def preferred_style(
    topic: dict | str | None,
    history: list[dict] | None = None,
    *,
    force: str | None = None,
) -> tuple[str, str, int]:
    """Pilih gaya untuk satu topik. Kembalikan (style, alasan, keyakinan 0–100)."""
    if force in STYLES:
        return force, "dipaksa", 100
    choice, info, motiv, profil = classify_topic(topic)
    hist = _history_styles(history)
    last, streak = _streak(hist)
    confidence = 0
    reason = "rotasi"
    if choice == STYLE_PENJELAS:
        confidence = min(100, 50 + info * 12 - max(motiv, profil) * 6)
        reason = "topik info"
    elif choice == STYLE_CERITA:
        confidence = min(100, 50 + motiv * 12 - max(info, profil) * 6)
        reason = "topik motivasi"
    elif choice == STYLE_KOLASE:
        confidence = min(100, 50 + profil * 12 - max(info, motiv) * 6)
        reason = "topik profil/sejarah"
    else:
        # tidak jelas: rotasi dari gaya terakhir, atau penjelas sebagai default pertama
        if last:
            choice = _next_style(last)
            reason = "rotasi (topik netral)"
            confidence = 30
        else:
            choice = STYLE_PENJELAS
            reason = "default (topik netral)"
            confidence = 20

    # Hindari 4+ beruntun gaya yang sama, kecuali keyakinan sangat tinggi.
    if last and choice == last and streak >= 3 and confidence < 85:
        other = _least_recent(hist, exclude=choice)
        return other, f"rotasi setelah {streak}× {last}", max(20, confidence - 25)
    return choice, reason, max(0, min(100, confidence))


def assign_styles(
    topics: list[dict | str],
    history: list[dict] | None = None,
    *,
    min_each: int | None = None,
) -> list[dict[str, Any]]:
    """Rencanakan gaya untuk satu batch (mis. 5 video/hari) agar ketiga gaya muncul.

    Kembalikan daftar dict: {style, reason, confidence}.
    Topik dengan sinyal kuat dipertahankan; yang keyakinannya rendah boleh dibalik
    agar batch tidak 5-0.
    """
    n = len(topics)
    if min_each is None:
        # Batch 5 video, 3 gaya: masing-masing minimal 1 (semua muncul).
        # Tidak bisa min_each=2 (butuh 6 slot).
        if n >= 5:
            min_each = 1
        elif n >= len(STYLES):
            min_each = 1
        elif n >= 2:
            min_each = 1 if len(STYLES) <= n else 0
        else:
            min_each = 0
    hist = list(history or [])
    planned: list[dict[str, Any]] = []
    running = list(hist)
    for topic in topics:
        style, reason, conf = preferred_style(topic, running)
        planned.append({
            "style": style,
            "reason": reason,
            "confidence": conf,
            "judul": (topic.get("judul") if isinstance(topic, dict) else str(topic or "")),
        })
        running.append({"style": style})

    def count(s: str) -> int:
        return sum(1 for p in planned if p["style"] == s)

    # Pastikan keragaman: balik yang keyakinannya paling rendah.
    for needed in STYLES:
        while count(needed) < min_each and n > count(needed):
            # kandidat: gaya lain, keyakinan terendah
            # jangan merampas gaya lain sampai di bawah min_each
            candidates = [
                (i, p) for i, p in enumerate(planned)
                if p["style"] != needed and count(p["style"]) > min_each
            ]
            if not candidates:
                break
            candidates.sort(key=lambda ip: (ip[1]["confidence"], ip[0]))
            i, p = candidates[0]
            # jangan balik jika sangat yakin (>80) dan kita sudah punya 0 — tetap balik 1
            # agar ada keragaman, kecuali n==1
            old = p["style"]
            p["style"] = needed
            p["reason"] = f"keragaman batch (dari {old}, yakin {p['confidence']})"
    return planned


def record_style(
    state: Any,
    *,
    date: str,
    slot: int,
    style: str,
    judul: str = "",
    reason: str = "",
) -> None:
    """Catat gaya yang dipakai. Pemanggil wajib memakai State sementara, bukan state produksi hari ini, untuk sampel uji."""
    if style not in STYLES or state is None:
        return
    hist = state.data.setdefault("style_history", [])
    hist.append({
        "date": date,
        "slot": slot,
        "style": style,
        "judul": judul,
        "reason": reason,
    })
    state.data["style_history"] = hist[-80:]
    state.save()


def history_from_state(state: Any) -> list[dict]:
    if state is None:
        return []
    data = getattr(state, "data", None) or {}
    hist = list(data.get("style_history") or [])
    # pelengkap dari video harian yang sudah ada gaya-nya
    days = data.get("days") or {}
    for date, day in days.items():
        for v in day.get("videos") or []:
            s = v.get("style")
            if s in STYLES:
                hist.append({
                    "date": date,
                    "slot": v.get("slot"),
                    "style": s,
                    "judul": v.get("judul") or "",
                    "reason": v.get("style_reason") or "",
                })
    return hist
