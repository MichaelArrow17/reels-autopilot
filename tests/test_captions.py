"""Uji chunk caption: monotik, tanpa tumpang tindih/duplikat, waktu tampil minimum."""

import pytest

from reels_autopilot.captions import (
    CaptionChunk,
    chunk_at_time,
    chunk_captions,
    current_word_index,
    validate_caption_chunks,
)
from reels_autopilot.config import HARD_MAX_DURATION, MAX_DURATION, TARGET_WORDS_MAX, TARGET_WORDS_MIN
from reels_autopilot.providers.tts import Word, estimate_words, normalize_word_timings
from reels_autopilot.qc import QCRejected, caption_issues, duration_issues, pre_publish_gate
from reels_autopilot.script_writer import fallback_script, trim_to_word_budget, _word_count


def _words(*pairs: tuple[str, float, float]) -> list[Word]:
    return [Word(word=w, start=s, duration=d) for w, s, d in pairs]


def test_current_word_index_does_not_jump_back_in_gaps():
    words = _words(
        ("Kamu", 0.0, 0.25),
        ("nggak", 0.40, 0.25),  # celah 0.25–0.40
        ("perlu", 0.80, 0.30),
    )
    # Di celah, tetap di kata terakhir yang sudah mulai — bukan kembali ke 0.
    assert current_word_index(words, 0.10) == 0
    assert current_word_index(words, 0.30) == 0
    assert current_word_index(words, 0.50) == 1
    assert current_word_index(words, 0.70) == 1
    assert current_word_index(words, 0.90) == 2
    times = [i * 0.05 for i in range(0, 30)]
    indices = [current_word_index(words, t) for t in times]
    assert indices == sorted(indices)


def test_chunk_captions_monotonic_no_overlap_no_duplicate():
    # 12 kata dengan jeda antar-batas kata (pola flicker versi lama)
    words = []
    t = 0.0
    tokens = "Kamu nggak perlu kamera untuk mulai unggah Reels satu naskah cukup".split()
    for tok in tokens:
        words.append(Word(word=tok, start=t, duration=0.28))
        t += 0.40  # celah 0.12s
    chunks = chunk_captions(words, min_duration=0.6, audio_duration=t + 1.0)
    errors = validate_caption_chunks(chunks, min_duration=0.6)
    assert errors == [], errors
    assert chunks, "harus ada chunk"
    for ch in chunks:
        assert 1 <= len(ch.words) <= 5
        assert ch.duration >= 0.6 - 1e-3
    # monotik & tanpa tumpang tindih
    for a, b in zip(chunks, chunks[1:]):
        assert a.start <= b.start
        assert a.end <= b.start + 1e-3
    # tidak mengulang kata
    flat = [(w.word, round(w.start, 4)) for ch in chunks for w in ch.words]
    assert len(flat) == len(set(flat))
    assert [w for w, _ in flat] == tokens


def test_chunk_at_time_never_revisits_previous_chunk():
    words = _words(
        ("Satu", 0.0, 0.3),
        ("dua", 0.35, 0.3),
        ("tiga", 1.2, 0.3),
        ("empat", 1.55, 0.3),
        ("lima", 2.4, 0.3),
        ("enam", 2.75, 0.3),
    )
    chunks = chunk_captions(words, min_duration=0.6, audio_duration=4.0)
    assert validate_caption_chunks(chunks) == []
    seen_starts = []
    last_idx = -1
    t = 0.0
    while t <= 4.0:
        ch = chunk_at_time(chunks, t)
        assert ch is not None
        idx = chunks.index(ch)
        assert idx >= last_idx, f"mundur dari chunk {last_idx} ke {idx} pada t={t:.2f}"
        last_idx = idx
        seen_starts.append(ch.start)
        t += 0.05
    # highlight tetap di dalam chunk aktif
    for ch in chunks:
        mid = (ch.start + ch.end) / 2
        hi = ch.highlight_index(mid)
        assert 0 <= hi < len(ch.words)


def test_validate_caption_chunks_catches_overlap_and_duplicates():
    bad_overlap = [
        CaptionChunk(words=_words(("A", 0.0, 0.5), ("B", 0.5, 0.5)), start=0.0, end=1.2),
        CaptionChunk(words=_words(("C", 1.0, 0.5), ("D", 1.5, 0.5)), start=1.0, end=2.0),
    ]
    err = validate_caption_chunks(bad_overlap)
    assert any("tumpang tindih" in e for e in err)

    bad_dup = [
        CaptionChunk(words=_words(("A", 0.0, 0.4), ("B", 0.4, 0.4)), start=0.0, end=1.0),
        CaptionChunk(words=_words(("A", 0.0, 0.4), ("C", 1.0, 0.4)), start=1.0, end=1.8),
    ]
    err = validate_caption_chunks(bad_dup)
    assert any("mengulang" in e or "sebelumnya" in e for e in err)

    too_short = [
        CaptionChunk(words=_words(("Halo", 0.0, 0.2)), start=0.0, end=0.2),
    ]
    err = validate_caption_chunks(too_short)
    assert any("minimum" in e for e in err)


def test_estimate_words_proportional_and_monotonic():
    text = "Satu dua tigaaa empat"
    # "tigaaa" lebih berat (lebih banyak huruf), harus dapat porsi waktu lebih panjang
    words = estimate_words(text, 4.0)
    assert [w.word for w in words] == text.split()
    for a, b in zip(words, words[1:]):
        assert a.start <= b.start
        assert a.end <= b.start + 1e-6
    assert words[-1].end <= 4.0 + 1e-6
    tiga = next(w for w in words if w.word == "tigaaa")
    dua = next(w for w in words if w.word == "dua")
    assert tiga.duration > dua.duration
    # dengan interval ucapan, kata hanya di dalam span
    spans = [(0.5, 2.0), (2.5, 4.0)]
    spoken = estimate_words(text, 4.0, speech_spans=spans)
    for w in spoken:
        in_span = any(a - 1e-6 <= w.start < b + 1e-6 for a, b in spans)
        assert in_span, w


def test_normalize_word_timings_removes_overlap():
    words = normalize_word_timings(
        _words(("A", 0.0, 1.0), ("B", 0.5, 1.0), ("C", 3.0, 2.0)),
        duration=4.0,
    )
    assert words[0].end <= words[1].start + 1e-6
    assert words[-1].end <= 4.0 + 1e-6


def test_duration_issues_hard_cap_is_error():
    err, warn = duration_issues(40.0)
    assert err == []
    err, warn = duration_issues(44.0)
    assert err == []
    assert any("ideal" in w for w in warn)
    err, warn = duration_issues(46.0)
    assert any("batas keras" in e and "45" in e for e in err)
    err, warn = duration_issues(HARD_MAX_DURATION)
    assert err == []
    err, warn = duration_issues(20.0)
    assert err == []
    assert warn


def test_caption_issues_and_pre_publish_gate(tmp_path):
    good = chunk_captions(
        _words(("Satu", 0.0, 0.4), ("dua", 0.4, 0.4), ("tiga", 0.9, 0.4), ("empat", 1.3, 0.4)),
        min_duration=0.6,
        audio_duration=3.0,
    )
    assert caption_issues(chunks=good) == []

    bad = [CaptionChunk(words=_words(("A", 0.0, 0.5), ("B", 0.5, 0.5)), start=0.0, end=0.3)]
    assert caption_issues(chunks=bad)

    missing = tmp_path / "tidak_ada.mp4"
    with pytest.raises(QCRejected) as ex:
        pre_publish_gate(missing)
    assert "tidak ada" in str(ex.value).lower() or ex.value.result.errors


def test_fallback_script_word_budget_and_trim():
    s = fallback_script({
        "judul": "Kenapa hook dua detik menentukan Reels",
        "hook": "Dua detik pertama memutuskan kamu ditonton atau dilewati.",
    })
    n = _word_count(s["narasi_penuh"])
    assert TARGET_WORDS_MIN <= n <= TARGET_WORDS_MAX, n
    assert s["durasi_target_detik"] == 35
    long = ("Kata " * 160) + "Selesai."
    trimmed = trim_to_word_budget(long, TARGET_WORDS_MAX)
    assert _word_count(trimmed) <= TARGET_WORDS_MAX
    assert _word_count(trimmed) >= 70
