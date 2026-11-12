"""State persisten: topik yang sudah dipakai, antrian harian, offset Telegram, pause."""

from __future__ import annotations

import json
import logging
import difflib
from datetime import datetime
from pathlib import Path
from typing import Any

from reels_autopilot.config import WITA, Settings, get_settings

log = logging.getLogger("reels.state")


def today_wita(settings: Settings | None = None) -> str:
    tz = (settings or get_settings()).tz
    return datetime.now(tz).strftime("%Y-%m-%d")


def _now_iso(settings: Settings | None = None) -> str:
    tz = (settings or get_settings()).tz
    return datetime.now(tz).isoformat(timespec="seconds")


class State:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.path = self.settings.state_path
        self.data: dict[str, Any] = {
            "past_topics": [],
            "days": {},
            "telegram": {"last_update_id": 0, "chat_id": self.settings.telegram_chat_id},
            "paused": False,
            "paused_until": None,
        }
        self.load()
        self._merge_past_topics_file()

    def load(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("state rusak, mulai baru: %s", e)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        # cermin past_topics agar mudah dibaca / di-commit terpisah
        past_path = self.settings.past_topics_path
        past_path.write_text(
            json.dumps(self.data.get("past_topics") or [], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _merge_past_topics_file(self) -> None:
        p = self.settings.past_topics_path
        if not p.exists():
            return
        try:
            extra = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(extra, list):
            return
        have = {(x.get("judul") or "").lower() for x in self.data.get("past_topics") or [] if isinstance(x, dict)}
        for item in extra:
            if isinstance(item, str):
                item = {"judul": item}
            judul = (item.get("judul") or "").lower()
            if judul and judul not in have:
                self.data.setdefault("past_topics", []).append(item)
                have.add(judul)

    def is_paused(self) -> bool:
        if not self.data.get("paused"):
            return False
        until = self.data.get("paused_until")
        if until:
            try:
                if datetime.now(self.settings.tz) >= datetime.fromisoformat(until):
                    self.data["paused"] = False
                    self.data["paused_until"] = None
                    self.save()
                    return False
            except ValueError:
                pass
        return True

    def pause(self, until_iso: str | None = None) -> None:
        self.data["paused"] = True
        self.data["paused_until"] = until_iso
        self.save()

    def resume(self) -> None:
        self.data["paused"] = False
        self.data["paused_until"] = None
        self.save()

    def similar_past(self, judul: str, threshold: float = 0.8) -> dict | None:
        judul_n = (judul or "").strip().lower()
        if not judul_n:
            return None
        for item in self.data.get("past_topics") or []:
            other = (item.get("judul") if isinstance(item, dict) else str(item)) or ""
            if difflib.SequenceMatcher(None, judul_n, other.lower()).ratio() >= threshold:
                return item if isinstance(item, dict) else {"judul": other}
        return None

    def add_past_topic(self, judul: str, **extra: Any) -> None:
        if self.similar_past(judul, 0.92):
            return
        entry = {"judul": judul, "tanggal": today_wita(self.settings), **extra}
        self.data.setdefault("past_topics", []).append(entry)
        self.save()

    def day(self, date: str | None = None) -> dict:
        date = date or today_wita(self.settings)
        days = self.data.setdefault("days", {})
        if date not in days:
            days[date] = {
                "date": date,
                "shortlist": [],
                "ditolak": [],
                "videos": [],
                "scouted_at": None,
                "notified": False,
            }
        return days[date]

    def set_shortlist(self, shortlist: list, ditolak: list | None = None, date: str | None = None) -> None:
        d = self.day(date)
        d["shortlist"] = shortlist
        d["ditolak"] = ditolak or d.get("ditolak") or []
        d["scouted_at"] = _now_iso(self.settings)
        self.save()

    def videos(self, date: str | None = None) -> list[dict]:
        return self.day(date).setdefault("videos", [])

    def upsert_video(self, video: dict, date: str | None = None) -> dict:
        vids = self.videos(date)
        vid = video.get("id")
        for i, existing in enumerate(vids):
            if existing.get("id") == vid:
                existing.update(video)
                self.save()
                return existing
        vids.append(video)
        self.save()
        return video

    def video_by_slot(self, slot: int, date: str | None = None) -> dict | None:
        for v in self.videos(date):
            if v.get("slot") == slot:
                return v
        return None

    def video_by_id(self, vid: str, date: str | None = None) -> dict | None:
        for v in self.videos(date):
            if v.get("id") == vid:
                return v
        return None

    def telegram_offset(self) -> int:
        return int((self.data.get("telegram") or {}).get("last_update_id") or 0)

    def set_telegram_offset(self, update_id: int) -> None:
        self.data.setdefault("telegram", {})["last_update_id"] = update_id
        self.save()

    def set_chat_id(self, chat_id: str | int) -> None:
        self.data.setdefault("telegram", {})["chat_id"] = str(chat_id)
        self.save()
