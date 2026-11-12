"""Refresh long-lived Instagram User token (Instagram Login) and simpan ke GitHub Secret.

GET https://graph.instagram.com/refresh_access_token
    ?grant_type=ig_refresh_token&access_token=...

Token jangka panjang berlaku ~60 hari. Refresh boleh dilakukan setelah 24 jam
dan sebelum kedaluwarsa. Workflow bulanan memanggil ini.

GITHUB_TOKEN otomatis Actions TIDAK bisa menulis secret — pakai secret GH_PAT
(fine-grained PAT: secrets RW pada repo ini).
Nilai token tidak pernah ditulis ke log.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from base64 import b64encode
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings

log = logging.getLogger("reels.ig_token")
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
SECRET_NAME = "IG_ACCESS_TOKEN"
ALIAS_SECRET_NAME = "IG_TOKEN"


def refresh_long_lived_token(token: str, timeout: int = 30) -> dict[str, Any]:
    """Kembalikan dict {access_token, token_type, expires_in}. Token tidak dilog."""
    if not token:
        raise RuntimeError("IG_ACCESS_TOKEN kosong")
    r = requests.get(
        REFRESH_URL,
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = {"text_len": len(r.text or "")}
    if r.status_code >= 400 or not (isinstance(body, dict) and body.get("access_token")):
        err = body.get("error") if isinstance(body, dict) else {}
        msg = (err.get("message") if isinstance(err, dict) else None) or f"HTTP {r.status_code}"
        code = err.get("code") if isinstance(err, dict) else r.status_code
        raise RuntimeError(f"ig refresh gagal: {code} {msg}")
    return {
        "access_token": body["access_token"],
        "token_type": body.get("token_type") or "bearer",
        "expires_in": body.get("expires_in"),
    }


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
        # jaga-jaga kalau gh pernah memantulkan token
        err = err.replace(value, "***").replace(pat, "***")
        raise RuntimeError(f"gh secret set gagal: {err}")
    return "gh"


def run(settings: Settings | None = None, *, repo: str | None = None) -> dict[str, Any]:
    """Refresh token dan tulis ulang secret. Skip bersih jika prerequisite kurang."""
    s = settings or get_settings()
    token = s.ig_token
    pat = s.gh_pat or ""
    repo = repo or os.environ.get("GITHUB_REPOSITORY") or s.github_releases_repo or ""
    if not token:
        log.warning("Refresh IG dilewati: IG_ACCESS_TOKEN / IG_TOKEN belum diisi.")
        return {"ok": False, "reason": "ig_secrets_missing"}
    if not pat:
        log.warning("Refresh IG dilewati: GH_PAT belum diisi (wajib untuk menulis secret).")
        return {"ok": False, "reason": "gh_pat_missing"}
    if not repo:
        log.warning("Refresh IG dilewati: GITHUB_REPOSITORY belum diisi.")
        return {"ok": False, "reason": "repo_missing"}

    refreshed = refresh_long_lived_token(token)
    new_token = refreshed["access_token"]
    via = update_github_secret(SECRET_NAME, new_token, repo=repo, pat=pat)
    # jaga alias lama tetap selaras jika workflow lama masih merujuk IG_TOKEN
    try:
        update_github_secret(ALIAS_SECRET_NAME, new_token, repo=repo, pat=pat)
        alias = True
    except Exception as e:
        log.info("Alias IG_TOKEN tidak di-update: %s", type(e).__name__)
        alias = False
    expires_in = refreshed.get("expires_in")
    log.info(
        "IG_ACCESS_TOKEN diperbarui via %s; expires_in=%s detik; alias_IG_TOKEN=%s",
        via,
        expires_in,
        alias,
    )
    return {
        "ok": True,
        "via": via,
        "expires_in": expires_in,
        "alias_updated": alias,
        "token_len": len(new_token),
    }
