"""Konfigurasi dari environment / GitHub Secrets. Default selalu DRY_RUN=true."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

WITA = ZoneInfo("Asia/Makassar")
PACIFIC = ZoneInfo("America/Los_Angeles")

SLOTS: list[dict] = [
    {"id": 1, "hour": 7, "minute": 30},
    {"id": 2, "hour": 12, "minute": 0},
    {"id": 3, "hour": 17, "minute": 0},
    {"id": 4, "hour": 19, "minute": 0},
    {"id": 5, "hour": 21, "minute": 0},
]

# Palet resmi playbook (bagian 9 / 10)
COLOR_BG = "#0F1B2A"
COLOR_ACCENT = "#F28C28"
COLOR_TEXT = "#F4F7FB"
COLOR_MUTED = "#8BA3C7"
COLOR_SHADOW = "#070D16"

# Target QC (retensi: 30–40 dtk, batas keras 45 dtk)
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30
TARGET_LUFS = -14.0
TARGET_TRUE_PEAK = -0.5
TARGET_DURATION = 35.0
MIN_DURATION = 25.0
MAX_DURATION = 40.0
HARD_MAX_DURATION = 45.0
TARGET_WORDS_MIN = 75
TARGET_WORDS_MAX = 100
TARGET_WORDS = 90
MIN_CAPTION_SECONDS = 0.6
CAPTION_MIN_WORDS = 2
CAPTION_MAX_WORDS = 4


def find_root() -> Path:
    env = os.environ.get("REELS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "pyproject.toml").exists() and (p / "src").is_dir():
            return p
    return Path.cwd()


ROOT = find_root()
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip()


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return list(default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    root: Path = field(default_factory=find_root)
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))
    approval_mode: str = field(default_factory=lambda: _str("APPROVAL_MODE", "veto").lower())
    auto_approve_timeout_min: int = field(default_factory=lambda: _int("AUTO_APPROVE_TIMEOUT_MIN", 45))
    skip_on_timeout: bool = field(default_factory=lambda: _bool("SKIP_ON_TIMEOUT", False))
    daily_quota: int = field(default_factory=lambda: _int("DAILY_QUOTA", 5))
    language: str = field(default_factory=lambda: _str("LANGUAGE", "id"))
    tts_voice: str = field(default_factory=lambda: _str("TTS_VOICE", "id-ID-ArdiNeural"))
    tts_rate: str = field(default_factory=lambda: _str("TTS_RATE", "-5%"))
    tz_name: str = field(default_factory=lambda: _str("TZ", "Asia/Makassar"))

    gemini_api_key: str = field(default_factory=lambda: _str("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _str("GEMINI_MODEL", "gemini-3.5-flash-lite"))
    groq_api_key: str = field(default_factory=lambda: _str("GROQ_API_KEY"))
    groq_model: str = field(default_factory=lambda: _str("GROQ_MODEL", "llama-3.3-70b-versatile"))
    openrouter_api_key: str = field(default_factory=lambda: _str("OPENROUTER_API_KEY"))
    openrouter_model: str = field(
        default_factory=lambda: _str("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    )
    cf_account_id: str = field(default_factory=lambda: _str("CF_ACCOUNT_ID"))
    cf_api_token: str = field(default_factory=lambda: _str("CF_API_TOKEN"))
    cf_ai_model: str = field(
        default_factory=lambda: _str("CF_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct")
    )
    github_models_token: str = field(
        default_factory=lambda: _str("GITHUB_MODELS_TOKEN") or _str("GITHUB_TOKEN")
    )
    github_models_model: str = field(
        default_factory=lambda: _str("GITHUB_MODELS_MODEL", "openai/gpt-4o-mini")
    )
    hf_token: str = field(default_factory=lambda: _str("HF_TOKEN"))
    hf_model: str = field(
        default_factory=lambda: _str("HF_MODEL", "meta-llama/Llama-3.2-3B-Instruct")
    )

    piper_bin: str = field(default_factory=lambda: _str("PIPER_BIN", "piper"))
    piper_model: str = field(default_factory=lambda: _str("PIPER_MODEL"))

    pexels_api_key: str = field(default_factory=lambda: _str("PEXELS_API_KEY"))
    pixabay_api_key: str = field(default_factory=lambda: _str("PIXABAY_API_KEY"))
    unsplash_access_key: str = field(default_factory=lambda: _str("UNSPLASH_ACCESS_KEY"))

    video_host_chain: list[str] = field(
        default_factory=lambda: _list("VIDEO_HOST_CHAIN", ["github_release", "r2", "catbox"])
    )
    github_releases_repo: str = field(default_factory=lambda: _str("GITHUB_RELEASES_REPO"))
    github_token: str = field(default_factory=lambda: _str("GITHUB_TOKEN"))
    r2_account_id: str = field(default_factory=lambda: _str("R2_ACCOUNT_ID"))
    r2_access_key_id: str = field(default_factory=lambda: _str("R2_ACCESS_KEY_ID"))
    r2_secret_access_key: str = field(default_factory=lambda: _str("R2_SECRET_ACCESS_KEY"))
    r2_bucket: str = field(default_factory=lambda: _str("R2_BUCKET"))
    r2_public_base_url: str = field(default_factory=lambda: _str("R2_PUBLIC_BASE_URL"))
    r2_endpoint: str = field(default_factory=lambda: _str("R2_ENDPOINT"))

    telegram_bot_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _str("TELEGRAM_CHAT_ID"))

    fb_page_id: str = field(default_factory=lambda: _str("FB_PAGE_ID"))
    fb_page_token: str = field(default_factory=lambda: _str("FB_PAGE_TOKEN"))
    ig_user_id: str = field(default_factory=lambda: _str("IG_USER_ID"))
    # Canonical: IG_ACCESS_TOKEN (Facebook Login for Business user token, atau alias IG_TOKEN).
    ig_token: str = field(default_factory=lambda: _str("IG_ACCESS_TOKEN") or _str("IG_TOKEN"))
    # Host Graph untuk publish IG. Token EAAP (Facebook Login) memakai graph.facebook.com;
    # token Instagram Login memakai graph.instagram.com.
    ig_graph_host: str = field(default_factory=lambda: _str("IG_GRAPH_HOST", "graph.facebook.com"))
    ig_graph_version: str = field(default_factory=lambda: _str("IG_GRAPH_VERSION", "v21.0"))
    # App Meta — dipakai exchange + debug_token. Kosong = health check saja.
    fb_app_id: str = field(default_factory=lambda: _str("FB_APP_ID"))
    fb_app_secret: str = field(default_factory=lambda: _str("FB_APP_SECRET"))
    # PAT fine-grained (contents/secrets RW) untuk refresh token IG menulis secret.
    # GITHUB_TOKEN otomatis Actions TIDAK bisa menulis secret.
    gh_pat: str = field(default_factory=lambda: _str("GH_PAT"))
    meta_graph_version: str = field(default_factory=lambda: _str("META_GRAPH_VERSION", "v26.0"))
    fb_is_ai_generated: bool = field(default_factory=lambda: _bool("FB_IS_AI_GENERATED", True))

    youtube_api_key: str = field(default_factory=lambda: _str("YOUTUBE_API_KEY"))
    http_user_agent: str = field(
        default_factory=lambda: _str(
            "HTTP_USER_AGENT", "reels-autopilot/0.1 (Po Chai Kreator AI; personal pipeline)"
        )
    )

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz_name)
        except Exception:
            return WITA

    @property
    def data_dir(self) -> Path:
        p = self.root / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jobs_dir(self) -> Path:
        p = self.data_dir / "jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_dir(self) -> Path:
        p = self.data_dir / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def dry_run_dir(self) -> Path:
        p = self.data_dir / "dry_run"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def samples_dir(self) -> Path:
        p = self.root / "samples"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def provider_status_path(self) -> Path:
        return self.data_dir / "provider_status.json"

    @property
    def past_topics_path(self) -> Path:
        return self.data_dir / "past_topics.json"

    @property
    def _graph_version(self) -> str:
        v = self.meta_graph_version or "v26.0"
        return v if v.startswith("v") else "v" + v

    @property
    def graph_base(self) -> str:
        """Facebook Graph (hanya untuk publish Page opsional)."""
        return f"https://graph.facebook.com/{self._graph_version}"

    @property
    def _ig_graph_version(self) -> str:
        v = self.ig_graph_version or "v21.0"
        return v if v.startswith("v") else "v" + v

    @property
    def ig_graph_base(self) -> str:
        """Host Graph untuk IG (default graph.facebook.com / v21.0)."""
        host = (self.ig_graph_host or "graph.facebook.com").strip()
        host = host.replace("https://", "").replace("http://", "").strip().strip("/")
        return f"https://{host}/{self._ig_graph_version}"

    @property
    def ig_configured(self) -> bool:
        return bool(self.ig_user_id and self.ig_token)

    @property
    def fb_configured(self) -> bool:
        return bool(self.fb_page_id and self.fb_page_token)


def get_settings() -> Settings:
    return Settings()
