"""Router failover: coba rantai provider, cooldown saat kuota habis, balik ke primer setelah reset."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from reels_autopilot.config import PACIFIC, Settings, get_settings
from reels_autopilot.providers.catalog import CHAINS, provider_meta

log = logging.getLogger("reels.router")

QUOTA_RE = re.compile(
    r"RESOURCE_EXHAUSTED|quotaExceeded|insufficient[_\s-]?quota|"
    r"rate[_-]?limit|too many requests|credits?\s+(exceeded|exhausted)|"
    r"exceeded your (current )?quota|usage limit",
    re.I,
)


class QuotaExhausted(Exception):
    def __init__(self, provider_id: str, message: str, retry_after: datetime | None = None):
        super().__init__(message)
        self.provider_id = provider_id
        self.retry_after = retry_after


class AllProvidersFailed(Exception):
    def __init__(self, category: str, errors: list[tuple[str, str]]):
        self.category = category
        self.errors = errors
        detail = "; ".join(f"{p}: {e}" for p, e in errors) or "no provider"
        super().__init__(f"Semua provider '{category}' gagal ({detail})")


@dataclass
class ProviderRecord:
    category: str
    provider_id: str
    consecutive_failures: int = 0
    last_error: str | None = None
    last_error_at: str | None = None
    last_success_at: str | None = None
    cooldown_until: str | None = None
    quota_exhausted: bool = False
    quota_reset_at: str | None = None
    success_count: int = 0
    failure_count: int = 0


@dataclass
class CallResult:
    category: str
    provider_id: str
    value: Any
    tried: list[tuple[str, str]] = field(default_factory=list)
    # tried = providers that were skipped or failed, (id, reason)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def next_pacific_midnight(now: datetime | None = None) -> datetime:
    now = now or _now()
    local = now.astimezone(PACIFIC)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(timezone.utc)


def default_reset_at(category: str, provider_id: str, retry_after: datetime | None = None) -> datetime:
    if retry_after is not None:
        return retry_after
    meta = provider_meta(category, provider_id) or {}
    kind = meta.get("reset") or "unknown"
    now = _now()
    if kind == "pacific_midnight":
        return next_pacific_midnight(now)
    if kind == "hourly":
        return now + timedelta(hours=1)
    if kind == "monthly_billing":
        # perkiraan: awal bulan berikutnya UTC — bukan jaminan siklus GitHub/CF
        if now.month == 12:
            nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=5, second=0, microsecond=0)
        else:
            nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=5, second=0, microsecond=0)
        return nxt
    if kind == "rolling_24h":
        return now + timedelta(hours=24)
    # unknown: coba lagi dalam 45 menit; kalau masih gagal, akan diperpanjang
    return now + timedelta(minutes=45)


def looks_like_quota(exc: BaseException, status_code: int | None = None) -> bool:
    if isinstance(exc, QuotaExhausted):
        return True
    if status_code in {429, 402}:
        return True
    return bool(QUOTA_RE.search(str(exc)))


def parse_retry_after(header: str | None) -> datetime | None:
    if not header:
        return None
    header = header.strip()
    try:
        seconds = int(header)
        return _now() + timedelta(seconds=max(1, seconds))
    except ValueError:
        pass
    try:
        # RFC 7231 HTTP-date — coba fromisoformat / email.utils
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(header)
    except Exception:
        return None


class ProviderStatusStore:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, ProviderRecord] = {}
        self.load()

    def _key(self, category: str, provider_id: str) -> str:
        return f"{category}:{provider_id}"

    def load(self) -> None:
        self._data = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for key, val in (raw.get("providers") or {}).items():
            try:
                self._data[key] = ProviderRecord(**val)
            except TypeError:
                continue

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _iso(_now()),
            "providers": {k: asdict(v) for k, v in self._data.items()},
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, category: str, provider_id: str) -> ProviderRecord:
        key = self._key(category, provider_id)
        rec = self._data.get(key)
        if rec is None:
            rec = ProviderRecord(category=category, provider_id=provider_id)
            self._data[key] = rec
        return rec

    def is_cooling(self, category: str, provider_id: str, now: datetime | None = None) -> bool:
        now = now or _now()
        rec = self.get(category, provider_id)
        until = _parse(rec.cooldown_until) or _parse(rec.quota_reset_at)
        if until is None:
            return False
        if now >= until:
            # reset selesai: buka lagi (primer akan dicoba lebih dulu)
            rec.cooldown_until = None
            rec.quota_exhausted = False
            rec.quota_reset_at = None
            rec.consecutive_failures = 0
            self.save()
            log.info("Cooldown %s/%s selesai, dicoba lagi sebagai primer rantai", category, provider_id)
            return False
        return True

    def cooldown_remaining(self, category: str, provider_id: str) -> timedelta | None:
        rec = self.get(category, provider_id)
        until = _parse(rec.cooldown_until) or _parse(rec.quota_reset_at)
        if not until:
            return None
        delta = until - _now()
        return delta if delta.total_seconds() > 0 else None

    def success(self, category: str, provider_id: str) -> None:
        rec = self.get(category, provider_id)
        rec.last_success_at = _iso(_now())
        rec.consecutive_failures = 0
        rec.last_error = None
        rec.quota_exhausted = False
        rec.cooldown_until = None
        rec.quota_reset_at = None
        rec.success_count += 1
        self.save()

    def failure(
        self,
        category: str,
        provider_id: str,
        error: str,
        *,
        quota: bool = False,
        retry_after: datetime | None = None,
    ) -> None:
        rec = self.get(category, provider_id)
        rec.last_error = error[:500]
        rec.last_error_at = _iso(_now())
        rec.consecutive_failures += 1
        rec.failure_count += 1
        if quota:
            reset = default_reset_at(category, provider_id, retry_after)
            rec.quota_exhausted = True
            rec.quota_reset_at = _iso(reset)
            rec.cooldown_until = _iso(reset)
            log.warning(
                "Kuota %s/%s habis atau rate-limit. Cooldown sampai %s WITA.",
                category,
                provider_id,
                reset.astimezone(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M"),
            )
        else:
            # error biasa: cooldown pendek, semakin lama jika beruntun
            minutes = min(60, 5 * (2 ** min(rec.consecutive_failures - 1, 4)))
            until = _now() + timedelta(minutes=minutes)
            rec.cooldown_until = _iso(until)
        self.save()

    def snapshot(self) -> list[dict]:
        out = []
        for rec in self._data.values():
            d = asdict(rec)
            d["cooling"] = self.is_cooling(rec.category, rec.provider_id)
            rem = self.cooldown_remaining(rec.category, rec.provider_id)
            d["cooldown_remaining_min"] = round(rem.total_seconds() / 60, 1) if rem else 0
            out.append(d)
        return out


class ProviderRouter:
    """Coba provider sesuai urutan rantai. Yang sedang cooldown dilewati.
    Setelah waktu reset, provider primer dicoba lagi lebih dulu.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.status = ProviderStatusStore(self.settings.provider_status_path)

    def chain(self, category: str) -> list[str]:
        return list(CHAINS.get(category, []))

    def execute(
        self,
        category: str,
        callers: dict[str, Callable[[], Any]],
        *,
        skip: set[str] | None = None,
    ) -> CallResult:
        """callers: peta id provider -> callable tanpa argumen yang melempar
        QuotaExhausted atau Exception biasa. Yang tidak ada di callers dilewati.
        """
        skip = skip or set()
        tried: list[tuple[str, str]] = []
        order = self.chain(category)
        # tetap urutan primer → cadangan (jangan rotasi), agar setelah reset primer dipakai lagi
        for pid in order:
            if pid in skip:
                tried.append((pid, "skipped"))
                continue
            if pid not in callers:
                tried.append((pid, "not_implemented"))
                continue
            if self.status.is_cooling(category, pid):
                rem = self.status.cooldown_remaining(category, pid)
                mins = round(rem.total_seconds() / 60, 1) if rem else 0
                tried.append((pid, f"cooldown ~{mins} menit"))
                log.info("Lewati %s/%s (cooldown ~%s menit)", category, pid, mins)
                continue
            try:
                value = callers[pid]()
            except QuotaExhausted as e:
                self.status.failure(category, pid, str(e), quota=True, retry_after=e.retry_after)
                tried.append((pid, f"quota: {e}"))
                continue
            except Exception as e:
                quota = looks_like_quota(e)
                retry = getattr(e, "retry_after", None)
                self.status.failure(category, pid, f"{type(e).__name__}: {e}", quota=quota, retry_after=retry)
                tried.append((pid, f"{'quota' if quota else 'error'}: {e}"))
                log.warning("Provider %s/%s gagal: %s", category, pid, e)
                continue
            self.status.success(category, pid)
            if tried:
                log.info("Failover %s: sukses di '%s' setelah %s", category, pid, tried)
            else:
                log.info("Provider %s/%s sukses (primer)", category, pid)
            return CallResult(category=category, provider_id=pid, value=value, tried=tried)
        raise AllProvidersFailed(category, tried)

    def report(self) -> dict:
        """Ringkasan untuk CLI / Telegram / BLUEPRINT runtime."""
        out: dict[str, list[dict]] = {}
        for cat, ids in CHAINS.items():
            rows = []
            for pid in ids:
                meta = provider_meta(cat, pid) or {}
                rec = self.status.get(cat, pid)
                cooling = self.status.is_cooling(cat, pid)
                rem = self.status.cooldown_remaining(cat, pid)
                rows.append(
                    {
                        "id": pid,
                        "name": meta.get("name", pid),
                        "gratis": meta.get("gratis", True),
                        "verified_limits": meta.get("verified", False),
                        "limits": meta.get("limits", ""),
                        "env": meta.get("env", []),
                        "cooling": cooling,
                        "quota_exhausted": rec.quota_exhausted,
                        "cooldown_until": rec.cooldown_until,
                        "cooldown_remaining_min": round(rem.total_seconds() / 60, 1) if rem else 0,
                        "last_error": rec.last_error,
                        "last_success_at": rec.last_success_at,
                        "success_count": rec.success_count,
                        "failure_count": rec.failure_count,
                    }
                )
            out[cat] = rows
        return out
