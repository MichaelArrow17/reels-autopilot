import time
from unittest.mock import patch

from reels_autopilot.config import Settings
from reels_autopilot.ig_token import (
    FB_DEBUG_URL,
    FB_OAUTH_URL,
    debug_token,
    exchange_fb_token,
    health_check,
    run,
)


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def test_exchange_fb_token_uses_facebook_oauth_endpoint():
    payload = {"access_token": "NEWTOKEN", "token_type": "bearer", "expires_in": 5184000}
    with patch("reels_autopilot.ig_token.requests.get", return_value=_Resp(200, payload)) as get:
        out = exchange_fb_token("OLDTOKEN", "111", "secret")
    assert out["access_token"] == "NEWTOKEN"
    assert out["expires_in"] == 5184000
    args, kwargs = get.call_args
    assert args[0] == FB_OAUTH_URL
    assert kwargs["params"]["grant_type"] == "fb_exchange_token"
    assert kwargs["params"]["client_id"] == "111"
    assert kwargs["params"]["fb_exchange_token"] == "OLDTOKEN"
    assert "secret" in kwargs["params"]["client_secret"]


def test_debug_token_reports_validity_and_remaining():
    now = int(time.time())
    payload = {"data": {"is_valid": True, "expires_at": now + 20 * 86400, "scopes": ["instagram_basic"]}}
    with patch("reels_autopilot.ig_token.requests.get", return_value=_Resp(200, payload)) as get:
        out = debug_token("TOK", "111", "secret")
    assert out["is_valid"] is True
    assert out["remaining_seconds"] > 19 * 86400
    args, kwargs = get.call_args
    assert args[0] == FB_DEBUG_URL
    assert kwargs["params"]["access_token"] == "111|secret"


def test_health_check_hits_configurable_graph_host():
    with patch(
        "reels_autopilot.ig_token.requests.get",
        return_value=_Resp(200, {"username": "achmad_radinal94", "id": "1784"}),
    ) as get:
        out = health_check("TOK", "1784", graph_base="https://graph.facebook.com/v21.0")
    assert out["ok"] is True
    assert out["username"] == "achmad_radinal94"
    assert get.call_args[0][0] == "https://graph.facebook.com/v21.0/1784"


def test_refresh_run_skips_when_token_missing():
    class S:
        ig_token = ""
        ig_user_id = "1784"
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = ""
        fb_app_secret = ""
        ig_graph_base = "https://graph.facebook.com/v21.0"

    out = run(S())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "ig_secrets_missing"


def test_refresh_run_skips_when_user_id_missing():
    class S:
        ig_token = "OLD"
        ig_user_id = ""
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    out = run(S())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "ig_secrets_missing"


def test_run_health_check_when_app_secret_absent():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = ""
        github_releases_repo = "owner/repo"
        fb_app_id = ""
        fb_app_secret = ""
        ig_graph_base = "https://graph.facebook.com/v21.0"
        telegram_bot_token = ""
        telegram_chat_id = ""

    with patch(
        "reels_autopilot.ig_token.health_check",
        return_value={"ok": True, "username": "achmad_radinal94"},
    ) as hc:
        out = run(S())  # type: ignore[arg-type]
    hc.assert_called_once()
    assert out["ok"] is True
    assert out["mode"] == "health_check"
    assert out["username"] == "achmad_radinal94"


def test_run_health_check_alerts_on_failure():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = ""
        github_releases_repo = "owner/repo"
        fb_app_id = ""
        fb_app_secret = ""
        ig_graph_base = "https://graph.facebook.com/v21.0"

    with (
        patch("reels_autopilot.ig_token.health_check", side_effect=RuntimeError("HTTP 190")),
        patch("reels_autopilot.ig_token._alert", return_value=True) as alert,
    ):
        out = run(S())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "health_check_failed"
    alert.assert_called_once()
    assert "HTTP 190" in alert.call_args[0][1]


def test_run_exchange_persists_and_debugs():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    now = int(time.time())
    with (
        patch(
            "reels_autopilot.ig_token.exchange_fb_token",
            return_value={"access_token": "NEW", "expires_in": 5184000},
        ),
        patch("reels_autopilot.ig_token.update_github_secret", return_value="api") as upsert,
        patch(
            "reels_autopilot.ig_token.debug_token",
            return_value={
                "is_valid": True,
                "expires_at": now + 50 * 86400,
                "remaining_seconds": 50 * 86400,
                "scopes_count": 4,
            },
        ),
        patch(
            "reels_autopilot.ig_token.health_check",
            return_value={"ok": True, "username": "achmad_radinal94"},
        ),
        patch("reels_autopilot.ig_token._alert") as alert,
    ):
        out = run(S(), repo="owner/repo")  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out["mode"] == "exchange"
    assert out["exchanged"] is True
    assert out["via"] == "api"
    assert upsert.call_count >= 1
    assert upsert.call_args_list[0][0][0] == "IG_ACCESS_TOKEN"
    assert upsert.call_args_list[0][0][1] == "NEW"
    alert.assert_not_called()


def test_run_exchange_alerts_when_expiry_under_10_days():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    now = int(time.time())
    with (
        patch(
            "reels_autopilot.ig_token.exchange_fb_token",
            return_value={"access_token": "NEW", "expires_in": 86400},
        ),
        patch("reels_autopilot.ig_token.update_github_secret", return_value="api"),
        patch(
            "reels_autopilot.ig_token.debug_token",
            return_value={
                "is_valid": True,
                "expires_at": now + 3 * 86400,
                "remaining_seconds": 3 * 86400,
                "scopes_count": 4,
            },
        ),
        patch("reels_autopilot.ig_token.health_check", return_value={"ok": True, "username": "x"}),
        patch("reels_autopilot.ig_token._alert", return_value=True) as alert,
    ):
        out = run(S(), repo="owner/repo")  # type: ignore[arg-type]
    assert out["ok"] is True
    assert out.get("expiry_warning") is True
    assert "10 hari" in alert.call_args[0][1]


def test_run_exchange_alerts_when_token_invalid():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    with (
        patch(
            "reels_autopilot.ig_token.exchange_fb_token",
            return_value={"access_token": "NEW", "expires_in": 100},
        ),
        patch("reels_autopilot.ig_token.update_github_secret", return_value="api"),
        patch(
            "reels_autopilot.ig_token.debug_token",
            return_value={
                "is_valid": False,
                "expires_at": None,
                "remaining_seconds": None,
                "scopes_count": 0,
            },
        ),
        patch("reels_autopilot.ig_token._alert", return_value=True) as alert,
    ):
        out = run(S(), repo="owner/repo")  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "token_invalid"
    assert "tidak valid" in alert.call_args[0][1]


def test_run_skips_exchange_without_pat_but_still_debugs():
    class S:
        ig_token = "OLD"
        ig_user_id = "1784"
        gh_pat = ""
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    now = int(time.time())
    with (
        patch("reels_autopilot.ig_token.exchange_fb_token") as ex,
        patch(
            "reels_autopilot.ig_token.debug_token",
            return_value={
                "is_valid": True,
                "expires_at": now + 40 * 86400,
                "remaining_seconds": 40 * 86400,
                "scopes_count": 4,
            },
        ) as dbg,
        patch("reels_autopilot.ig_token.health_check", return_value={"ok": True, "username": "x"}),
        patch("reels_autopilot.ig_token._alert") as alert,
    ):
        out = run(S(), repo="owner/repo")  # type: ignore[arg-type]
    ex.assert_not_called()
    assert dbg.called
    assert out["ok"] is True
    assert out["exchanged"] is False
    assert out["exchange_skipped"] == "gh_pat_missing"
    alert.assert_not_called()


def test_ig_graph_host_default_and_override(monkeypatch):
    monkeypatch.delenv("IG_GRAPH_HOST", raising=False)
    monkeypatch.delenv("IG_GRAPH_VERSION", raising=False)
    s = Settings()
    assert s.ig_graph_host == "graph.facebook.com"
    assert s.ig_graph_base == "https://graph.facebook.com/v21.0"
    monkeypatch.setenv("IG_GRAPH_HOST", "graph.instagram.com")
    monkeypatch.setenv("IG_GRAPH_VERSION", "v22.0")
    s2 = Settings()
    assert s2.ig_graph_base == "https://graph.instagram.com/v22.0"


def test_run_skips_exchange_for_system_user_token():
    class S:
        ig_token = "TOK"
        ig_user_id = "1784"
        gh_pat = "pat"
        github_releases_repo = "owner/repo"
        fb_app_id = "111"
        fb_app_secret = "sec"
        ig_graph_base = "https://graph.facebook.com/v21.0"

    with (
        patch("reels_autopilot.ig_token.exchange_fb_token") as ex,
        patch(
            "reels_autopilot.ig_token.debug_token",
            return_value={"is_valid": True, "expires_at": None, "remaining_seconds": None, "scopes_count": 6, "type": "SYSTEM_USER"},
        ),
        patch("reels_autopilot.ig_token.health_check", return_value={"ok": True, "username": "x"}),
        patch("reels_autopilot.ig_token._alert") as alert,
    ):
        out = run(S(), repo="owner/repo")  # type: ignore[arg-type]
    ex.assert_not_called()
    alert.assert_not_called()
    assert out["ok"] is True
    assert out["exchange_skipped"] == "never_expires"
