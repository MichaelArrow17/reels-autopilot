from reels_autopilot.config import TARGET_WORDS_MAX, TARGET_WORDS_MIN
from reels_autopilot.script_writer import fallback_script, _word_count


def test_fallback_has_hook_and_five_scenes():
    s = fallback_script({
        "judul": "Kenapa hook dua detik menentukan Reels",
        "hook": "Dua detik pertama memutuskan kamu ditonton atau dilewati.",
    })
    assert s["hook"]
    assert "Di video ini" not in s["narasi_penuh"]
    assert "Halo guys" not in s["narasi_penuh"]
    assert len(s["adegan"]) == 5
    assert s["is_ai_generated"] is True
    n = _word_count(s["narasi_penuh"])
    assert TARGET_WORDS_MIN <= n <= TARGET_WORDS_MAX
    assert s["cta"]
    assert s["durasi_target_detik"] <= 45


def test_fallback_caption_not_thin():
    from reels_autopilot.script_writer import fallback_captions, enrich_hook_line
    import re

    s = fallback_script({
        "judul": "cara pakai ai",
        "hook": "cara pakai ai?",
    })
    cap = s["caption"]
    assert cap.strip().lower() != "cara pakai ai?"
    lines = [ln.strip() for ln in cap.splitlines() if ln.strip()]
    assert len(lines) >= 4
    hook_line = enrich_hook_line("cara pakai ai?", "cara pakai ai")
    assert hook_line.lower() != "cara pakai ai?"
    assert len(hook_line.split()) >= 8
    assert hook_line in cap
    assert any("simpan" in ln.lower() or "follow" in ln.lower() for ln in lines)
    tags = re.findall(r"#\w+", cap)
    assert 3 <= len(set(tags)) <= 5
    # hashtag utamakan Indonesia
    assert "#KreatorAI" in tags
    assert "#PoChai" in tags

    varian = fallback_captions(s)["varian"][0]
    assert varian["baris1"].strip().lower() != "cara pakai ai?"
    assert len((varian.get("isi") or "").split()) >= 8
    assert varian["cta"]
    assert any(k in varian["cta"].lower() for k in ("simpan", "follow"))
    assert 3 <= len(varian["hashtag"]) <= 5


def test_fallback_keeps_rich_hook_line():
    hook = "Dua detik pertama memutuskan kamu ditonton atau dilewati."
    s = fallback_script({
        "judul": "Kenapa hook dua detik menentukan Reels",
        "hook": hook,
    })
    assert s["caption"].splitlines()[0] == hook
