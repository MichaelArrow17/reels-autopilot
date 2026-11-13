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


def test_fallback_caption_has_no_internal_instructions():
    from reels_autopilot.caption_guard import INTERNAL_CAPTION_PHRASES, public_caption_issues
    from reels_autopilot.script_writer import fallback_captions, fallback_script

    s = fallback_script({
        "judul": "cara pakai ai",
        "hook": "cara pakai ai?",
    })
    assert public_caption_issues(s["caption"]) == []
    varian = fallback_captions(s)["varian"][0]
    blob = "\n".join([
        varian["baris1"], varian["isi"], varian["cta"],
        varian.get("pertanyaan") or "", " ".join(varian["hashtag"]),
    ])
    assert public_caption_issues(blob) == []
    for phrase in INTERNAL_CAPTION_PHRASES:
        assert phrase.lower() not in (s["caption"] + blob).lower()
    # isi benar-benar soal topik, bukan rubrik
    assert "cara pakai ai" in varian["isi"].lower()
    assert "explainer" not in varian["isi"].lower()


def test_public_caption_guard_rejects_known_leak():
    from reels_autopilot.caption_guard import public_caption_issues
    leaked = (
        "cara pakai ai?\n"
        "Explainer singkat, satu gagasan per adegan. Tanpa angka yang dikarang.\n"
        "Simpan video ini.\n"
        "Bagian mana yang mau kamu coba dulu?\n"
        "#KreatorAI #PoChai"
    )
    issues = public_caption_issues(leaked)
    assert issues
    assert any("explainer singkat" in e.lower() or "gagasan per adegan" in e.lower() for e in issues)
    assert public_caption_issues(
        "Masih ngedit video manual padahal di CapCut ada fitur AI otomatis?\n"
        "Fitur Naskah AI bisa buat naskah instan dari topik yang kamu ketik.\n"
        "Simpan video ini!\n#CapCutAI"
    ) == []


def test_assemble_public_caption_replaces_leaked_llm_pack():
    from reels_autopilot.caption_guard import public_caption_issues
    from reels_autopilot.script_writer import assemble_public_caption, fallback_script

    script = fallback_script({
        "judul": "Kenapa hook dua detik menentukan Reels",
        "hook": "Dua detik pertama memutuskan kamu ditonton atau dilewati.",
    })
    dirty = {
        "varian": [{
            "baris1": "Hook cepat?",
            "isi": "Explainer singkat, satu gagasan per adegan. Tanpa angka yang dikarang.",
            "cta": "Simpan video ini.",
            "pertanyaan": "Setuju?",
            "hashtag": ["#KreatorAI"],
        }]
    }
    cap = assemble_public_caption(script, dirty)
    assert public_caption_issues(cap) == []
    assert "explainer singkat" not in cap.lower()
    assert "gagasan per adegan" not in cap.lower()
    assert "hook" in cap.lower() or "dua detik" in cap.lower()


def test_writer_captions_drops_leaked_llm_pack(monkeypatch):
    from reels_autopilot.caption_guard import public_caption_issues
    from reels_autopilot.script_writer import ScriptWriter, fallback_script

    script = fallback_script({
        "judul": "cara pakai ai",
        "hook": "cara pakai ai?",
    })
    writer = ScriptWriter()

    def fake_json(*_a, **_k):
        return ({
            "varian": [{
                "baris1": "cara pakai ai?",
                "isi": "Explainer singkat: satu gagasan per adegan, klaim hanya yang bisa dicek.",
                "cta": "Simpan video ini.",
                "pertanyaan": "Coba bagian mana dulu?",
                "hashtag": ["#KreatorAI", "#PoChai", "#ReelsIndonesia"],
            }]
        }, "gemini")

    monkeypatch.setattr(writer.llm, "generate_json", fake_json)
    pack = writer.captions(script)
    assert pack.get("llm_provider") == "template"
    blob = " ".join((pack["varian"][0].get(k) or "") for k in ("baris1", "isi", "cta"))
    assert public_caption_issues(blob) == []
