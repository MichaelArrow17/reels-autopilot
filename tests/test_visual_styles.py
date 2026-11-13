"""Gaya visual baru, storyboard, affiliate, pemilih gaya, sampel uji."""

from __future__ import annotations

import json
from pathlib import Path

from reels_autopilot.affiliate import (
    AffiliateConfig,
    AffiliateProduct,
    apply_affiliate_cta,
    load_affiliate,
    match_product,
    _parse_simple_yaml,
)
from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.script_writer import fallback_script, _word_count
from reels_autopilot.storyboard import (
    derive_penjelas_visual,
    extract_narration_numbers,
    fallback_cerita,
    number_allowed,
    validate_cerita,
    cerita_caption,
    ENVIRONMENTS,
    ACTIONS,
)
from reels_autopilot.styles import (
    STYLE_CERITA,
    STYLE_PENJELAS,
    assign_styles,
    classify_topic,
    preferred_style,
    record_style,
)
from reels_autopilot.telegram_bot import uji_sample_html


def test_classify_info_vs_motivasi():
    s, info, motiv = classify_topic({"judul": "Cara pakai ChatGPT tanpa ngarang", "hook": "Tips AI"})
    assert s == STYLE_PENJELAS and info > motiv
    s, info, motiv = classify_topic({"judul": "Jangan menyerah saat sudah hampir sampai"})
    assert s == STYLE_CERITA and motiv > info


def test_assign_styles_ensures_variety_in_batch_of_five():
    topics = [
        {"judul": "Tips pakai AI di HP"},
        {"judul": "Investasi saham pemula"},
        {"judul": "Cara jaga data pribadi"},
        {"judul": "Fitur baru ChatGPT"},
        {"judul": "Algoritma Reels Instagram"},
    ]
    plan = assign_styles(topics, history=[])
    styles = [p["style"] for p in plan]
    assert STYLE_PENJELAS in styles and STYLE_CERITA in styles
    assert styles.count(STYLE_CERITA) >= 2
    assert styles.count(STYLE_PENJELAS) >= 2


def test_preferred_style_breaks_streak():
    hist = [{"style": STYLE_PENJELAS}] * 4
    style, reason, conf = preferred_style({"judul": "Topik netral tanpa kata khusus"}, hist)
    assert style == STYLE_CERITA
    assert "rotasi" in reason


def test_record_style_uses_given_state_only(tmp_path):
    from reels_autopilot.config import Settings
    from reels_autopilot.state import State

    settings = Settings()
    settings.root = tmp_path
    st = State(settings)
    st.path = tmp_path / "state.json"
    st.data = {"past_topics": [], "days": {}, "telegram": {}, "paused": False}
    record_style(st, date="2026-11-14", slot=1, style=STYLE_PENJELAS, judul="Tes", reason="uji")
    assert st.data["style_history"][-1]["style"] == STYLE_PENJELAS
    # state produksi tidak boleh tersentuh
    prod = Path("/workspace/reels_autopilot/data/state.json")
    if prod.exists():
        # kita tidak menulis ke situ; cek path yang dipakai adalah tmp
        assert st.path == tmp_path / "state.json"


def test_validate_rejects_code_and_falls_back():
    sb, fb, err = validate_cerita(
        {"kode": "import pygame\nimport moviepy", "environment": "underwater"},
        {"judul": "Jangan menyerah"},
    )
    assert fb is True
    assert sb["environment"] in ENVIRONMENTS
    assert len(sb["beats"]) >= 5
    assert any("kode" in e for e in err)


def test_validate_normalizes_unknown_action_and_fixes_times():
    raw = fallback_cerita({"judul": "Tes motivasi"})
    raw["beats"][0]["aksi_a"] = "fly_spaceship"
    raw["beats"][1]["t"] = raw["beats"][0]["t"] - 5
    sb, fb, err = validate_cerita(raw)
    assert fb is False
    assert sb["beats"][0]["aksi_a"]["nama"] in ACTIONS
    assert sb["beats"][0]["aksi_a"]["nama"] == "idle"
    times = [b["t"] for b in sb["beats"]]
    assert times == sorted(times)
    assert 20 <= sb["durasi_detik"] <= 30


def test_all_environment_templates_validate():
    for env in ENVIRONMENTS:
        sb0 = fallback_cerita({"judul": "Tes " + env, "hook": "Yang berusaha sampai di ujung."}, env)
        sb, fb, err = validate_cerita(sb0)
        assert fb is False, (env, err)
        assert sb["environment"] == env
        assert any(b.get("klimaks") for b in sb["beats"])
        cap = cerita_caption(sb)
        assert public_caption_issues(cap) == []
        assert "import " not in cap.lower()
        assert "pose stickman" not in cap.lower()


def test_no_invented_numbers_in_visual():
    allowed = extract_narration_numbers("Ada tiga langkah. Pertama dan kedua.")
    assert number_allowed(3, allowed)
    assert number_allowed(1, allowed)
    assert not number_allowed(99, allowed)
    s = derive_penjelas_visual({
        "narasi_penuh": "Tanpa bilangan apa pun di sini.",
        "adegan": [{}],
        "visual": {"bab": [{"counter": {"ke": 99, "label": "x"}}]},
    })
    assert s["visual"]["bab"][0]["counter"] is None
    s2 = derive_penjelas_visual({
        "narasi_penuh": "Ada tiga langkah sederhana.",
        "adegan": [{}],
        "visual": {"bab": [{"layout": "steps", "counter": {"ke": 3, "label": "langkah"}}]},
    })
    assert s2["visual"]["bab"][0]["counter"]["ke"] == 3.0


def test_affiliate_empty_does_nothing(tmp_path):
    cfg = load_affiliate(Path("/workspace/reels_autopilot/config/affiliate.yaml"))
    assert cfg.enabled is False
    assert cfg.products == []
    text = "Hook panjang untuk caption.\nSimpan video ini.\n#PoChai"
    assert apply_affiliate_cta(text, {"judul": "AI"}, config=cfg) == text


def test_affiliate_inserts_cta_without_url():
    cfg = AffiliateConfig(
        enabled=True,
        cta_default="Cek link di bio.",
        insert_url=False,
        products=[AffiliateProduct(id="x", keywords=["chatgpt"], cta="Cek link di bio kalau mau cobain.", url="https://example.com/rahasia")],
    )
    text = "ChatGPT kadang ngarang.\nSimpan video ini.\n#PoChai"
    out = apply_affiliate_cta(text, {"judul": "Cara pakai ChatGPT"}, config=cfg)
    assert "Cek link di bio kalau mau cobain." in out
    assert "example.com" not in out
    assert "https://" not in out
    assert public_caption_issues(out) == []
    # tidak dobel
    out2 = apply_affiliate_cta(out, {"judul": "Cara pakai ChatGPT"}, config=cfg)
    assert out2.count("Cek link di bio") == 1


def test_affiliate_yaml_parser():
    raw = """
enabled: true
insert_url: false
cta_default: "Cek link di bio."
products:
  - id: contoh
    keywords: [ai, tips]
    cta: "Cek link di bio."
    url: ""
"""
    data = _parse_simple_yaml(raw)
    assert data["enabled"] is True
    assert data["products"][0]["id"] == "contoh"
    assert "ai" in data["products"][0]["keywords"]


def test_uji_message_is_not_an_acc_preview():
    html = uji_sample_html(
        "penjelas (motion graphics)",
        public_caption="Caption contoh.\n#PoChai",
        notes="Durasi 34 dtk.",
    )
    low = html.lower()
    assert "sampel uji" in low
    assert "bukan untuk diposting" in low
    assert "tidak perlu acc" in low
    # jangan kasih perintah ACC yang menyesatkan
    assert "balas ok" not in low
    assert "balas acc" not in low
    assert "supaya boleh tayang" not in low
    assert "caption contoh" in low
    assert public_caption_issues(html) == []


def test_fallback_script_still_valid_after_visual_enrich():
    s = fallback_script({
        "judul": "Kenapa hook dua detik menentukan Reels",
        "hook": "Dua detik pertama memutuskan kamu ditonton atau dilewati.",
    })
    s2 = derive_penjelas_visual(s)
    n = _word_count(s2["narasi_penuh"])
    from reels_autopilot.config import TARGET_WORDS_MAX, TARGET_WORDS_MIN
    assert TARGET_WORDS_MIN <= n <= TARGET_WORDS_MAX
    assert len(s2["adegan"]) == 5
    assert s2["visual"]["bab"]
    assert public_caption_issues(s2["caption"]) == []


def test_stick_sprites_and_environments_render():
    from reels_autopilot.style_cerita import stick_sprite, _env_static, render_cerita_frame
    from reels_autopilot.drawutil import load_font
    from reels_autopilot.config import Settings

    for action in ("idle", "walk", "climb", "swim", "sink", "fall", "push", "celebrate", "sit", "reach", "limp"):
        im = stick_sprite(action, 3, "kuning", "kanan", 100)
        assert im.size[0] > 100 and im.mode == "RGBA"
    for env in ENVIRONMENTS:
        bg = _env_static(env)
        assert bg.size == (1080, 1920)
    s = Settings()
    fonts = {
        "label": load_font(42, 800, s),
        "bubble": load_font(34, 700, s),
        "tiny": load_font(20, 400, s),
        "clim": load_font(52, 800, s),
    }
    sb = fallback_cerita({"judul": "Tes"}, "underwater")
    frame = render_cerita_frame(sb, 2.0, fonts)
    assert frame.size == (1080, 1920)
    # klimaks
    frame2 = render_cerita_frame(sb, 20.0, fonts)
    assert frame2.size == (1080, 1920)


def test_penjelas_frame_and_text_fits():
    from reels_autopilot.providers.tts import Word
    from reels_autopilot.captions import chunk_captions
    from reels_autopilot.style_penjelas import PALETTES, render_penjelas_frame, _windows_from_script
    from reels_autopilot.drawutil import load_font, fit_text, SAFE_WIDTH, SAFE_LEFT, SAFE_RIGHT
    from reels_autopilot.config import Settings

    long = "Ini judul yang sangat panjang sekali supaya font mengecil dan tidak keluar dari layar vertikal Reels Indonesia."
    lines, font, size = fit_text(long, max_width=SAFE_WIDTH, max_height=300, max_size=110, min_size=28, weight=800, max_lines=3)
    assert size < 110
    assert all(font.getlength(ln) <= SAFE_WIDTH + 1 for ln in lines)

    narasi = SCRIPT_WORDS = (
        "ChatGPT kadang terdengar yakin, padahal jawabannya ngarang. "
        "Tiga langkah sederhana. Simpan video ini."
    )
    words = []
    t = 0.0
    for w in narasi.split():
        words.append(Word(w, t, 0.3))
        t += 0.35
    duration = t + 0.4
    chunks = chunk_captions(words, audio_duration=duration)
    script = derive_penjelas_visual({
        "hook": "ChatGPT kadang terdengar yakin, padahal jawabannya ngarang.",
        "narasi_penuh": narasi,
        "adegan": [
            {"nama": "hook", "teks_layar": "TERDENGAR YAKIN", "narasi": narasi},
        ],
        "visual": {"mode": "light", "bab": [{"layout": "kinetic_title", "judul_layar": "TERDENGAR YAKIN",
                   "kata_kunci": [{"kata": "YAKIN", "warna": "emas"}, {"kata": "NGARANG", "warna": "merah"}]}]},
    })
    s = Settings()
    memo = {}
    def cache(sz, w=400):
        k = (int(sz), int(w))
        if k not in memo:
            memo[k] = load_font(sz, w, s)
        return memo[k]
    fonts = {
        "brand": load_font(26, 650, s), "chapter": load_font(24, 700, s),
        "pill": load_font(28, 700, s), "hook": load_font(72, 850, s),
        "caption": load_font(44, 550, s), "caption_hi": load_font(48, 800, s),
        "_cache": cache,
    }
    windows, sft = _windows_from_script(script, words, duration)
    frame = render_penjelas_frame(script, 0.5, duration, words, chunks, windows, sft, fonts, PALETTES["light"], "light")
    assert frame.size == (1080, 1920)
    # dark mode juga
    script["visual"]["mode"] = "dark"
    frame_d = render_penjelas_frame(script, 0.5, duration, words, chunks, windows, sft, fonts, PALETTES["dark"], "dark")
    assert frame_d.size == (1080, 1920)


def test_sfx_and_icons_smoke(tmp_path):
    from reels_autopilot.icons import ICON_NAMES, draw_icon
    from reels_autopilot.sfx import pop_sfx, whoosh_sfx, mix_events, write_wav, underwater_ambient

    im = draw_icon("calendar", 64)
    assert im.size == (64, 64) and im.mode == "RGBA"
    for n in ("check", "close", "phone", "shield", "robot"):
        assert draw_icon(n, 48).size == (48, 48)
    samples = pop_sfx() + whoosh_sfx()
    assert len(samples) > 100
    ev = mix_events([(0.1, "pop"), (0.4, "whoosh")], 1.0)
    path = write_wav(tmp_path / "t.wav", ev)
    assert path.exists() and path.stat().st_size > 100
    amb = underwater_ambient(1.5)
    assert len(amb) > 1000


def test_writer_cerita_fallback_without_llm(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.script_writer import ScriptWriter

    settings = Settings()
    settings.root = tmp_path
    w = ScriptWriter(settings)
    monkeypatch.setattr(w.llm, "generate_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    script = w.write({"judul": "Jangan menyerah di tengah jalan", "hook": "Yang berhenti tidak sampai."}, style=STYLE_CERITA)
    assert script["style"] == STYLE_CERITA
    assert script["storyboard"]["beats"]
    assert script["storyboard_fallback"] is True
    assert public_caption_issues(script["caption"]) == []
    assert not (script.get("narasi_penuh") or "") or script.get("pakai_vo") in {False, True}


def test_produce_one_assigns_style_and_keeps_locked_caption(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.pipeline import Pipeline
    from reels_autopilot.state import State
    from reels_autopilot.qc import QCResult

    settings = Settings()
    settings.root = tmp_path
    settings.dry_run = True
    settings.telegram_bot_token = ""
    settings.approval_mode = "required"
    pipe = Pipeline(settings)
    pipe.state = State(settings)
    pipe.state.path = tmp_path / "state.json"
    locked = "Caption final yang sudah dipreview.\nSimpan ini.\n#PoChai #KreatorAI #ReelsIndonesia"
    video = {
        "id": "2026-11-14-s1-test",
        "slot": 1,
        "slot_label": "07:30",
        "judul": "Tes AI",
        "hook": "Hook tes cukup panjang untuk lolos dari filter tipis.",
        "topic": {"judul": "Tes AI ChatGPT", "hook": "Hook tes cukup panjang untuk lolos dari filter tipis."},
        "caption": locked,
        "status": "approved",
        "style": STYLE_PENJELAS,
    }

    def fake_write(topic, style=None, **kwargs):
        return {
            "judul": "BARU", "hook": "hook baru", "narasi_penuh": "narasi " * 20,
            "adegan": [], "caption": "CAPTION BARU YANG BERBEDA\n#X",
            "cta": "Simpan", "hashtag": ["#X"], "llm_provider": "template",
            "image_query": "", "style": style or STYLE_PENJELAS,
        }

    class FakeTTS:
        provider_id = "edge_tts"
        duration = 30.0
        words = []

    monkeypatch.setattr(pipe.writer, "write", fake_write)
    monkeypatch.setattr(pipe.writer, "captions", lambda script: {"varian": []})
    monkeypatch.setattr(pipe.tts, "synthesize", lambda *a, **k: FakeTTS())
    monkeypatch.setattr("reels_autopilot.pipeline.chunk_captions", lambda *a, **k: [])
    monkeypatch.setattr("reels_autopilot.pipeline.render_video", lambda *a, **k: None)
    monkeypatch.setattr(
        "reels_autopilot.pipeline.inspect",
        lambda *a, **k: QCResult(path="x", ok=True, duration=30, width=1080, height=1920, fps=30, has_audio=True, has_video=True),
    )
    monkeypatch.setattr(pipe.images, "search", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))
    sent = {"n": 0}
    monkeypatch.setattr(pipe.tg, "send_preview", lambda *a, **k: sent.__setitem__("n", sent["n"] + 1) or {"ok": True})

    out = pipe.produce_one(video, "2026-11-14", notify=False)
    assert out["caption"] == locked
    assert out["status"] == "approved"
    assert out["style"] == STYLE_PENJELAS
    assert sent["n"] == 0
