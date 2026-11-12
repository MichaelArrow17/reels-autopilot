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
    assert _word_count(s["narasi_penuh"]) >= 80
    assert s["cta"]
