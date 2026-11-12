"""Kumpulkan topik dari banyak sumber gratis, gerbang safety, skor, shortlist."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from reels_autopilot.config import Settings, get_settings
from reels_autopilot.providers.llm import LLMClient
from reels_autopilot.providers.router import ProviderRouter
from reels_autopilot.state import State, today_wita

log = logging.getLogger("reels.scout")

# Bobot rubrik playbook 13.2 (usulan, ditandai TAMBAHAN di playbook)
WEIGHTS = {
    "curiosity_gap": 0.25,
    "niche_fit": 0.20,
    "trend_velocity": 0.20,
    "evergreen_vs_viral": 0.15,
    "bisa_stickman": 0.10,
    "safety": 0.10,
}
THRESHOLD = 65

SEEDS = [
    "cara pakai ai", "chatgpt", "ai gratis", "claude ai", "bikin video ai",
    "gemini google", "prompt chatgpt", "faceless content", "reels otomatis",
    "produktivitas ai",
]

NICHE_POS = re.compile(
    r"\b(ai|a\.i|chatgpt|gemini|claude|llm|teknologi|teknologi|aplikasi|kreator|"
    r"konten|produktivitas|prompt|otomatis|robot|coding|program|instagram|reels|"
    r"youtube|tiktok|penulis|tulisan|naskah|tts|video\s*ai|open.?source|software|"
    r"gawai|smartphone|algoritma|data|internet|startup|saas)\b",
    re.I,
)
NICHE_NEG = re.compile(
    r"\b(bola|ligue|liga\s+inggris|transfer\s+pemain|gosip|selingkuh|sinetron|"
    r"judol|judi\s*slot|togel|porn|dewasa)\b",
    re.I,
)
CURIOUS = re.compile(r"\b(kenapa|mengapa|bagaimana|kenapa|rahasia|ternyata|kok|mengapa|cara)\b", re.I)

# Gerbang safety — tolak sebelum LLM (playbook 13.2)
SAFETY_REJECT = [
    (r"\b(sara|rasis|pribumi|anti[\s-]?islam|anti[\s-]?kristen|anti[\s-]?yahudi|"
     r"genosida|etnis\s+tionghoa|hate\s*speech)\b", "SARA / politik identitas"),
    (r"\b(hoaks|hoax|konspirasi|rakyat harus tahu|dilarang tayang|fakta yang disembunyikan)\b",
     "indikasi hoaks / klaim tidak terverifikasi"),
    (r"\b(korban jiwa|meninggal dunia|tsunami|gempa bumi|tragedi|kecelakaan maut|"
     r"penembakan|teror)\b", "tragedi / berita duka — gerbang safety"),
    (r"\b(download film gratis|rekam bioskop|subtitle bajakan|crack\s+software|"
     r"nonton gratis 21)\b", "materi berhak cipta"),
    (r"\b(investasi dijamin|cuan pasti|profit dijamin|obat kanker|menyembuhkan|"
     r"kaya mendadak|trading sinyal pasti|tambah tinggi badan)\b",
     "janji kesehatan / keuangan"),
]

NEWS_FEEDS = [
    ("google_news_ai", "https://news.google.com/rss/search?q=kecerdasan+buatan+OR+ChatGPT+OR+Gemini+when:1d&hl=id&gl=ID&ceid=ID:id"),
    ("google_news_tech", "https://news.google.com/rss/search?q=teknologi+when:1d&hl=id&gl=ID&ceid=ID:id"),
    ("cnn_tekno", "https://www.cnnindonesia.com/teknologi/rss"),
    ("theverge", "https://www.theverge.com/rss/index.xml"),
    ("hn", "https://hnrss.org/frontpage"),
]
REDDIT_FEEDS = [
    ("reddit_chatgpt", "https://www.reddit.com/r/ChatGPT/.rss"),
    ("reddit_artificial", "https://www.reddit.com/r/artificial/.rss"),
    ("reddit_singularity", "https://www.reddit.com/r/singularity/.rss"),
    ("reddit_indonesia_tech", "https://www.reddit.com/r/indonesia/search.rss?q=AI+OR+ChatGPT&sort=new&restrict_sr=on"),
]
TRENDS_RSS = "https://trends.google.com/trending/rss?geo=ID"


def _get(url: str, settings: Settings, timeout: int = 15, **kw) -> requests.Response:
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", settings.http_user_agent)
    headers.setdefault("Accept", "application/rss+xml, application/xml, application/json, */*")
    return requests.get(url, headers=headers, timeout=timeout, **kw)


def safety_reason(judul: str) -> str | None:
    text = judul or ""
    for pat, reason in SAFETY_REJECT:
        if re.search(pat, text, flags=re.I):
            return reason
    return None


def heuristic_scores(item: dict, n_sources: int) -> dict:
    judul = item.get("judul") or ""
    pos = 8 if NICHE_POS.search(judul) else 3
    if NICHE_NEG.search(judul):
        pos = min(pos, 1)
    curiosity = 8 if CURIOUS.search(judul) else 5
    velocity = min(10, 4 + n_sources * 3)
    # evergreen default 7; viral (tren hari ini) 6 — seimbang
    ev = 6 if item.get("sumber") in {"google_trends_ID"} else 7
    stickman = 8 if pos >= 6 else 5
    safety = 8 if not safety_reason(judul) else 0
    return {
        "curiosity_gap": curiosity,
        "niche_fit": pos,
        "trend_velocity": velocity,
        "evergreen_vs_viral": ev,
        "bisa_stickman": stickman,
        "safety": safety,
    }


def total_score(skor: dict) -> float:
    return round(sum(skor.get(k, 0) * w for k, w in WEIGHTS.items()) * 10, 1)


class TopicScout:
    def __init__(self, settings: Settings | None = None, state: State | None = None):
        self.settings = settings or get_settings()
        self.state = state or State(self.settings)
        self.router = ProviderRouter(self.settings)
        self.llm = LLMClient(self.settings, self.router)

    def collect(self) -> tuple[list[dict], list[dict]]:
        """Ambil dari SEMUA sumber yang bisa; yang gagal dicatat, tidak menggagalkan yang lain."""
        raw: list[dict] = []
        errors: list[dict] = []
        sources = [
            ("google_trends_rss", self._trends),
            ("youtube_autocomplete", self._yt_auto),
            ("youtube_api", self._yt_popular),
            ("reddit_rss", self._reddit),
            ("news_rss", self._news),
            ("evergreen_bank", self._evergreen),
        ]
        callers_status = []
        for sid, fn in sources:
            try:
                items = fn()
                raw.extend(items)
                callers_status.append((sid, f"ok:{len(items)}"))
                self.router.status.success("topics", sid)
                log.info("Sumber %s: %s item", sid, len(items))
            except Exception as e:
                errors.append({"sumber": sid, "error": str(e)[:200]})
                self.router.status.failure("topics", sid, str(e), quota=False)
                log.warning("Sumber %s gagal: %s", sid, e)
        return raw, errors

    def run(self, *, use_llm: bool = True) -> dict:
        raw, errors = self.collect()
        raw = self._normalize_dedupe(raw)
        ditolak = []
        kandidat = []
        for item in raw:
            reason = safety_reason(item.get("judul") or "")
            if reason:
                ditolak.append({"judul": item.get("judul"), "alasan": reason, "tahap": "gerbang_safety"})
                continue
            if self.state.similar_past(item.get("judul") or ""):
                ditolak.append({"judul": item.get("judul"), "alasan": "sudah pernah dibuat (dedupe)", "tahap": "dedupe"})
                continue
            kandidat.append(item)

        shortlist: list[dict] = []
        provider = "heuristic"
        if use_llm and kandidat:
            try:
                shortlist, provider = self._llm_filter(kandidat, ditolak)
            except Exception as e:
                log.warning("LLM filter gagal (%s), pakai heuristik", e)
                shortlist, more = self._heuristic_filter(kandidat)
                ditolak.extend(more)
                provider = "heuristic"
        else:
            shortlist, more = self._heuristic_filter(kandidat)
            ditolak.extend(more)

        # pastikan cukup untuk DAILY_QUOTA: isi dari evergreen yang lolos
        if len(shortlist) < self.settings.daily_quota:
            extra, _ = self._heuristic_filter(
                [x for x in kandidat if x.get("sumber") == "evergreen_bank"
                 and not any(s.get("judul") == x.get("judul") for s in shortlist)]
            )
            for e in extra:
                if len(shortlist) >= max(self.settings.daily_quota, 8):
                    break
                shortlist.append(e)

        for i, s in enumerate(shortlist, 1):
            s["rank"] = i

        result = {
            "tanggal": today_wita(self.settings),
            "shortlist": shortlist[:10],
            "ditolak": ditolak[:50],
            "errors": errors,
            "raw_count": len(raw),
            "filter_provider": provider,
        }
        self.state.set_shortlist(result["shortlist"], result["ditolak"], result["tanggal"])
        cache = self.settings.cache_dir / f"shortlist_{result['tanggal']}.json"
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _normalize_dedupe(self, raw: list[dict]) -> list[dict]:
        # gabungkan sumber untuk judul mirip
        groups: list[dict] = []
        for item in raw:
            judul = (item.get("judul") or "").strip()
            if not judul or len(judul) < 6:
                continue
            found = None
            for g in groups:
                import difflib
                if difflib.SequenceMatcher(None, judul.lower(), g["judul"].lower()).ratio() > 0.8:
                    found = g
                    break
            if found:
                src = item.get("sumber")
                if src and src not in found["sumber_list"]:
                    found["sumber_list"].append(src)
                if item.get("sinyal") and not found.get("sinyal"):
                    found["sinyal"] = item.get("sinyal")
            else:
                groups.append({
                    "judul": judul,
                    "sumber": item.get("sumber"),
                    "sumber_list": [item.get("sumber")] if item.get("sumber") else [],
                    "sinyal": item.get("sinyal"),
                    "url": item.get("url"),
                    "tanggal": item.get("tanggal"),
                })
        return groups

    def _heuristic_filter(self, kandidat: list[dict]) -> tuple[list[dict], list[dict]]:
        scored, ditolak = [], []
        for item in kandidat:
            n = len(item.get("sumber_list") or [item.get("sumber")])
            skor = heuristic_scores(item, n)
            total = total_score(skor)
            if skor["safety"] == 0 or safety_reason(item["judul"]):
                ditolak.append({"judul": item["judul"], "alasan": safety_reason(item["judul"]) or "safety 0"})
                continue
            if NICHE_NEG.search(item["judul"]) and skor["niche_fit"] < 4:
                ditolak.append({"judul": item["judul"], "alasan": "di luar niche Kreator AI"})
                continue
            if total < THRESHOLD and item.get("sumber") != "evergreen_bank":
                ditolak.append({"judul": item["judul"], "alasan": f"skor {total} < {THRESHOLD}"})
                continue
            tipe = "viral" if item.get("sumber") == "google_trends_ID" else "evergreen"
            hook = item["judul"] if len(item["judul"].split()) <= 12 else " ".join(item["judul"].split()[:12])
            scored.append({
                "judul": item["judul"],
                "sumber": item.get("sumber_list") or [item.get("sumber")],
                "tipe": tipe,
                "kedaluwarsa_jam": 48 if tipe == "viral" else None,
                "skor": skor,
                "skor_total": total if total >= THRESHOLD else max(total, THRESHOLD if item.get("sumber") == "evergreen_bank" else total),
                "hook": hook.rstrip("?.!") + "?",
                "angle": f"Sudut kreator Indonesia: {item['judul']}",
                "beats": [
                    "Hook: taruh penonton di dalam pertanyaan.",
                    "Konflik: apa yang biasanya disalahpahami.",
                    "Payoff: satu langkah yang bisa langsung dicoba.",
                ],
                "fakta_yang_wajib_dicek": ["Jangan mengarang angka; cek klaim sebelum naskah final."],
                "angle_baru": False,
                "sinyal": item.get("sinyal"),
            })
        scored.sort(key=lambda x: x["skor_total"], reverse=True)
        # campur 60% evergreen / 40% viral (playbook)
        ev = [s for s in scored if s["tipe"] == "evergreen"]
        vi = [s for s in scored if s["tipe"] == "viral"]
        quota = max(self.settings.daily_quota, 8)
        n_vi = min(len(vi), max(1, round(quota * 0.4))) if vi else 0
        mixed = []
        # selang-seling, mulai evergreen
        i = j = 0
        while len(mixed) < quota and (i < len(ev) or j < len(vi)):
            take_v = j < n_vi and j < len(vi) and (len(mixed) % 5 == 2)
            if take_v:
                mixed.append(vi[j]); j += 1
            elif i < len(ev):
                mixed.append(ev[i]); i += 1
            elif j < len(vi):
                mixed.append(vi[j]); j += 1
            else:
                break
        return mixed, ditolak

    def _llm_filter(self, kandidat: list[dict], ditolak: list) -> tuple[list[dict], str]:
        prompt_path = self.settings.prompts_dir / "topic_filter.txt"
        system = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else _DEFAULT_FILTER_PROMPT
        past = [{"judul": p.get("judul"), "angle": p.get("angle")} for p in (self.state.data.get("past_topics") or [])][-80]
        user = json.dumps(
            {"RAW_TOPICS": kandidat[:60], "PAST_TOPICS": past, "PERFORMA": []},
            ensure_ascii=False,
        )
        data, provider = self.llm.generate_json(user, system=system)
        if provider == "template" or (isinstance(data, dict) and data.get("_template")):
            short, more = self._heuristic_filter(kandidat)
            ditolak.extend(more)
            return short, "template"
        short = data.get("shortlist") or []
        ditolak.extend(data.get("ditolak") or [])
        # gerbang safety lagi di sisi kita (jangan percaya LLM buta)
        clean = []
        for s in short:
            reason = safety_reason(s.get("judul") or "")
            if reason:
                ditolak.append({"judul": s.get("judul"), "alasan": reason, "tahap": "safety_setelah_llm"})
                continue
            if s.get("skor_total", 0) < THRESHOLD:
                continue
            clean.append(s)
        return clean, provider

    def _trends(self) -> list[dict]:
        r = _get(TRENDS_RSS, self.settings)
        r.raise_for_status()
        return _parse_rss(r.content, "google_trends_ID", traffic=True)

    def _yt_auto(self) -> list[dict]:
        out = []
        for seed in SEEDS:
            r = _get(
                "https://suggestqueries.google.com/complete/search",
                self.settings,
                params={"client": "firefox", "ds": "yt", "hl": "id", "q": seed},
            )
            r.raise_for_status()
            data = r.json()
            sugg = data[1] if isinstance(data, list) and len(data) > 1 else []
            for q in sugg:
                out.append({"judul": q, "sumber": "yt_autocomplete", "sinyal": seed})
        return out

    def _yt_popular(self) -> list[dict]:
        if not self.settings.youtube_api_key:
            return []
        r = _get(
            "https://www.googleapis.com/youtube/v3/videos",
            self.settings,
            params={
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": "ID",
                "videoCategoryId": "28",  # Science & Technology
                "maxResults": 10,
                "key": self.settings.youtube_api_key,
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(f"youtube API {r.status_code}: {r.text[:200]}")
        out = []
        for item in (r.json() or {}).get("items") or []:
            sn = item.get("snippet") or {}
            out.append({
                "judul": sn.get("title"),
                "sumber": "youtube_mostPopular_ID",
                "url": f"https://www.youtube.com/watch?v={item.get('id')}",
            })
        return out

    def _reddit(self) -> list[dict]:
        out = []
        for sid, url in REDDIT_FEEDS:
            try:
                r = _get(url, self.settings)
                r.raise_for_status()
                out.extend(_parse_rss(r.content, sid))
            except Exception as e:
                log.info("reddit %s: %s", sid, e)
        return out

    def _news(self) -> list[dict]:
        out = []
        for sid, url in NEWS_FEEDS:
            try:
                r = _get(url, self.settings)
                r.raise_for_status()
                out.extend(_parse_rss(r.content, sid))
            except Exception as e:
                log.info("news %s: %s", sid, e)
        return out

    def _evergreen(self) -> list[dict]:
        path = self.settings.data_dir / "evergreen_bank.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("topics") or []
        out = []
        for t in items:
            if isinstance(t, str):
                t = {"judul": t}
            t = dict(t)
            t["sumber"] = "evergreen_bank"
            out.append(t)
        return out


def _parse_rss(content: bytes, sumber: str, traffic: bool = False) -> list[dict]:
    try:
        # feedparser jika ada, else ElementTree
        try:
            import feedparser
            parsed = feedparser.parse(content)
            out = []
            for e in parsed.entries:
                item = {
                    "judul": e.get("title"),
                    "sumber": sumber,
                    "url": e.get("link"),
                    "tanggal": e.get("published") or e.get("updated"),
                }
                if traffic:
                    item["sinyal"] = e.get("ht_approx_traffic") or e.get("approx_traffic")
                out.append(item)
            if out:
                return out
        except ImportError:
            pass
        root = ET.fromstring(content)
        out = []
        ns = {"ht": "https://trends.google.com/trending/rss"}
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            link = item.findtext("link")
            approx = None
            if traffic:
                el = item.find("ht:approx_traffic", ns)
                if el is None:
                    for child in item:
                        if "approx_traffic" in child.tag:
                            approx = child.text
                else:
                    approx = el.text
            out.append({"judul": title, "sumber": sumber, "url": link, "sinyal": approx})
        return out
    except ET.ParseError as e:
        raise RuntimeError(f"RSS {sumber} tidak bisa diurai: {e}") from e


_DEFAULT_FILTER_PROMPT = """PERAN: Kamu "Kurator Topik" untuk kreator faceless "Po Chai" (Kreator AI + Penulis), FB & IG Reels berbahasa Indonesia santai, format explainer stickman 45–90 detik, 9:16.
TUGAS: gabungkan duplikat, buang yang mirip PAST_TOPICS, GERBANG SAFETY (SARA, hoaks, tragedi <7 hari, hak cipta, janji kesehatan/keuangan), skor sesuai rubrik, ambil 5–10 teratas skor_total >= 65.
OUTPUT: HANYA JSON valid dengan kunci tanggal, shortlist, ditolak. Jangan mengarang angka/fakta.
"""
