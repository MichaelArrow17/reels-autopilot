"""Publish Reels ke Instagram (utama) dan opsional ke Facebook Page.

Jalur utama: Graph API IG (host lewat IG_GRAPH_HOST, default graph.facebook.com,
versi v21.0) — container REELS lalu media_publish. Wajib video_url publik
(HostingClient). Profil Facebook menerima Reel lewat auto-share IG, bukan
Graph ke profil. Permalink media diambil setelah media_publish (untuk Telegram).

Facebook Page (graph.facebook.com video_reels) bersifat opsional: hanya
dijalankan jika FB_PAGE_ID + FB_PAGE_TOKEN diisi.

Default DRY_RUN=true: tidak memanggil API, hanya menulis payload (token disensor).
Secret IG yang belum diisi → skip dengan log jelas, bukan exception.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings
from reels_autopilot.providers.hosting import HostingClient
from reels_autopilot.providers.router import QuotaExhausted, parse_retry_after

log = logging.getLogger("reels.publish")


def _redact(d: Any) -> Any:
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if any(s in k.lower() for s in ("token", "secret", "authorization", "password", "key")):
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(d, list):
        return [_redact(x) for x in d]
    return d


class Publisher:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.host = HostingClient(self.settings)

    def publish(
        self,
        mp4: Path,
        *,
        caption: str,
        when_unix: int | None = None,
        video_state: str = "PUBLISHED",
        dest_fb: bool | None = None,
        dest_ig: bool = True,
        public_url: str | None = None,
    ) -> dict:
        s = self.settings
        # FB Page opsional: default on hanya jika secret-nya ada.
        if dest_fb is None:
            dest_fb = s.fb_configured
        result: dict[str, Any] = {
            "dry_run": s.dry_run,
            "fb": None,
            "ig": None,
            "host": None,
            "caption": caption,
            "mp4": str(mp4),
        }
        if s.dry_run:
            payload = {
                "would_do": {
                    "fb_page": dest_fb,
                    "ig": dest_ig,
                    "api": s.ig_graph_base,
                    "video_state": video_state if not when_unix else "SCHEDULED",
                    "scheduled_publish_time": when_unix,
                    "page_id": s.fb_page_id or "(opsional, belum diisi)",
                    "ig_user_id": s.ig_user_id or "(belum diisi)",
                    "is_ai_generated": s.fb_is_ai_generated,
                    "note": (
                        "Target utama: Instagram Reels via Graph API "
                        f"({s.ig_graph_base}). "
                        "Profil Facebook menerima lewat auto-share IG "
                        "(cek FB Po Chai; API tidak bisa memverifikasi). "
                        "Publish ke Facebook Page bersifat opsional."
                    ),
                },
                "caption": caption,
                "mp4": str(mp4),
                "size": mp4.stat().st_size if mp4.exists() else 0,
            }
            out = s.dry_run_dir / f"publish_{Path(mp4).stem}.json"
            out.write_text(json.dumps(_redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")
            result["dry_run_path"] = str(out)
            log.info("DRY_RUN publish tertulis di %s", out)
            return result

        missing_fb = dest_fb and not s.fb_configured
        missing_ig = dest_ig and not s.ig_configured
        if missing_fb:
            log.warning("Publish FB Page dilewati: FB_PAGE_ID / FB_PAGE_TOKEN belum diisi (opsional).")
            result["fb"] = {"skipped": True, "reason": "missing_fb_secrets"}
            dest_fb = False
        if missing_ig:
            log.warning(
                "Publish IG dilewati: IG_USER_ID / IG_ACCESS_TOKEN belum diisi. "
                "Video tidak diunggah ke Instagram."
            )
            result["ig"] = {"skipped": True, "reason": "missing_ig_secrets"}
            result["skipped"] = True
            result["reason"] = "ig_secrets_missing"
            # IG adalah target utama — jangan lanjut FB-only sebagai pengganti.
            dest_ig = False
            dest_fb = False
            return result

        if dest_fb:
            result["fb"] = self.fb_reel(mp4, caption, when_unix=when_unix, video_state=video_state)
        if dest_ig:
            if not public_url:
                hosted = self.host.upload(mp4, name=Path(mp4).name)
                result["host"] = {"provider": hosted.provider_id, "url": hosted.public_url}
                public_url = hosted.public_url
            result["ig"] = self.ig_reel(public_url, caption)
        return result

    def fb_reel(
        self,
        path: Path,
        caption: str,
        *,
        when_unix: int | None = None,
        video_state: str = "PUBLISHED",
    ) -> dict:
        """3 fase resmi: start → rupload → finish. Hanya untuk PAGE."""
        s = self.settings
        if not s.fb_page_id or not s.fb_page_token:
            raise RuntimeError("FB_PAGE_ID / FB_PAGE_TOKEN belum diisi")
        g = s.graph_base
        start = requests.post(
            f"{g}/{s.fb_page_id}/video_reels",
            data={"upload_phase": "start", "access_token": s.fb_page_token},
            timeout=60,
        )
        _meta_err("fb", start)
        start_j = start.json()
        vid = start_j.get("video_id")
        if not vid:
            raise RuntimeError(f"fb start tanpa video_id: {start_j}")
        size = Path(path).stat().st_size
        with Path(path).open("rb") as f:
            up = requests.post(
                f"https://rupload.facebook.com/video-upload/{s.meta_graph_version}/{vid}",
                headers={
                    "Authorization": f"OAuth {s.fb_page_token}",
                    "offset": "0",
                    "file_size": str(size),
                },
                data=f,
                timeout=300,
            )
        up.raise_for_status()
        d: dict[str, Any] = {
            "upload_phase": "finish",
            "video_id": vid,
            "description": caption,
            "access_token": s.fb_page_token,
            "is_ai_generated": "true" if s.fb_is_ai_generated else "false",
        }
        if when_unix:
            d["video_state"] = "SCHEDULED"
            d["scheduled_publish_time"] = str(when_unix)
        else:
            d["video_state"] = video_state
        fin = requests.post(f"{g}/{s.fb_page_id}/video_reels", data=d, timeout=60)
        _meta_err("fb", fin)
        return fin.json()

    def ig_reel(self, public_video_url: str, caption: str) -> dict:
        """Container REELS → poll FINISHED → media_publish → ambil permalink.

        Host: IG_GRAPH_HOST (default graph.facebook.com) / v21.0.
        Tidak ada parameter jadwal — panggil tepat di jam tayang.
        video_url harus publik (GitHub Releases / R2 / catbox).
        """
        s = self.settings
        if not s.ig_configured:
            raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN belum diisi")
        g = s.ig_graph_base
        c = requests.post(
            f"{g}/{s.ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": public_video_url,
                "caption": caption,
                "access_token": s.ig_token,
                "share_to_feed": "true",
            },
            timeout=60,
        )
        _meta_err("ig", c)
        cid = (c.json() or {}).get("id")
        if not cid:
            raise RuntimeError(f"ig media tanpa id: {c.text[:300]}")
        for _ in range(10):
            st = requests.get(
                f"{g}/{cid}",
                params={"fields": "status_code,status", "access_token": s.ig_token},
                timeout=30,
            )
            _meta_err("ig", st)
            code = (st.json() or {}).get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError(f"ig container ERROR: {st.text[:300]}")
            time.sleep(60)
        else:
            raise RuntimeError("ig container belum FINISHED dalam ~10 menit")
        pub = requests.post(
            f"{g}/{s.ig_user_id}/media_publish",
            data={"creation_id": cid, "access_token": s.ig_token},
            timeout=60,
        )
        _meta_err("ig", pub)
        body = pub.json() or {}
        media_id = body.get("id")
        if media_id:
            permalink = _fetch_permalink(g, media_id, s.ig_token)
            if permalink:
                body["permalink"] = permalink
        return body


def _fetch_permalink(graph_base: str, media_id: str, token: str) -> str | None:
    """Ambil permalink media. Gagal tidak menggagalkan publish."""
    try:
        info = requests.get(
            f"{graph_base}/{media_id}",
            params={"fields": "permalink,id", "access_token": token},
            timeout=30,
        )
        if info.status_code >= 400:
            log.warning("permalink IG tidak tersedia (HTTP %s)", info.status_code)
            return None
        return (info.json() or {}).get("permalink")
    except Exception as e:
        log.warning("permalink IG gagal diambil: %s", type(e).__name__)
        return None


def _meta_err(provider: str, resp: requests.Response) -> None:
    if resp.status_code in {429, 400, 403, 17} or resp.status_code >= 400:
        try:
            body = resp.json()
        except Exception:
            body = {"text": resp.text[:400]}
        err = (body.get("error") or body) if isinstance(body, dict) else {}
        code = err.get("code") if isinstance(err, dict) else None
        msg = err.get("message") if isinstance(err, dict) else str(body)
        # kode Meta yang sering berarti rate/quota: 4, 17, 32, 80004
        if resp.status_code == 429 or code in {4, 17, 32, 80004}:
            raise QuotaExhausted(provider, f"{code}: {msg}", parse_retry_after(resp.headers.get("Retry-After")))
        if resp.status_code >= 400:
            raise RuntimeError(f"{provider} HTTP {resp.status_code}: {msg}")
