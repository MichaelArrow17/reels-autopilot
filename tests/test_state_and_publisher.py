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
    assert "graph.facebook.com" in text or "Telegram" in text or "profil" in text.lower()
    path.unlink(missing_ok=True)


def test_publisher_skips_when_meta_secrets_missing(tmp_path):
    s = Settings()
    s.dry_run = False
    s.fb_page_id = ""
    s.fb_page_token = ""
    s.ig_user_id = ""
    s.ig_token = ""
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"fake")
    result = Publisher(s).publish(mp4, caption="tes", dest_fb=True, dest_ig=True)
    assert result["skipped"] is True
    assert result["reason"] == "ig_secrets_missing"
    assert result["ig"]["reason"] == "missing_ig_secrets"
    # tidak boleh menandai sukses publish
    assert result.get("dry_run") is False


def test_publisher_default_skips_ig_without_requiring_fb(tmp_path):
    s = Settings()
    s.dry_run = False
    s.fb_page_id = ""
    s.fb_page_token = ""
    s.ig_user_id = ""
    s.ig_token = ""
    mp4 = tmp_path / "x.mp4"
    mp4.write_bytes(b"fake")
    # dest_fb default = False karena secret FB kosong (opsional)
    result = Publisher(s).publish(mp4, caption="tes")
    assert result["skipped"] is True
    assert result["reason"] == "ig_secrets_missing"


def test_ig_access_token_env_alias(monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "NEWSTYLE")
    monkeypatch.delenv("IG_TOKEN", raising=False)
    s = Settings()
    assert s.ig_token == "NEWSTYLE"
    assert s.ig_configured is False  # user id masih kosong
    monkeypatch.setenv("IG_USER_ID", "1789")
    s2 = Settings()
    assert s2.ig_configured is True


def test_ig_graph_base_default_is_facebook_v21(monkeypatch):
    monkeypatch.delenv("IG_GRAPH_HOST", raising=False)
    monkeypatch.delenv("IG_GRAPH_VERSION", raising=False)
    s = Settings()
    assert s.ig_graph_base == "https://graph.facebook.com/v21.0"


def test_ig_reel_publishes_and_fetches_permalink(monkeypatch):
    s = Settings()
    s.dry_run = False
    s.ig_user_id = "1784"
    s.ig_token = "TOK"
    s.ig_graph_host = "graph.facebook.com"
    s.ig_graph_version = "v21.0"
    pub = Publisher(s)

    posts = []
    gets = []

    class Resp:
        def __init__(self, payload, status_code=200):
            self.status_code = status_code
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    def fake_post(url, data=None, timeout=None, **kwargs):
        posts.append(url)
        if url.endswith("/media"):
            return Resp({"id": "container1"})
        if url.endswith("/media_publish"):
            return Resp({"id": "media99"})
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, params=None, timeout=None, **kwargs):
        gets.append((url, (params or {}).get("fields")))
        if url.endswith("/container1"):
            return Resp({"status_code": "FINISHED"})
        if url.endswith("/media99"):
            return Resp({"id": "media99", "permalink": "https://www.instagram.com/reel/ABC/"})
        raise AssertionError(f"unexpected GET {url}")

    import reels_autopilot.publisher as pubmod

    monkeypatch.setattr(pubmod.requests, "post", fake_post)
    monkeypatch.setattr(pubmod.requests, "get", fake_get)
    monkeypatch.setattr(pubmod.time, "sleep", lambda _s: None)

    out = pub.ig_reel("https://example.com/v.mp4", "caption tes")
    assert out["id"] == "media99"
    assert out["permalink"] == "https://www.instagram.com/reel/ABC/"
    assert posts[0] == "https://graph.facebook.com/v21.0/1784/media"
    assert posts[1] == "https://graph.facebook.com/v21.0/1784/media_publish"
    assert any(u.endswith("/media99") for u, _ in gets)


def test_ig_reel_survives_permalink_failure(monkeypatch):
    s = Settings()
    s.dry_run = False
    s.ig_user_id = "1784"
    s.ig_token = "TOK"
    pub = Publisher(s)

    class Resp:
        def __init__(self, payload, status_code=200):
            self.status_code = status_code
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    def fake_post(url, data=None, timeout=None, **kwargs):
        if url.endswith("/media"):
            return Resp({"id": "c1"})
        return Resp({"id": "m1"})

    def fake_get(url, params=None, timeout=None, **kwargs):
        if url.endswith("/c1"):
            return Resp({"status_code": "FINISHED"})
        return Resp({}, status_code=400)

    import reels_autopilot.publisher as pubmod

    monkeypatch.setattr(pubmod.requests, "post", fake_post)
    monkeypatch.setattr(pubmod.requests, "get", fake_get)
    monkeypatch.setattr(pubmod.time, "sleep", lambda _s: None)

    out = pub.ig_reel("https://example.com/v.mp4", "caption tes")
    assert out["id"] == "m1"
    assert "permalink" not in out

def test_asset_name_from_job_path():
    from reels_autopilot.publisher import _asset_name
    path = Path("/home/runner/work/reels-autopilot/reels-autopilot/data/jobs/2026-11-12/slot1/reel.mp4")
    assert _asset_name(path) == "2026-11-12-slot1-reel.mp4"


def test_assert_public_video_url_retries_then_ok(monkeypatch):
    from reels_autopilot import publisher as pubmod

    calls = {"n": 0}

    class Fake:
        def __init__(self, status, content=b"mp4"):
            self.status_code = status
            self._content = content

        def iter_content(self, _size):
            yield self._content

        def close(self):
            return None

    def fake_head(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return Fake(404)
        return Fake(200)

    monkeypatch.setattr(pubmod.requests, "head", fake_head)
    monkeypatch.setattr(pubmod.time, "sleep", lambda *_: None)
    pubmod._assert_public_video_url("https://example.com/v.mp4")
    assert calls["n"] == 2


def test_fb_handoff_text_is_copyable_and_drops_old_line():
    from reels_autopilot.telegram_bot import FB_HANDOFF_HOWTO, fb_handoff_text

    caption = "cara pakai ai?\nSimpan video ini.\n#KreatorAI #PoChai"
    permalink = "https://www.instagram.com/reel/DfpSYK-CuMW/"
    text = fb_handoff_text(caption, permalink)
    assert "<pre><code>" in text and "</code></pre>" in text
    assert "cara pakai ai?" in text
    assert "#KreatorAI" in text
    assert FB_HANDOFF_HOWTO.replace(">", "&gt;") in text or FB_HANDOFF_HOWTO in text
    assert permalink in text
    assert "cek FB Po Chai" not in text
    # ampersand/chevron di caption di-escape di dalam blok
    escaped = fb_handoff_text("A & B <C>", None)
    assert "A &amp; B &lt;C&gt;" in escaped


def test_send_fb_handoff_retries_then_swallows(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.telegram_bot import FB_HANDOFF_VIDEO_CAPTION, TelegramBot

    s = Settings()
    s.telegram_bot_token = "dummy-token"
    s.telegram_chat_id = "7568757522"
    bot = TelegramBot(s)
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"fake-video")
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("telegram down")

    monkeypatch.setattr(bot, "send_video", boom)
    monkeypatch.setattr(bot, "send", boom)
    out = bot.send_fb_handoff(
        mp4=mp4,
        caption="hook\\nisi\\n#PoChai",
        permalink="https://www.instagram.com/reel/DfpSYK-CuMW/",
    )
    assert out["ok"] is False
    assert calls["n"] >= 2  # minimal video retried
    assert all(p.get("reason") == "telegram_send_failed" or p.get("ok") is False for p in out["parts"])


def test_send_video_sets_supports_streaming(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.telegram_bot import TelegramBot

    s = Settings()
    s.telegram_bot_token = "dummy-token"
    s.telegram_chat_id = "7568757522"
    bot = TelegramBot(s)
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"fake-video")
    seen = {}

    def fake_call(method, **kwargs):
        seen["method"] = method
        seen["kwargs"] = kwargs
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(bot, "_call", fake_call)
    res = bot.send_video(mp4, "Siap share ke FB Po Chai", supports_streaming=True)
    assert res["ok"] is True
    assert seen["method"] == "sendVideo"
    assert seen["kwargs"].get("supports_streaming") == "true"
    assert "files" in seen["kwargs"]
