"""Gaya kolase scrapbook, penjaga fakta, dan pemilih 3 gaya."""

from __future__ import annotations

from pathlib import Path

from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.fact_guard import facts_ok, validate_kolase_facts
from reels_autopilot.style_kolase import (
    append_credit,
    credit_line,
    derive_kolase,
    fallback_kolase,
    kolase_caption,
    make_illustration,
    render_kolase_frame,
    sample_kartini_script,
)
from reels_autopilot.styles import (
    STYLE_CERITA,
    STYLE_KOLASE,
    STYLE_PENJELAS,
    STYLES,
    classify_topic,
    preferred_style,
)
from reels_autopilot.telegram_bot import uji_sample_html


def test_old_style_is_not_selectable():
    assert STYLES == (STYLE_PENJELAS, STYLE_CERITA, STYLE_KOLASE)
    assert "lama" not in STYLES
    assert "original" not in STYLES
    assert "legacy" not in STYLES
    style, _, _ = preferred_style({"judul": "apa saja"}, force="lama")
    # force invalid diabaikan, tidak mengembalikan gaya lama
    assert style in STYLES


def test_classify_profil_to_kolase():
    s, info, motiv, profil = classify_topic({
        "judul": "Biografi singkat kisah hidup tokoh sejarah ini",
        "hook": "Riwayat hidup pendiri dan penemunya",
    })
    assert s == STYLE_KOLASE
    assert profil > info and profil > motiv


def test_fact_guard_requires_source_for_year_and_death():
    bad = {
        "style": "kolase",
        "subjek": "Seseorang",
        "narasi_penuh": "Ia lahir tahun 1879 dan wafat dalam skandal.",
        "klaim": [],
    }
    issues = validate_kolase_facts(bad)
    assert any("tanpa daftar sumber" in i for i in issues)
    still_bad = {
        **bad,
        "klaim": [{"teks": "lahir tahun 1879", "sumber_url": "https://bit.ly/abc", "sumber_nama": "x"}],
    }
    issues2 = validate_kolase_facts(still_bad)
    assert any("sah" in i or "terpercaya" in i or "wafat" in i or "skandal" in i for i in issues2)


def test_fact_guard_accepts_sourced_kartini():
    s = sample_kartini_script()
    assert facts_ok(s)
    assert public_caption_issues(s["caption"]) == []
    assert "1879" in s["narasi_penuh"]
    assert any("britannica.com" in (c.get("sumber_url") or "") for c in s["klaim"])


def test_fact_guard_blocks_invented_numbers():
    s = sample_kartini_script()
    s = dict(s)
    s["narasi_penuh"] = s["narasi_penuh"] + " Ia punya 999 sekolah."
    issues = validate_kolase_facts(s)
    assert any("999" in i for i in issues)


def test_educational_fallback_has_no_unsourced_person_facts():
    s = fallback_kolase({"judul": "Topik acak tanpa sumber"}, educational=True)
    assert s["style"] == STYLE_KOLASE
    assert facts_ok(s)
    assert public_caption_issues(s["caption"]) == []
    assert not s.get("subjek")
    cap = kolase_caption(s)
    assert "import " not in cap.lower()


def test_credit_line_appended_once():
    assets = [
        {"attribution": "Foo / Wikimedia Commons (Public Domain)", "provider": "wikimedia"},
        {"attribution": "Foo / Wikimedia Commons (Public Domain)", "provider": "wikimedia"},
    ]
    line = credit_line(assets)
    cap = append_credit("Hook.\n#PoChai", line)
    cap2 = append_credit(cap, line)
    assert cap.count("Wikimedia Commons") == 1
    assert cap2 == cap
    assert public_caption_issues(cap) == []


def test_kolase_frame_and_illustration():
    from reels_autopilot.providers.tts import Word
    from reels_autopilot.captions import chunk_captions
    from reels_autopilot.drawutil import load_font
    from reels_autopilot.config import Settings
    from reels_autopilot.style_kolase import _windows_from_script

    ill = make_illustration("Kartini", size=(400, 520), seed=1)
    assert ill.mode == "RGBA" and ill.size[0] > 100
    script = derive_kolase(fallback_kolase({"judul": "Cek sumber dulu"}, educational=True))
    # tempel ilustrasi sebagai aset agar frame tidak butuh jaringan
    for b in script["bab"]:
        b["asset"] = {"cutout": "", "path": ""}
    narasi = script["narasi_penuh"]
    words = []
    t = 0.0
    for w in narasi.split():
        words.append(Word(w, t, 0.3))
        t += 0.32
    duration = t + 0.4
    chunks = chunk_captions(words, audio_duration=duration)
    windows = _windows_from_script(script, words, duration)
    assert len(windows) == 4
    s = Settings()
    fonts = {
        "brand": load_font(24, 600, s),
        "chapter": load_font(26, 700, s),
        "label": load_font(48, 650, s),
        "caption": load_font(40, 550, s),
    }
    frame = render_kolase_frame(script, 0.5, duration, words, chunks, windows, fonts)
    assert frame.size == (1080, 1920)
    # transisi dorong di awal bab 2
    t_push = windows[1][0] + 0.1
    frame2 = render_kolase_frame(script, t_push, duration, words, chunks, windows, fonts)
    assert frame2.size == (1080, 1920)


def test_somber_piano_and_writer_fallback(tmp_path, monkeypatch):
    from reels_autopilot.sfx import somber_piano, write_wav
    from reels_autopilot.config import Settings
    from reels_autopilot.script_writer import ScriptWriter

    samples = somber_piano(2.0)
    assert len(samples) > 1000
    path = write_wav(tmp_path / "piano.wav", samples)
    assert path.exists() and path.stat().st_size > 100

    settings = Settings()
    settings.root = tmp_path
    w = ScriptWriter(settings)
    monkeypatch.setattr(w.llm, "generate_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    script = w.write({"judul": "Biografi tokoh tanpa sumber"}, style=STYLE_KOLASE)
    assert script["style"] == STYLE_KOLASE
    assert script.get("storyboard_fallback") is True
    assert facts_ok(script)
    assert public_caption_issues(script["caption"]) == []


def test_writer_rejects_unsourced_llm_bio(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.script_writer import ScriptWriter

    settings = Settings()
    settings.root = tmp_path
    w = ScriptWriter(settings)

    def fake_json(*a, **k):
        return {
            "judul": "Tokoh X",
            "hook": "Dia lahir tahun 1901 lalu mundur dari jabatan.",
            "narasi_penuh": "Dia lahir tahun 1901 lalu mundur dari jabatan dalam skandal besar tanpa sumber.",
            "subjek": "Tokoh X",
            "caption": "Lahir 1901.\n#PoChai",
            "klaim": [],
            "bab": [
                {"nama": "hook", "label": "1901", "gambar_query": "", "kata_kunci": []},
                {"nama": "timeline", "label": "MUNDUR", "gambar_query": "", "kata_kunci": []},
                {"nama": "twist", "label": "SKANDAL", "gambar_query": "", "kata_kunci": []},
                {"nama": "tanya", "label": "TULIS DI KOMENTAR", "gambar_query": "", "kata_kunci": []},
            ],
        }, "gemini"

    monkeypatch.setattr(w.llm, "generate_json", fake_json)
    script = w.write({"judul": "Profil Tokoh X", "subjek": "Tokoh X"}, style=STYLE_KOLASE)
    assert script["style"] == STYLE_KOLASE
    assert script.get("storyboard_fallback") is True
    assert "1901" not in (script.get("narasi_penuh") or "")
    assert facts_ok(script)


def test_uji_message_marks_kolase_as_sample():
    html = uji_sample_html(
        "kolase scrapbook (foto lisensi bebas + mesin tik + piano)",
        public_caption="Contoh caption.\n#PoChai",
        notes="Durasi 34 dtk.",
    )
    low = html.lower()
    assert "sampel uji" in low
    assert "bukan untuk diposting" in low
    assert "tidak perlu acc" in low
    assert "balas ok" not in low
    assert public_caption_issues(html) == []


def test_commons_search_is_wikimedia_only():
    import inspect
    from reels_autopilot.providers.images import ImageClient

    src = inspect.getsource(ImageClient.search_commons)
    assert "self._wikimedia" in src
    assert "self._pexels" not in src
    assert "self._pixabay" not in src
    assert "self._unsplash" not in src
    assert "self._openverse" not in src
    assert "self._local" not in src
