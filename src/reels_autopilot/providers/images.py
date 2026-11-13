"""Rantai gambar stok resmi + gratis: Pexels → Pixabay → Unsplash → Openverse → Wikimedia → lokal.

Untuk Reels yang akan dimonetisasi, default hanya mengambil lisensi yang
memperbolehkan penggunaan komersial (CC0, PDM, CC BY tanpa SA/NC/ND,
lisensi resmi Pexels/Pixabay/Unsplash). CC BY-SA dilewati karena share-alike
berisiko untuk video komersial. Atribusi disimpan dan harus tampil di kredit/caption.
"""

from __future__ import annotations

import logging
import time
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

from reels_autopilot.config import COLOR_ACCENT, COLOR_BG, Settings, get_settings
from reels_autopilot.providers.router import ProviderRouter, QuotaExhausted, parse_retry_after

log = logging.getLogger("reels.images")
TIMEOUT = 25

# lisensi yang kami anggap aman untuk monetisasi (huruf kecil)
COMMERCIAL_OK = {
    "pexels", "pexels license", "pixabay", "pixabay license", "unsplash", "unsplash license",
    "cc0", "cc0 1.0", "pdm", "public domain", "pd", "cc-0",
    "cc by", "cc-by", "cc by 2.0", "cc by 3.0", "cc by 4.0", "cc-by-4.0", "cc-by-3.0",
    "cc by 2.5",
}
COMMERCIAL_BLOCK = {"sa", "nc", "nd", "sharealike", "noncommercial", "noderiv"}
_LOGO_RE = re.compile(r"\b(logo|wordmark|trademark|word mark|coat of arms|official seal|word-mark)\b", re.I)


def _ok_license(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    compact = n.replace("_", " ")
    for b in COMMERCIAL_BLOCK:
        if b in compact and "cc0" not in compact:
            # "cc by-sa" contains "sa" as sharealike — blok
            if b == "sa" and "share" not in compact and "by-sa" not in compact and "bysa" not in compact.replace("-", "").replace(" ", ""):
                # hindari false positive "usage" dll — 'sa' hanya jika by-sa
                if "by-sa" not in compact and "by sa" not in compact:
                    continue
            if b == "sa" and ("by-sa" in compact or "by sa" in compact or "sharealike" in compact):
                return False
            if b != "sa":
                return False
    for ok in COMMERCIAL_OK:
        if compact == ok or compact.startswith(ok + " ") or ok in compact:
            if "by-sa" in compact or "by sa" in compact:
                return False
            return True
    return False


def _quota(provider_id: str, resp: requests.Response) -> None:
    if resp.status_code in {429, 402}:
        raise QuotaExhausted(
            provider_id,
            f"HTTP {resp.status_code}: {resp.text[:200]}",
            retry_after=parse_retry_after(resp.headers.get("Retry-After")),
        )


@dataclass
class ImageResult:
    path: Path
    provider_id: str
    photographer: str = ""
    source_url: str = ""
    license: str = ""
    attribution: str = ""
    commercial_ok: bool = False
    query: str = ""


class ImageClient:
    def __init__(self, settings: Settings | None = None, router: ProviderRouter | None = None):
        self.settings = settings or get_settings()
        self.router = router or ProviderRouter(self.settings)

    def search(self, query: str, out_dir: Path, *, stem: str = "bg") -> ImageResult:
        """Cari 1 gambar potret. Jika semua stok gagal, buat latar lokal."""
        query = (query or "").strip() or "technology abstract dark"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{stem}.jpg"
        s = self.settings
        callers = {}
        if s.pexels_api_key and query:
            callers["pexels"] = lambda: self._pexels(query, dest)
        if s.pixabay_api_key and query:
            callers["pixabay"] = lambda: self._pixabay(query, dest)
        if s.unsplash_access_key and query:
            callers["unsplash"] = lambda: self._unsplash(query, dest)
        callers["openverse"] = lambda: self._openverse(query, dest)
        callers["wikimedia"] = lambda: self._wikimedia(query, dest)
        callers["local"] = lambda: self._local(query, dest)
        result = self.router.execute("images", callers)
        img: ImageResult = result.value
        img.provider_id = img.provider_id or result.provider_id
        img.query = query
        return img

    def search_commons(self, query: str, out_dir: Path, *, stem: str = "cutout") -> ImageResult:
        """Hanya Wikimedia Commons berlisensi bebas, dengan lisensi+pembuat tercatat.

        Tidak memakai Pexels/Pixabay/Unsplash/Openverse/web acak. Jika kosong, pemanggil
        harus jatuh ke ilustrasi buatan sendiri.
        """
        query = (query or "").strip()
        if not query:
            raise RuntimeError("wikimedia: kueri kosong")
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{stem}.jpg"
        return self._wikimedia(query, dest, skip_logos=True)

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": self.settings.http_user_agent, "Accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    def _download(self, url: str, dest: Path, headers: dict | None = None) -> Path:
        last = None
        for attempt in range(3):
            try:
                r = requests.get(url, headers=headers or self._headers(), timeout=TIMEOUT, stream=True)
                if r.status_code == 429:
                    wait = 3 * (attempt + 1)
                    log.info("unduhan Commons 429, tunggu %ss (percobaan %s)", wait, attempt + 1)
                    time.sleep(wait)
                    last = RuntimeError(f"HTTP 429: {url[:120]}")
                    continue
                r.raise_for_status()
                dest.write_bytes(r.content)
                if dest.stat().st_size < 500:
                    raise RuntimeError("gambar terlalu kecil / kosong")
                return dest
            except Exception as e:
                last = e
                log.info("unduhan gagal (%s): %s", type(e).__name__, e)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise last or RuntimeError("unduh gagal")

    def _pexels(self, query: str, dest: Path) -> ImageResult:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "portrait", "per_page": 5, "size": "large"},
            headers=self._headers({"Authorization": self.settings.pexels_api_key}),
            timeout=TIMEOUT,
        )
        _quota("pexels", r)
        r.raise_for_status()
        photos = (r.json() or {}).get("photos") or []
        if not photos:
            raise RuntimeError("pexels: tidak ada hasil")
        p = photos[0]
        src = (p.get("src") or {}).get("large2x") or (p.get("src") or {}).get("large") or p.get("url")
        self._download(src, dest, headers=self._headers({"Authorization": self.settings.pexels_api_key}))
        author = p.get("photographer") or ""
        page = p.get("url") or ""
        attr = f"Foto: {author} / Pexels" if author else "Foto: Pexels"
        return ImageResult(dest, "pexels", author, page, "Pexels License", attr, True)

    def _pixabay(self, query: str, dest: Path) -> ImageResult:
        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": self.settings.pixabay_api_key,
                "q": query,
                "image_type": "photo",
                "orientation": "vertical",
                "safesearch": "true",
                "per_page": 5,
            },
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        _quota("pixabay", r)
        r.raise_for_status()
        hits = (r.json() or {}).get("hits") or []
        if not hits:
            raise RuntimeError("pixabay: tidak ada hasil")
        h = hits[0]
        url = h.get("largeImageURL") or h.get("webformatURL")
        self._download(url, dest)
        author = h.get("user") or ""
        page = h.get("pageURL") or ""
        attr = f"Foto: {author} / Pixabay" if author else "Foto: Pixabay"
        return ImageResult(dest, "pixabay", author, page, "Pixabay License", attr, True)

    def _unsplash(self, query: str, dest: Path) -> ImageResult:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "orientation": "portrait", "per_page": 5},
            headers=self._headers({"Authorization": f"Client-ID {self.settings.unsplash_access_key}"}),
            timeout=TIMEOUT,
        )
        _quota("unsplash", r)
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        if not results:
            raise RuntimeError("unsplash: tidak ada hasil")
        p = results[0]
        url = (p.get("urls") or {}).get("regular") or (p.get("urls") or {}).get("full")
        self._download(url, dest)
        user = (p.get("user") or {})
        author = user.get("name") or user.get("username") or ""
        page = (p.get("links") or {}).get("html") or ""
        attr = f"Foto: {author} / Unsplash" if author else "Foto: Unsplash"
        return ImageResult(dest, "unsplash", author, page, "Unsplash License", attr, True)

    def _openverse(self, query: str, dest: Path) -> ImageResult:
        r = requests.get(
            "https://api.openverse.org/v1/images/",
            params={
                "q": query,
                "license_type": "commercial",
                "category": "photograph",
                "page_size": 8,
            },
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        _quota("openverse", r)
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
        for item in results:
            lic = (item.get("license") or "") + " " + (item.get("license_version") or "")
            if not _ok_license(lic) and not _ok_license(item.get("license") or ""):
                continue
            url = item.get("url") or (item.get("thumbnail") or "")
            if not url:
                continue
            try:
                self._download(url, dest)
            except Exception:
                continue
            author = item.get("creator") or ""
            page = item.get("foreign_landing_url") or item.get("attribution") or ""
            attr = item.get("attribution") or (f"{author} — {lic}".strip(" —"))
            return ImageResult(dest, "openverse", author, page, lic.strip(), attr, True)
        raise RuntimeError("openverse: tidak ada hasil berlisensi komersial")

    def _wikimedia(self, query: str, dest: Path, *, skip_logos: bool = False) -> ImageResult:
        # API resmi Commons; User-Agent deskriptif wajib menurut kebijakan Wikimedia
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,  # File
            "gsrlimit": 24,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime|size",
            "iiurlwidth": 1200,
        }
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        _quota("wikimedia", r)
        r.raise_for_status()
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = str(page.get("title") or "")
            if skip_logos and _LOGO_RE.search(title):
                log.info("wikimedia lewati logo: %s", title)
                continue
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = (info.get("mime") or "")
            if not mime.startswith("image/") or "svg" in mime:
                continue
            if any(x in mime for x in ("tiff", "tif")) and not info.get("thumburl"):
                continue
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value") or (meta.get("License") or {}).get("value") or ""
            if not _ok_license(lic):
                log.info("wikimedia lewati lisensi '%s'", lic)
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            try:
                self._download(url, dest)
            except Exception:
                continue
            artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "")
            page_url = page.get("title") or info.get("descriptionurl") or ""
            attr = f"{artist.strip()} / Wikimedia Commons ({lic})".strip(" /")
            return ImageResult(dest, "wikimedia", artist.strip(), str(page_url), lic, attr, True)
        raise RuntimeError("wikimedia: tidak ada berkas berlisensi komersial yang cocok")

    def _local(self, query: str, dest: Path) -> ImageResult:
        """Latar abstrak bermerek — selalu berhasil, tanpa lisensi pihak ketiga."""
        img = Image.new("RGB", (1080, 1920), COLOR_BG)
        dr = ImageDraw.Draw(img, "RGBA")
        # blob aksen
        for cx, cy, r, col in [
            (200, 300, 280, (242, 140, 40, 40)),
            (900, 1600, 340, (40, 90, 140, 50)),
            (540, 960, 200, (242, 140, 40, 22)),
        ]:
            dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        dest_path = dest.with_suffix(".png")
        img.save(dest_path, "PNG")
        return ImageResult(dest_path, "local", "Po Chai", "", "original", "", True, query)
