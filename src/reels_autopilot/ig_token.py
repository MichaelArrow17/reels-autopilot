"""Refresh / health-check token Instagram dan simpan ke GitHub Secret.

Token saat ini adalah Facebook Login for Business (prefiks EAAP) yang
berjalan di graph.facebook.com, bukan Instagram Login di graph.instagram.com.

Jika FB_APP_ID + FB_APP_SECRET ada:
    GET graph.facebook.com/v21.0/oauth/access_token
        ?grant_type=fb_exchange_token&client_id&client_secret&fb_exchange_token
    lalu tulis ulang secret IG_ACCESS_TOKEN lewat GH_PAT,
    lalu debug_token (app token = app_id|app_secret).
    Telegram alert jika token invalid atau sisa umur < 10 hari.

Jika app secret tidak ada:
    health check GET /{ig-user-id}?fields=username di IG_GRAPH_HOST
    dan Telegram alert jika gagal.

GITHUB_TOKEN otomatis Actions TIDAK bisa menulis secret — pakai secret GH_PAT
(fine-grained PAT: secrets RW pada repo ini).
Nilai token / app secret tidak pernah ditulis ke log.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from base64 import b64encode
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings

log = logging.getLogger("reels.ig_token")
FB_OAUTH_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
FB_DEBUG_URL = "https://graph.facebook.com/v21.0/debug_token"
SECRET_NAME = "IG_ACCESS_TOKEN"
ALIAS_SECRET_NAME = "IG_TOKEN"
EXPIRY_ALERT_SECONDS = 10 * 24 * 3600


def _graph_error_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}"
    err = body.get("error") if isinstance(body, dict) else {}
    if not isinstance(err, dict):
        return f"HTTP {resp.status_code}"
    msg = err.get("message") or f"HTTP {resp.status_code}"
    code = err.get("code")
    return f"{code} {msg}" if code is not None else str(msg)


def exchange_fb_token(
    token: str,
    app_id: str,
    app_secret: str,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Tukar token lewat fb_exchange_token. Nilai token tidak dilog."""
    if not token:
        raise RuntimeError("IG_ACCESS_TOKEN kosong")
    if not app_id or not app_secret:
        raise RuntimeError("FB_APP_ID / FB_APP_SECRET kosong")
    r = requests.get(
        FB_OAUTH_URL,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": token,
        },
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = {"text_len": len(r.text or "")}
    if r.status_code >= 400 or not (isinstance(body, dict) and body.get("access_token")):
        raise RuntimeError(f"fb exchange gagal: {_graph_error_message(r)}")
    return {
        "access_token": body["access_token"],
        "token_type": body.get("token_type") or "bearer",
        "expires_in": body.get("expires_in"),
    }


def debug_token(
    token: str,
    app_id: str,
    app_secret: str,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    """Inspeksi token. App token = app_id|app_secret. Tidak dilog nilai token."""
    if not token or not app_id or not app_secret:
        raise RuntimeError("debug_token butuh token, FB_APP_ID, dan FB_APP_SECRET")
    r = requests.get(
        FB_DEBUG_URL,
        params={
            "input_token": token,
            "access_token": f"{app_id}|{app_secret}",
        },
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code >= 400:
        raise RuntimeError(f"debug_token gagal: {_graph_error_message(r)}")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("debug_token: respons tanpa data")
    expires_at = data.get("expires_at") or 0
    try:
        expires_at = int(expires_at)
    except (TypeError, ValueError):
        expires_at = 0
    is_valid = bool(data.get("is_valid"))
    remaining = (expires_at - int(time.time())) if expires_at else None
    return {
        "is_valid": is_valid,
        "expires_at": expires_at or None,
        "remaining_seconds": remaining,
        "app_id": data.get("app_id"),
        "type": data.get("type"),
        "scopes_count": len(data.get("scopes") or []),
    }


def health_check(
    token: str,
    user_id: str,
    *,
    graph_base: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """GET /{ig-user-id}?fields=username. Token tidak dilog."""
    if not token or not user_id:
        raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN kosong")
    r = requests.get(
        f"{graph_base}/{user_id}",
        params={"fields": "username", "access_token": token},
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = {}
    if r.status_code >= 400 or not (isinstance(body, dict) and body.get("username")):
        raise RuntimeError(f"ig health check gagal: {_graph_error_message(r)}")
    return {"ok": True, "username": body.get("username"), "id": body.get("id")}


def _encrypt_secret(public_key_b64: str, value: str) -> str:
    from nacl import encoding, public

    pk = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    return b64encode(public.SealedBox(pk).encrypt(value.encode("utf-8"))).decode("utf-8")


def update_github_secret(
    name: str,
    value: str,
    *,
    repo: str,
    pat: str,
    timeout: int = 45,
) -> str:
    """Update Actions secret lewat REST (PyNaCl) atau fallback `gh secret set`.

    Return 'api' atau 'gh'. Tidak mencetak nilai secret.
    """
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY (owner/name) belum diisi")
    if not pat:
        raise RuntimeError("GH_PAT belum diisi (GITHUB_TOKEN Actions tidak bisa menulis secret)")

    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "reels-autopilot-ig-refresh",
    }
    base = f"https://api.github.com/repos/{repo}"
    try:
        from nacl import encoding, public  # noqa: F401

        pk_r = requests.get(f"{base}/actions/secrets/public-key", headers=headers, timeout=timeout)
        pk_r.raise_for_status()
        pk = pk_r.json()
        encrypted = _encrypt_secret(pk["key"], value)
        put = requests.put(
            f"{base}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": pk["key_id"]},
            timeout=timeout,
        )
        if put.status_code not in {201, 204}:
            raise RuntimeError(f"GitHub secret PUT {name} HTTP {put.status_code}")
        return "api"
    except ImportError:
        log.info("PyNaCl tidak ada; memakai gh secret set")
    except Exception as e:
        log.warning("REST secret update gagal (%s); coba gh", type(e).__name__)

    env = os.environ.copy()
    env["GH_TOKEN"] = pat
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo],
        input=value.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:200]
        err = err.replace(value, "***").replace(pat, "***")
        raise RuntimeError(f"gh secret set gagal: {err}")
    return "gh"


def _alert(settings: Settings, text: str) -> bool:
    """Kirim peringatan singkat ke Telegram. Jangan sertakan token."""
    try:
        from reels_autopilot.telegram_bot import TelegramBot

        res = TelegramBot(settings).send(text)
        return bool(res.get("ok", True)) and res.get("reason") not in {"no chat_id", "not_configured"}
    except Exception as e:
        log.warning("Telegram alert gagal: %s", type(e).__name__)
        return False


def _persist_token(new_token: str, *, repo: str, pat: str) -> tuple[str, bool]:
    via = update_github_secret(SECRET_NAME, new_token, repo=repo, pat=pat)
    try:
        update_github_secret(ALIAS_SECRET_NAME, new_token, repo=repo, pat=pat)
        alias = True
    except Exception as e:
        log.info("Alias IG_TOKEN tidak di-update: %s", type(e).__name__)
        alias = False
    return via, alias


def run(settings: Settings | None = None, *, repo: str | None = None) -> dict[str, Any]:
    """Refresh (jika app secret ada) atau health check. Skip bersih jika token kosong."""
    s = settings or get_settings()
    token = s.ig_token
    user_id = s.ig_user_id
    pat = s.gh_pat or ""
    repo = repo or os.environ.get("GITHUB_REPOSITORY") or s.github_releases_repo or ""
    app_id = s.fb_app_id or ""
    app_secret = s.fb_app_secret or ""

    if not token or not user_id:
        log.warning("Refresh/health IG dilewati: IG_USER_ID / IG_ACCESS_TOKEN belum diisi.")
        return {"ok": False, "reason": "ig_secrets_missing"}

    if app_id and app_secret:
        return _run_exchange(s, token=token, user_id=user_id, app_id=app_id, app_secret=app_secret, repo=repo, pat=pat)

    log.info("FB_APP_SECRET tidak ada; menjalankan health check saja.")
    return _run_health(s, token=token, user_id=user_id)


def _run_health(s: Settings, *, token: str, user_id: str) -> dict[str, Any]:
    try:
        checked = health_check(token, user_id, graph_base=s.ig_graph_base)
    except Exception as e:
        msg = str(e)[:200]
        log.warning("IG health check gagal: %s", msg)
        _alert(s, f"IG health check gagal: {msg}")
        return {"ok": False, "reason": "health_check_failed", "mode": "health_check", "error": msg}
    log.info("IG health check OK, username=%s", checked.get("username"))
    return {"ok": True, "mode": "health_check", "username": checked.get("username")}


def _run_exchange(
    s: Settings,
    *,
    token: str,
    user_id: str,
    app_id: str,
    app_secret: str,
    repo: str,
    pat: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "exchange"}
    current = token
    exchanged = False

    # Token SYSTEM_USER / tanpa kedaluwarsa (expires_at=0) tidak perlu ditukar.
    never_expires = False
    try:
        pre = debug_token(token, app_id, app_secret)
        never_expires = bool(pre["is_valid"]) and (pre["expires_at"] is None or pre.get("type") == "SYSTEM_USER")
    except Exception as e:
        log.info("Pre-check debug_token gagal: %s", type(e).__name__)

    # Jangan tukar token kalau hasilnya tidak bisa disimpan — token lama bisa tidak berlaku.
    if never_expires:
        log.info("Token tidak kedaluwarsa (SYSTEM_USER); exchange dilewati.")
        result["exchange_skipped"] = "never_expires"
    elif not pat:
        log.warning("FB_APP_SECRET ada tapi GH_PAT kosong; exchange dilewati, debug_token saja.")
        result["exchange_skipped"] = "gh_pat_missing"
    elif not repo:
        log.warning("FB_APP_SECRET ada tapi GITHUB_REPOSITORY kosong; exchange dilewati, debug_token saja.")
        result["exchange_skipped"] = "repo_missing"
    else:
        try:
            refreshed = exchange_fb_token(token, app_id, app_secret)
            new_token = refreshed["access_token"]
            via, alias = _persist_token(new_token, repo=repo, pat=pat)
            current = new_token
            exchanged = True
            result.update(
                {
                    "via": via,
                    "alias_updated": alias,
                    "expires_in": refreshed.get("expires_in"),
                    "token_len": len(new_token),
                }
            )
            log.info(
                "IG_ACCESS_TOKEN diperbarui via %s; expires_in=%s detik; alias_IG_TOKEN=%s",
                via,
                refreshed.get("expires_in"),
                alias,
            )
        except Exception as e:
            msg = str(e)[:200]
            log.warning("Exchange token gagal: %s", msg)
            result["exchange_error"] = msg

    try:
        inspected = debug_token(current, app_id, app_secret)
    except Exception as e:
        msg = str(e)[:200]
        log.warning("debug_token gagal: %s", msg)
        _alert(s, f"IG debug_token gagal: {msg}")
        result.update({"ok": False, "reason": "debug_token_failed", "error": msg, "exchanged": exchanged})
        return result

    result["debug"] = {
        "is_valid": inspected["is_valid"],
        "expires_at": inspected["expires_at"],
        "remaining_seconds": inspected["remaining_seconds"],
        "scopes_count": inspected["scopes_count"],
    }

    if not inspected["is_valid"]:
        _alert(s, "IG token tidak valid. Perlu login ulang di Meta app Reels Autopilot RD.")
        result.update({"ok": False, "reason": "token_invalid", "exchanged": exchanged})
        return result

    remaining = inspected["remaining_seconds"]
    if remaining is not None and remaining < EXPIRY_ALERT_SECONDS:
        days = max(0, remaining // 86400)
        _alert(s, f"IG token sisa {days} hari (< 10 hari). Perlu refresh atau login ulang.")
        result["expiry_warning"] = True

    # Health check pelengkap (username), tidak menggagalkan kalau debug sudah valid.
    try:
        checked = health_check(current, user_id, graph_base=s.ig_graph_base)
        result["username"] = checked.get("username")
    except Exception as e:
        log.warning("Health check setelah debug gagal: %s", type(e).__name__)

    result.update({"ok": True, "exchanged": exchanged})
    return result
