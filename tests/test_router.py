from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reels_autopilot.config import Settings
from reels_autopilot.providers.router import (
    AllProvidersFailed,
    ProviderRouter,
    QuotaExhausted,
)


@pytest.fixture
def router(tmp_path, monkeypatch):
    monkeypatch.setenv("REELS_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "src").mkdir()
    s = Settings()
    # Settings.root may already be cached via find_root — set status via object dict by wrapping store
    r = ProviderRouter(s)
    r.status.path = tmp_path / "data" / "provider_status.json"
    r.status._data = {}
    return r


def test_failover_to_second_then_resume_primary(router):
    calls = []

    def primary():
        calls.append("gemini")
        raise QuotaExhausted("gemini", "RESOURCE_EXHAUSTED")

    def secondary():
        calls.append("groq")
        return "ok-groq"

    r = router.execute("llm", {"gemini": primary, "groq": secondary})
    assert r.provider_id == "groq"
    assert r.value == "ok-groq"
    assert any(p == "gemini" for p, _ in r.tried)

    calls.clear()
    r2 = router.execute("llm", {"gemini": primary, "groq": secondary})
    assert r2.provider_id == "groq"
    assert "gemini" not in calls

    rec = router.status.get("llm", "gemini")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    rec.cooldown_until = past
    rec.quota_reset_at = past
    rec.quota_exhausted = True
    router.status.save()

    def primary_ok():
        calls.append("gemini")
        return "ok-gemini"

    calls.clear()
    r3 = router.execute("llm", {"gemini": primary_ok, "groq": secondary})
    assert r3.provider_id == "gemini"
    assert r3.value == "ok-gemini"
    assert calls[0] == "gemini"


def test_all_fail(router):
    def boom():
        raise RuntimeError("mati")

    with pytest.raises(AllProvidersFailed) as ei:
        router.execute("llm", {"gemini": boom, "groq": boom, "template": boom})
    assert ei.value.category == "llm"
