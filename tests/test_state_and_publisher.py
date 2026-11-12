from pathlib import Path

from reels_autopilot.config import Settings
from reels_autopilot.publisher import Publisher
from reels_autopilot.state import State


def test_dedupe_similar_titles(tmp_path):
    st = State.__new__(State)
    st.settings = Settings()
    st.path = tmp_path / "state.json"
    st.data = {"past_topics": [], "days": {}, "telegram": {}, "paused": False, "paused_until": None}
    st.settings.past_topics_path  # just access
    # redirect past path
    class S:
        pass
    # wrap save to tmp
    original_save = State.save

    def save(self):
        self.path.write_text("{}", encoding="utf-8")
        (tmp_path / "past.json").write_text("[]", encoding="utf-8")

    st.save = lambda: None
    st.add_past_topic("Kenapa AI kadang ngarang fakta")
    assert st.similar_past("Kenapa AI kadang ngarang fakta") is not None
    assert st.similar_past("Topik yang sama sekali berbeda tentang masakan padang") is None


def test_publisher_dry_run_writes_file_no_network(tmp_path, monkeypatch):
    s = Settings()
    s.dry_run = True
    s.fb_page_token = "SECRETTOKEN123"
    s.fb_page_id = "123"
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"fake")
    pub = Publisher(s)
    pub.settings = s

    # inject dry_run_dir by wrapping
    from reels_autopilot import publisher as pubmod

    written = {}
    real_write = None

    result = pub.publish(mp4, caption="tes caption", dest_fb=True, dest_ig=True)
    # default dry_run_dir is under real repo data/dry_run — that's ok for this test
    assert result["dry_run"] is True
    path = Path(result["dry_run_path"])
    assert path.exists()
    text = path.read_text()
    assert "SECRETTOKEN123" not in text
    assert "tes caption" in text
    assert "Profil pribadi TIDAK didukung" in text
    path.unlink(missing_ok=True)
