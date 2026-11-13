"""Konfigurasi affiliate opsional. Kosong secara default — bro yang mengatur isinya.

Tautan tidak disisipkan ke caption kecuali kelak `insert_url: true` (default false).
CTA khas: "Cek link di bio."
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from reels_autopilot.caption_guard import public_caption_issues
from reels_autopilot.config import Settings, get_settings

log = logging.getLogger("reels.affiliate")

_DEFAULT_CTA = "Cek link di bio."


@dataclass
class AffiliateProduct:
    id: str = ""
    keywords: list[str] = field(default_factory=list)
    cta: str = ""
    url: str = ""
    topics: list[str] = field(default_factory=list)


@dataclass
class AffiliateConfig:
    enabled: bool = False
    cta_default: str = _DEFAULT_CTA
    insert_url: bool = False
    products: list[AffiliateProduct] = field(default_factory=list)
    path: Path | None = None
    raw_ok: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.enabled and self.products)


def affiliate_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.root / "config" / "affiliate.yaml"


def _parse_scalar(raw: str):
    v = raw.strip()
    if v[:1] in {"'", '"'} and v[-1:] == v[:1] and len(v) >= 2:
        return v[1:-1]
    low = v.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if low in {"null", "none", "~", ""}:
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [str(_parse_scalar(x.strip())).strip() for x in inner.split(",") if x.strip()]
    return v


def _parse_simple_yaml(text: str) -> dict:
    """Parser YAML subset untuk berkas affiliate (kunci, bool, string, list produk)."""
    root: dict = {}
    products: list[dict] = []
    current: dict | None = None
    mode = None  # None | products
    for raw in (text or "").splitlines():
        if re.match(r"^\s*#", raw) or not raw.strip():
            continue
        line = raw.rstrip()
        # item list
        m_item = re.match(r"^(\s*)-\s+(.*)$", line)
        if m_item:
            rest = m_item.group(2).strip()
            current = {}
            products.append(current)
            if rest and ":" in rest:
                k, _, val = rest.partition(":")
                current[k.strip()] = _parse_scalar(val)
            mode = "products"
            continue
        m_key = re.match(r"^(\s*)([A-Za-z_][\w]*)\s*:\s*(.*)$", line)
        if not m_key:
            continue
        indent, key, val = m_key.group(1), m_key.group(2), m_key.group(3)
        if not indent:
            current = None
            if key == "products":
                mode = "products"
                if val.strip() and val.strip() != "[]":
                    pass
                elif val.strip() == "[]":
                    products = []
                    mode = None
                continue
            root[key] = _parse_scalar(val) if val.strip() else (None if val == "" else val)
            mode = None
        elif current is not None and mode == "products":
            current[key] = _parse_scalar(val)
    if products or mode == "products":
        root["products"] = products
    return root


def load_affiliate(path: Path | None = None, settings: Settings | None = None) -> AffiliateConfig:
    path = Path(path) if path else affiliate_path(settings)
    cfg = AffiliateConfig(path=path)
    if not path.exists():
        return cfg
    try:
        text = path.read_text(encoding="utf-8")
        data = _parse_simple_yaml(text)
    except Exception as e:
        log.warning("affiliate.yaml tidak bisa dibaca: %s", e)
        cfg.raw_ok = False
        cfg.errors.append(str(e)[:200])
        return cfg
    cfg.enabled = bool(data.get("enabled") or False)
    cta = data.get("cta_default")
    if isinstance(cta, str) and cta.strip():
        cfg.cta_default = cta.strip()
    cfg.insert_url = bool(data.get("insert_url") or False)
    products = data.get("products") or []
    if isinstance(products, list):
        for p in products:
            if not isinstance(p, dict):
                continue
            kws = p.get("keywords") or []
            if isinstance(kws, str):
                kws = [k.strip() for k in kws.split(",") if k.strip()]
            tops = p.get("topics") or []
            if isinstance(tops, str):
                tops = [k.strip() for k in tops.split(",") if k.strip()]
            cfg.products.append(
                AffiliateProduct(
                    id=str(p.get("id") or ""),
                    keywords=[str(k).lower() for k in kws if k],
                    cta=str(p.get("cta") or "").strip(),
                    url=str(p.get("url") or "").strip(),
                    topics=[str(t).lower() for t in tops if t],
                )
            )
    return cfg


def match_product(cfg: AffiliateConfig, topic: dict | None, script: dict | None = None) -> AffiliateProduct | None:
    if not cfg.active:
        return None
    parts = []
    for src in (topic, script):
        if isinstance(src, dict):
            parts.extend([
                src.get("judul") or "",
                src.get("hook") or "",
                src.get("angle") or "",
                src.get("narasi_penuh") or "",
                " ".join(src.get("hashtag") or []) if isinstance(src.get("hashtag"), list) else "",
            ])
    blob = " ".join(str(p) for p in parts).lower()
    best: tuple[int, AffiliateProduct] | None = None
    for prod in cfg.products:
        score = 0
        for kw in prod.keywords:
            if kw and kw in blob:
                score += max(1, len(kw.split()))
        for t in prod.topics:
            if t and t in blob:
                score += 1
        if score and (best is None or score > best[0]):
            best = (score, prod)
    return best[1] if best else None


def apply_affiliate_cta(
    caption: str,
    topic: dict | None = None,
    script: dict | None = None,
    *,
    config: AffiliateConfig | None = None,
    settings: Settings | None = None,
) -> str:
    """Sisipkan CTA affiliate jika konfigurasi aktif dan topik cocok. Tanpa tautan secara default."""
    text = caption or ""
    cfg = config if config is not None else load_affiliate(settings=settings)
    if not cfg.active:
        return text
    prod = match_product(cfg, topic, script)
    if not prod:
        return text
    cta = (prod.cta or cfg.cta_default or _DEFAULT_CTA).strip()
    if not cta:
        return text
    # Jangan sisipkan URL ke caption (kebijakan default; bro yang atur jika suatu saat mau).
    if cfg.insert_url and prod.url:
        # tetap tidak otomatis menempel URL mentah di caption publik kecuali diizinkan —
        # dan tugas ini meminta "no links now".
        pass
    low = text.lower()
    if cta.lower() in low or "cek link di bio" in low or "cek tautan di bio" in low:
        return text
    new = text.rstrip() + "\n\n" + cta
    if public_caption_issues(new):
        log.warning("CTA affiliate ditolak karena bocor instruksi internal")
        return text
    return new
