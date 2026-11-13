"""Rantai hosting URL publik untuk IG Reels: GitHub Releases → Cloudflare R2 → catbox.

IG Content Publishing API mewajibkan video_url yang bisa diunduh publik.
FB Page API bisa unggah biner langsung, jadi hosting hanya krusial untuk IG.
DRY_RUN tidak mengunggah apa pun.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from reels_autopilot.config import Settings, get_settings
from reels_autopilot.providers.router import ProviderRouter, QuotaExhausted, parse_retry_after

log = logging.getLogger("reels.hosting")
TIMEOUT = 120


@dataclass
class HostResult:
    public_url: str
    provider_id: str
    extra: dict | None = None


def _quota(provider_id: str, resp: requests.Response) -> None:
    if resp.status_code in {429, 402}:
        raise QuotaExhausted(
            provider_id,
            f"HTTP {resp.status_code}: {resp.text[:200]}",
            retry_after=parse_retry_after(resp.headers.get("Retry-After")),
        )


class HostingClient:
    def __init__(self, settings: Settings | None = None, router: ProviderRouter | None = None):
        self.settings = settings or get_settings()
        self.router = router or ProviderRouter(self.settings)

    def upload(self, path: Path, *, name: str | None = None) -> HostResult:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        name = name or path.name
        s = self.settings
        if s.dry_run:
            url = f"https://dry-run.local/{name}"
            log.info("DRY_RUN: lewati unggah, URL fiktif %s", url)
            dest = s.dry_run_dir / f"host_{name}.json"
            dest.write_text(f'{{"dry_run": true, "would_upload": "{path}", "as": "{name}"}}\n')
            return HostResult(url, "dry_run", {"path": str(path)})

        callers = {}
        if s.github_releases_repo and s.github_token:
            callers["github_release"] = lambda: self._github_release(path, name)
        if self._r2_ready():
            callers["r2"] = lambda: self._r2(path, name)
        callers["catbox"] = lambda: self._catbox(path, name)
        # hormati urutan VIDEO_HOST_CHAIN: router tetap pakai CHAINS, tapi skip yang
        # tidak di chain user
        allowed = set(s.video_host_chain)
        callers = {k: v for k, v in callers.items() if k in allowed or k == "catbox"}
        result = self.router.execute("hosting", callers)
        hr: HostResult = result.value
        hr.provider_id = hr.provider_id or result.provider_id
        return hr

    def _r2_ready(self) -> bool:
        s = self.settings
        return all([s.r2_account_id, s.r2_access_key_id, s.r2_secret_access_key, s.r2_bucket, s.r2_public_base_url])

    def _github_release(self, path: Path, name: str) -> HostResult:
        s = self.settings
        owner_repo = s.github_releases_repo.strip().strip("/")
        if "/" not in owner_repo:
            raise RuntimeError("GITHUB_RELEASES_REPO harus owner/nama")
        tag = f"reels-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        headers = {
            "Authorization": f"Bearer {s.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": s.http_user_agent,
        }
        api = f"https://api.github.com/repos/{owner_repo}/releases"
        # cari rilis hari ini, atau buat
        r = requests.get(f"{api}/tags/{tag}", headers=headers, timeout=30)
        if r.status_code == 404:
            r = requests.post(
                api,
                headers=headers,
                json={
                    "tag_name": tag,
                    "name": f"Reels {tag}",
                    "body": "MP4 sementara untuk Instagram Content Publishing API. Boleh dihapus setelah 48 jam.",
                    "draft": False,
                    "prerelease": False,
                },
                timeout=30,
            )
            _quota("github_release", r)
            r.raise_for_status()
            release = r.json()
        elif r.status_code >= 400:
            _quota("github_release", r)
            raise RuntimeError(f"github release GET {r.status_code}: {r.text[:200]}")
        else:
            release = r.json()
        upload_url = (release.get("upload_url") or "").split("{")[0]
        if not upload_url:
            raise RuntimeError("github release tanpa upload_url")
        # retry-safe: hapus aset lama bernama sama (sisa percobaan gagal sebelumnya)
        for a in release.get("assets") or []:
            if a.get("name") == name and a.get("url"):
                requests.delete(a["url"], headers=headers, timeout=30)
        with path.open("rb") as f:
            up = requests.post(
                upload_url,
                params={"name": name},
                headers={**headers, "Content-Type": "video/mp4"},
                data=f,
                timeout=TIMEOUT,
            )
        _quota("github_release", up)
        if up.status_code >= 400:
            raise RuntimeError(f"github asset upload {up.status_code}: {up.text[:200]}")
        data = up.json()
        url = data.get("browser_download_url") or ""
        if not url:
            raise RuntimeError("github asset tanpa browser_download_url")
        return HostResult(url, "github_release", {"tag": tag, "asset_id": data.get("id")})

    def _r2(self, path: Path, name: str) -> HostResult:
        """PUT S3-compatible ke Cloudflare R2 (SigV4), tanpa boto3."""
        s = self.settings
        key = f"reels/{datetime.now(timezone.utc).strftime('%Y%m%d')}/{name}"
        endpoint = s.r2_endpoint or f"https://{s.r2_account_id}.r2.cloudflarestorage.com"
        url = f"{endpoint.rstrip('/')}/{s.r2_bucket}/{quote(key)}"
        body = path.read_bytes()
        headers = _sigv4_headers(
            method="PUT",
            url=url,
            body=body,
            access_key=s.r2_access_key_id,
            secret_key=s.r2_secret_access_key,
            region="auto",
            service="s3",
            content_type="video/mp4",
        )
        r = requests.put(url, data=body, headers=headers, timeout=TIMEOUT)
        _quota("r2", r)
        if r.status_code >= 400:
            raise RuntimeError(f"R2 PUT {r.status_code}: {r.text[:200]}")
        public = s.r2_public_base_url.rstrip("/") + "/" + key
        return HostResult(public, "r2", {"key": key})

    def _catbox(self, path: Path, name: str) -> HostResult:
        with path.open("rb") as f:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (name, f, "video/mp4")},
                timeout=TIMEOUT,
                headers={"User-Agent": self.settings.http_user_agent},
            )
        _quota("catbox", r)
        if r.status_code >= 400 or not (r.text or "").startswith("http"):
            raise RuntimeError(f"catbox gagal {r.status_code}: {r.text[:200]}")
        return HostResult(r.text.strip(), "catbox")


def _sigv4_headers(
    *,
    method: str,
    url: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    content_type: str,
) -> dict:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_headers = f"content-type:{content_type}\nhost:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical = f"{method}\n{path}\n\n{canonical_headers}\n{signed}\n{payload_hash}"
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date = _sign(("AWS4" + secret_key).encode(), datestamp)
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed}, Signature={signature}"
    )
    return {
        "Content-Type": content_type,
        "Host": host,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
        "Authorization": auth,
    }
