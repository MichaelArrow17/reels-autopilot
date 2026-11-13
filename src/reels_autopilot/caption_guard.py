"""Jaga caption publik agar tidak membocorkan instruksi gaya/rubrik internal."""

from __future__ import annotations

# Frasa instruksi internal — jangan pernah tampil di caption IG/FB/Telegram.
# Bandingkan case-insensitive. Jangan pakai kata terlalu umum (mis. "ngarang" saja)
# supaya caption sah tentang halusinasi AI tidak tertolak.
INTERNAL_CAPTION_PHRASES: tuple[str, ...] = (
    "explainer singkat",
    "satu gagasan per adegan",
    "satu gagasan, satu adegan",
    "tanpa angka yang dikarang",
    "tanpa angka karangan",
    "tidak ada angka yang dikarang",
    "klaim hanya yang bisa dicek",
    "setiap klaim dicek",
    "naskah ditulis untuk telinga",
    "hook selesai dalam dua detik",
    "tulis untuk telinga",
    "satu ide per kalimat",
    "bahasa natural dokumenter",
    "output hanya json",
    "pose stickman",
    'dilarang: "di video ini"',
    "jangan mengarang angka",
    "jangan menambah angka",
    "playbook 9.4",
    "playbook 13.2",
    "gerbang safety",
    "untuk telinga: satu ide",
    "setiap angka di layar harus diucapkan",
)


def public_caption_issues(text: str | None) -> list[str]:
    """Kembalikan daftar pelanggaran jika caption memuat instruksi internal."""
    low = (text or "").lower()
    if not low.strip():
        return []
    hits: list[str] = []
    seen: set[str] = set()
    for phrase in INTERNAL_CAPTION_PHRASES:
        key = phrase.lower()
        if key in low and key not in seen:
            seen.add(key)
            hits.append(f"caption memuat instruksi internal: {phrase}")
    return hits


def caption_is_clean(text: str | None) -> bool:
    return not public_caption_issues(text)
