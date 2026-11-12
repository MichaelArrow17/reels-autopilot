
from unittest.mock import patch

import pytest

from reels_autopilot.ig_token import REFRESH_URL, refresh_long_lived_token, run


def test_refresh_long_lived_token_calls_instagram_login_endpoint():
    class Resp:
        status_code = 200

        def json(self):
            return {"access_token": "NEWTOKEN", "token_type": "bearer", "expires_in": 5184000}

    with patch("reels_autopilot.ig_token.requests.get", return_value=Resp()) as get:
        out = refresh_long_lived_token("OLDTOKEN")
    assert out["access_token"] == "NEWTOKEN"
    assert out["expires_in"] == 5184000
    args, kwargs = get.call_args
    assert args[0] == REFRESH_URL
    assert kwargs["params"]["grant_type"] == "ig_refresh_token"
    assert kwargs["params"]["access_token"] == "OLDTOKEN"


def test_refresh_run_skips_when_token_missing():
    class S:
        ig_token = ""
        gh_pat = "pat"
        github_releases_repo = "owner/repo"

    out = run(S())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "ig_secrets_missing"


def test_refresh_run_skips_when_gh_pat_missing():
    class S:
        ig_token = "OLD"
        gh_pat = ""
        github_releases_repo = "owner/repo"

    out = run(S())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "gh_pat_missing"
