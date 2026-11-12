"""Chunk caption karaoke: 2–4 kata, timing dari batas kata TTS, monotik tanpa flicker."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reels_autopilot.config import (
    CAPTION_MAX_WORDS,
    CAPTION_MIN_WORDS,
    MIN_CAPTION_SECONDS,
)
from reels_autopilot.providers.tts import Word, normalize_word_timings

_PUNCT_END = re.compile(r"[.!?…]+$")
_EPS = 1e-3


@dataclass
class CaptionChunk:
    words: list[Word]
    start: float
    end: float

    @property
    def text(self) -> str:
        return " ".join(w.word for w in self.words if w.word)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def highlight_index(self, t: float) -> int:
        """Indeks kata yang sedang diucapkan di dalam chunk; tidak pernah mundur ke luar chunk."""
        if not self.words:
            return -1
        idx = 0
        for i, w in enumerate(self.words):
            if w.start <= t:
                idx = i
            else:
                break
        return idx


def current_word_index(words: list[Word], t: float) -> int:
    """Indeks kata terakhir yang sudah mulai. Celah antar kata TIDAK boleh kembali ke 0."""
    if not words:
        return -1
    idx = 0
    for i, w in enumerate(words):
        if w.start <= t:
            idx = i
        else:
            break
    return idx


def chunk_at_time(chunks: list[CaptionChunk], t: float) -> CaptionChunk | None:
    """Chunk yang sudah mulai di waktu t. Jeda antar chunk menahan teks sebelumnya, tidak boleh mundur/kosong."""
    if not chunks:
        return None
    found: CaptionChunk | None = None
    for ch in chunks:
        if ch.start <= t:
            found = ch
        else:
            break
    return found


def _ends_sentence(word: str) -> bool:
    return bool(_PUNCT_END.search((word or "").strip()))


def chunk_captions(
    words: list[Word],
    *,
    min_duration: float = MIN_CAPTION_SECONDS,
    min_words: int = CAPTION_MIN_WORDS,
    max_words: int = CAPTION_MAX_WORDS,
    audio_duration: float | None = None,
) -> list[CaptionChunk]:
    """Gabungkan kata menjadi chunk stabil 2–4 kata (atau satu baris pendek).

    Aturan:
    - setiap chunk tampil minimal ``min_duration`` detik (default 0,6)
    - monotik: start dan end tidak mundur, tanpa tumpang tindih
    - tidak mengulang atau mengunjungi kembali kata sebelumnya
    """
    words = normalize_word_timings(words, audio_duration)
    if not words:
        return []

    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        if len(cur) >= max_words or (_ends_sentence(w.word) and len(cur) >= min_words):
            groups.append(cur)
            cur = []
    if cur:
        if groups and len(cur) < min_words and len(groups[-1]) + len(cur) <= max_words:
            groups[-1].extend(cur)
        else:
            groups.append(cur)

    chunks = [
        CaptionChunk(words=list(g), start=float(g[0].start), end=float(max(g[-1].end, g[0].start)))
        for g in groups
        if g
    ]
    if not chunks:
        return []

    # Perpanjang sampai min_duration, tanpa melewati awal chunk berikutnya.
    horizon = audio_duration if audio_duration and audio_duration > 0 else None
    for i, ch in enumerate(chunks):
        nxt = chunks[i + 1].start if i + 1 < len(chunks) else (horizon if horizon is not None else ch.end)
        target = ch.start + min_duration
        if nxt > ch.start:
            ch.end = max(ch.end, min(target, nxt))
        else:
            ch.end = max(ch.end, target)
        if i + 1 < len(chunks) and ch.end > chunks[i + 1].start:
            ch.end = chunks[i + 1].start
        if horizon is not None and i == len(chunks) - 1:
            ch.end = min(max(ch.end, min(target, horizon) if horizon > ch.start else target), max(horizon, target))
            # tahan chunk terakhir tetap ≥ min_duration meski audio tinggal sedikit
            if ch.duration + _EPS < min_duration:
                ch.end = ch.start + min_duration

    # Gabungkan chunk yang masih terlalu singkat.
    merged: list[CaptionChunk] = []
    for ch in chunks:
        if merged and ch.duration + _EPS < min_duration:
            prev = merged[-1]
            prev.words = prev.words + ch.words
            prev.end = max(prev.end, ch.end, prev.start + min_duration)
        else:
            merged.append(ch)

    # Rapikan monotik + tanpa tumpang tindih.
    for i in range(len(merged) - 1):
        if merged[i].end > merged[i + 1].start + _EPS:
            merged[i].end = merged[i + 1].start
        if merged[i + 1].start < merged[i].end:
            merged[i + 1].start = merged[i].end
        if merged[i + 1].end <= merged[i + 1].start:
            merged[i + 1].end = merged[i + 1].start + min_duration
            if i + 2 < len(merged) and merged[i + 1].end > merged[i + 2].start:
                merged[i + 1].end = merged[i + 2].start

    # Tutup celah: tahan chunk sebelumnya sampai chunk berikut mulai (cegah teks hilang/flicker).
    if merged and merged[0].start <= 0.35:
        merged[0].start = 0.0
    for i in range(len(merged) - 1):
        if merged[i].end < merged[i + 1].start:
            merged[i].end = merged[i + 1].start

    return [ch for ch in merged if ch.words and ch.end > ch.start]


def validate_caption_chunks(
    chunks: list[CaptionChunk],
    *,
    min_duration: float = MIN_CAPTION_SECONDS,
    allow_empty: bool = False,
) -> list[str]:
    """Kembalikan daftar error (kosong = lolos). Monotik, tanpa tumpang tindih/duplikat."""
    errors: list[str] = []
    if not chunks:
        if not allow_empty:
            errors.append("caption kosong: tidak ada chunk timing")
        return errors

    seen_keys: set[tuple[str, float]] = set()
    last_word_start = -1.0
    prev: CaptionChunk | None = None
    for i, ch in enumerate(chunks):
        if not ch.words or not ch.text.strip():
            errors.append(f"chunk {i} kosong")
            continue
        if ch.end <= ch.start + _EPS / 10:
            errors.append(f"chunk {i} durasi tidak valid ({ch.start:.3f}–{ch.end:.3f})")
        if ch.duration + _EPS < min_duration:
            errors.append(
                f"chunk {i} tampil {ch.duration:.2f}s, minimum {min_duration:.2f}s ({ch.text!r})"
            )
        if prev is not None:
            if ch.start + _EPS < prev.start:
                errors.append(
                    f"chunk {i} mundur (start {ch.start:.3f} < {prev.start:.3f})"
                )
            if ch.start + _EPS < prev.end:
                errors.append(
                    f"chunk {i} tumpang tindih dengan chunk {i - 1} "
                    f"({prev.end:.3f} > {ch.start:.3f})"
                )
        for w in ch.words:
            key = (w.word, round(w.start, 4))
            if key in seen_keys:
                errors.append(
                    f"chunk {i} mengulang kata {w.word!r} @ {w.start:.3f}s"
                )
            seen_keys.add(key)
            if w.start + _EPS < last_word_start:
                errors.append(
                    f"chunk {i} mengunjungi kata sebelumnya ({w.word!r} @ {w.start:.3f}s)"
                )
            last_word_start = max(last_word_start, w.start)
        prev = ch
    return errors
