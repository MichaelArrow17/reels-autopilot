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


def test_preview_message_html_is_one_copyable_packet():
    from reels_autopilot.telegram_bot import (
        FB_HANDOFF_HOWTO,
        TG_VIDEO_CAPTION_MAX,
        preview_message_html,
        published_notice_text,
    )

    caption = (
        "Beli saham sekarang beneran bisa cuma modal chat?\n"
        "Kecerdasan buatan kini mampu menganalisis pasar hingga eksekusi trading "
        "langsung dari kolom obrolan. Kamu tidak perlu lagi menghabiskan waktu lama "
        "hanya untuk membaca grafik rumit.\n"
        "Follow akun Po Chai untuk tips AI lainnya.\n"
        "Menurutmu, apakah AI bakal bikin investasi saham jadi lebih aman?\n"
        "#InvestasiSaham #TipsAI #TeknologiFinansial #ArtificialIntelligence #EdukasiSaham"
    )
    video = {
        "slot": 2,
        "slot_label": "12:00",
        "judul": "AI Ubah Cara Investasi Saham Lewat Chat",
        "caption": caption,
        "status": "rendered",
    }
    text = preview_message_html(video)
    assert "<pre><code>" in text and "</code></pre>" in text
    assert caption in text  # exact final caption, unescaped here (no special chars)
    assert "Caption siap tempel ke IG dan FB Po Chai" in text
    assert "Share ke FB Po Chai" in text
    assert "ACC 2" in text
    assert "TOLAK 2" in text
    assert "Sudah ACC" not in text
    assert len(text) <= TG_VIDEO_CAPTION_MAX

    approved = dict(video, status="approved")
    acc = preview_message_html(approved)
    assert "Sudah ACC, tayang jam 12:00 WITA." in acc
    assert "tidak perlu ACC lagi" in acc
    assert "TOLAK 2" in acc
    assert caption in acc
    assert len(acc) <= TG_VIDEO_CAPTION_MAX

    escaped = preview_message_html({
        "slot": 1, "slot_label": "07:30", "judul": "A & B",
        "caption": "A & B <C>", "status": "rendered",
    })
    assert "A &amp; B &lt;C&gt;" in escaped
    assert "A & B <C>" not in escaped

    notice = published_notice_text(approved, "https://www.instagram.com/reel/XXXX/")
    assert "Sudah tayang slot 2 (12:00 WITA)" in notice
    assert "https://www.instagram.com/reel/XXXX/" in notice
    assert caption not in notice
    assert "<pre>" not in notice
    assert "Siap share" not in notice
    assert FB_HANDOFF_HOWTO not in notice


def test_send_preview_uses_html_and_exact_caption(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings
    from reels_autopilot.telegram_bot import TelegramBot

    s = Settings()
    s.telegram_bot_token = "dummy-token"
    s.telegram_chat_id = "7568757522"
    s.approval_mode = "required"
    bot = TelegramBot(s)
    mp4 = tmp_path / "reel.mp4"
    mp4.write_bytes(b"fake-video")
    seen = {}

    def fake_call(method, **kwargs):
        seen["method"] = method
        seen["kwargs"] = kwargs
        return {"ok": True, "result": {"message_id": 99}}

    monkeypatch.setattr(bot, "_call", fake_call)
    video = {
        "slot": 3,
        "slot_label": "17:00",
        "judul": "Kenapa Fitur Otonom Xpeng Belum Aktif di RI?",
        "caption": "Hook topik.\nBaris nilai.\n#PoChai",
        "status": "approved",
    }
    res = bot.send_preview(video, mp4)
    assert res["ok"] is True
    assert seen["method"] == "sendVideo"
    assert seen["kwargs"].get("parse_mode") == "HTML"
    cap = seen["kwargs"].get("caption") or ""
    assert "Hook topik.\nBaris nilai.\n#PoChai" in cap
    assert "Sudah ACC, tayang jam 17:00 WITA." in cap
    assert "<pre><code>" in cap


def test_produce_one_keeps_locked_caption(tmp_path, monkeypatch):
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
    locked = "Caption final yang sudah dipreview.\nSimpan ini.\n#PoChai #KreatorAI #ReelsIndonesia"
    video = {
        "id": "2026-11-13-s2-test",
        "slot": 2,
        "slot_label": "12:00",
        "judul": "Tes",
        "hook": "Hook tes cukup panjang untuk lolos?",
        "topic": {"judul": "Tes", "hook": "Hook tes cukup panjang untuk lolos?"},
        "caption": locked,
        "status": "approved",
    }

    def fake_write(topic):
        return {
            "judul": "BARU",
            "hook": "hook baru",
            "narasi_penuh": "narasi " * 20,
            "adegan": [],
            "caption": "CAPTION BARU YANG BERBEDA\n#X",
            "cta": "Simpan",
            "hashtag": ["#X"],
            "llm_provider": "template",
            "image_query": "",
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

    out = pipe.produce_one(video, "2026-11-13", notify=False)
    assert out["caption"] == locked
    assert out["status"] == "approved"
    assert sent["n"] == 0
