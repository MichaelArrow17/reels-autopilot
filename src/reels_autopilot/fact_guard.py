"""Penjaga fakta ketat untuk konten orang nyata / perusahaan (gaya kolase).

Setiap klaim faktual harus punya URL sumber resmi/terpercaya di metadata.
Klaim berat (skandal, mundur jabatan, kematian) diblokir jika tidak bersumber.
Angka karangan dilarang (memakai number_allowed yang sudah ada).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from reels_autopilot.storyboard import extract_narration_numbers, number_allowed

# Klaim berat: jangan tampil tanpa sumber.
HEAVY_PATTERNS = (
    r"\b(meninggal|wafat|tewas|kematian|dibunuh|bunuh diri)\b",
    r"\b(died|death|suicide|killed|murdered)\b",
    r"\b(mundur|mengundurkan|dipecat|diberhentikan|resign(?:ed|ation)?|fired|ousted)\b",
    r"\b(skandal|skandalnya|scandal|selingkuh|perselingkuhan|affair)\b",
    r"\b(ditangkap|ditahan|divonis|terpidana|korupsi|arrested|convicted|embezzl)\b",
    r"\b(diperkosa|pelecehan|assaulted|pedofil)\b",
)

_HEAVY_RE = [re.compile(p, re.I) for p in HEAVY_PATTERNS]

# Shortener / sumber yang tidak dianggap layak.
_BAD_HOST_PARTS = (
    "bit.ly", "tinyurl", "t.co", "goo.gl", "ow.ly", "rb.gy",
    "cutt.ly", "shorturl", "is.gd",
)

# Host yang kita anggap resmi atau cukup terpercaya (bukan daftar tertutup).
_REPUTABLE_HINTS = (
    ".gov", ".go.id", ".mil", ".edu",
    "britannica.com", "wikipedia.org", "wikimedia.org", "wikidata.org",
    "reuters.com", "bbc.", "nytimes.com", "theguardian.com",
    "apnews.com", "afp.com", "kompas.com", "antaranews.com",
    "kemdikbud.go.id", "indonesia.go.id", "nobelprize.org",
    "cern.ch", "w3.org", "nasa.gov", "who.int", "un.org",
    "nature.com", "science.org", "jstor.org",
)


def _is_http_url(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
    except Exception:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc) and "." in p.netloc


def source_url_ok(url: str) -> bool:
    """URL sumber harus http(s) dan bukan shortener."""
    if not _is_http_url(url):
        return False
    host = (urlparse(url).netloc or "").lower()
    if any(b in host for b in _BAD_HOST_PARTS):
        return False
    return True


def source_is_reputable(url: str) -> bool:
    if not source_url_ok(url):
        return False
    host = (urlparse(url).netloc or "").lower()
    path = (urlparse(url).path or "").lower()
    blob = host + path
    return any(h in blob for h in _REPUTABLE_HINTS)


def heavy_spans(text: str) -> list[str]:
    hits: list[str] = []
    for rx in _HEAVY_RE:
        for m in rx.finditer(text or ""):
            hits.append(m.group(0).lower())
    return hits


def _normalize_claims(raw) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        teks = (item.get("teks") or item.get("klaim") or item.get("text") or "").strip()
        url = (item.get("sumber_url") or item.get("url") or item.get("source_url") or "").strip()
        nama = (item.get("sumber_nama") or item.get("sumber") or item.get("source") or "").strip()
        out.append({"teks": teks, "sumber_url": url, "sumber_nama": nama})
    return out


def _claim_covers(fragment: str, claims: list[dict]) -> bool:
    frag = (fragment or "").strip().lower()
    if not frag:
        return False
    for c in claims:
        if not source_url_ok(c.get("sumber_url") or ""):
            continue
        teks = (c.get("teks") or "").lower()
        if frag in teks or teks in frag:
            return True
        # token overlap kasar (minimal 1 token bermakna)
        tokens = [t for t in re.findall(r"[a-z0-9]+", frag) if len(t) >= 4]
        if tokens and all(t in teks for t in tokens[:2]):
            return True
    return False


def validate_kolase_facts(script: dict | None, *, require_claims: bool = True) -> list[str]:
    """Kembalikan daftar pelanggaran. Kosong = lolos."""
    script = script or {}
    issues: list[str] = []
    narasi = " ".join(
        [
            script.get("narasi_penuh") or "",
            script.get("hook") or "",
            script.get("judul") or "",
            script.get("caption") or "",
        ]
    )
    claims = _normalize_claims(script.get("klaim") or script.get("fakta_bersumber") or [])
    # setiap entri klaim harus lengkap
    for i, c in enumerate(claims, 1):
        if not (c.get("teks") or "").strip():
            issues.append(f"klaim #{i} tanpa teks")
            continue
        url = c.get("sumber_url") or ""
        if not source_url_ok(url):
            issues.append(f"klaim #{i} tanpa URL sumber yang sah")
        elif not source_is_reputable(url):
            issues.append(f"klaim #{i} sumber belum terpercaya/resmi: host tidak dikenali")

    personish = bool(script.get("subjek") or script.get("tokoh"))
    # Angka tahun / subjek orang-nyata wajib punya daftar klaim bersumber.
    years = [n for n in extract_narration_numbers(narasi) if n >= 100]
    needs_sources = bool(personish or years)
    if require_claims and needs_sources and not claims:
        issues.append("ada klaim faktual tanpa daftar sumber (klaim[])")

    # Klaim berat hanya ditegakkan jika naskah tentang orang/perusahaan/tahun,
    # bukan peringatan umum ("jangan sebar skandal tanpa sumber").
    if needs_sources:
        for hit in heavy_spans(narasi):
            if not _claim_covers(hit, claims):
                issues.append(f"klaim berat '{hit}' tanpa sumber")

    # angka di narasi harus muncul di salah satu klaim bersumber (kecuali 0–10 wacana)
    allowed_from_claims: set[float] = set()
    for c in claims:
        if source_url_ok(c.get("sumber_url") or ""):
            allowed_from_claims |= extract_narration_numbers(c.get("teks") or "")
    spoken = extract_narration_numbers(narasi)
    for n in spoken:
        if n <= 10:
            continue
        if not number_allowed(n, allowed_from_claims):
            issues.append(f"angka {n:g} di narasi tidak ada di klaim bersumber")

    # simpan salinan bersih jika pemanggil ingin
    script["klaim"] = claims
    return issues


def facts_ok(script: dict | None, **kwargs) -> bool:
    return not validate_kolase_facts(script, **kwargs)
