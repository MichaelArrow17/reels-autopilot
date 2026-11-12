"""Guard idempoten: GitHub cron + cron-job.org tidak boleh produce/publish ganda."""

from datetime import datetime

from reels_autopilot.config import WITA, resolve_publish_slot
from reels_autopilot.pipeline import (
    Pipeline,
    already_produced,
    already_published,
    already_scouted,
)
from reels_autopilot.state import State


def test_resolve_slot_prefers_explicit_input():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=WITA)
    assert resolve_publish_slot(input_slot="1", schedule_cron="0 4 * * *", now=now) == 1
    assert resolve_publish_slot(input_slot=5, now=now) == 5
    assert resolve_publish_slot(input_slot=" 3 ", now=now) == 3


def test_resolve_slot_uses_github_schedule_when_input_empty():
    now = datetime(2026, 11, 13, 12, 5, tzinfo=WITA)
    # Jadwal 07:30 WITA yang telat tidak boleh ikut ke slot 2.
    assert resolve_publish_slot(input_slot="", schedule_cron="30 23 * * *", now=now) == 1
    assert resolve_publish_slot(schedule_cron="0 4 * * *", now=now) == 2
    assert resolve_publish_slot(schedule_cron="0 9 * * *", now=now) == 3
    assert resolve_publish_slot(schedule_cron="0 11 * * *", now=now) == 4
    assert resolve_publish_slot(schedule_cron="0 13 * * *", now=now) == 5


def test_resolve_slot_auto_detects_nearest_wita_including_midnight_wrap():
    assert resolve_publish_slot(now=datetime(2026, 11, 13, 7, 40, tzinfo=WITA)) == 1
    assert resolve_publish_slot(now=datetime(2026, 11, 13, 12, 0, tzinfo=WITA)) == 2
    assert resolve_publish_slot(now=datetime(2026, 11, 13, 21, 10, tzinfo=WITA)) == 5
    # 00:00 lebih dekat ke 21:00 kemarin daripada ke 07:30.
    assert resolve_publish_slot(now=datetime(2026, 11, 13, 0, 0, tzinfo=WITA)) == 5


def test_resolve_slot_rejects_out_of_range():
    try:
        resolve_publish_slot(input_slot="9")
    except ValueError as e:
        assert "1-5" in str(e)
    else:
        raise AssertionError("expected ValueError")
    try:
        resolve_publish_slot(input_slot="satu")
    except ValueError as e:
        assert "tidak valid" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_already_produced_ignores_missing_mp4():
    assert already_produced({"status": "rendered", "mp4": "/missing/reel.mp4"})
    assert already_produced({"status": "approved"})
    assert already_produced({"status": "published"})
    assert already_produced({"status": "dry_published"})
    assert already_produced({"status": "rejected"})
    assert already_produced({"status": "skipped"})
    assert not already_produced({"status": "pending"})
    assert not already_produced({"status": "failed"})
    assert not already_produced({"status": "qc_failed"})
    assert not already_produced({})


def test_already_scouted_and_force():
    assert already_scouted({"scouted_at": "2026-11-13T07:26:55+08:00"})
    assert already_scouted({"videos": [{"slot": 1}]})
    assert already_scouted({"shortlist": [{"judul": "x"}]})
    assert not already_scouted({})
    assert not already_scouted({"scouted_at": "x"}, force=True)


def test_already_published_uses_ig_id_even_if_status_stale():
    assert already_published({"status": "published"})
    assert already_published({
        "status": "approved",
        "publish": {"ig": {"id": "184", "permalink": "https://www.instagram.com/reel/x/"}},
    })
    assert already_published({
        "status": "rendered",
        "publish": {"ig": {"permalink": "https://www.instagram.com/reel/x/"}},
    })
    assert not already_published({"status": "approved"})
    assert not already_published({"status": "approved", "publish": {"ig": {}}})
    assert not already_published({"status": "dry_published"})


def test_produce_day_skips_rendered_when_mp4_missing(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings

    settings = Settings()
    settings.root = tmp_path
    settings.dry_run = True
    settings.telegram_bot_token = ""
    st = State(settings)
    date = "2026-11-13"
    st.upsert_video({
        "id": f"{date}-s1-aaaaaa",
        "slot": 1,
        "status": "rendered",
        "mp4": str(tmp_path / "nope.mp4"),
        "judul": "Tes",
    }, date)
    pipe = Pipeline(settings)
    pipe.state = st
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("produce_one should not run")

    monkeypatch.setattr(pipe, "produce_one", boom)
    out = pipe.produce_day(date)
    assert out == []
    assert called["n"] == 0
    assert st.video_by_slot(1, date)["status"] == "rendered"


def test_publish_slot_skips_when_already_on_instagram(tmp_path, monkeypatch):
    from reels_autopilot.config import Settings

    settings = Settings()
    settings.root = tmp_path
    settings.dry_run = False
    settings.approval_mode = "required"
    settings.telegram_bot_token = ""
    st = State(settings)
    date = "2026-11-13"
    st.upsert_video({
        "id": f"{date}-s1-bbbbbb",
        "slot": 1,
        "status": "approved",
        "mp4": str(tmp_path / "reel.mp4"),
        "publish": {"ig": {"id": "18418112578086444"}},
    }, date)
    pipe = Pipeline(settings)
    pipe.state = st

    def boom(*_a, **_k):
        raise AssertionError("publisher.publish should not run")

    monkeypatch.setattr(pipe.publisher, "publish", boom)
    res = pipe.publish_slot(1, date)
    assert res == {"ok": False, "reason": "published", "slot": 1}
    assert st.video_by_slot(1, date)["status"] == "published"
