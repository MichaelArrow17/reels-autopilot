"""Rantai TTS gratis: edge-tts → gTTS → Piper (offline) → espeak-ng (offline)."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from reels_autopilot.config import Settings, TARGET_LUFS, TARGET_TRUE_PEAK, get_settings
from reels_autopilot.providers.router import ProviderRouter, AllProvidersFailed

log = logging.getLogger("reels.tts")

WORD_RE = re.compile(r"\S+")


@dataclass
class Word:
    word: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class TTSResult:
    audio_path: Path
    words: list[Word] = field(default_factory=list)
    duration: float = 0.0
    provider_id: str = ""
    voice: str = ""


def estimate_words(text: str, duration: float) -> list[Word]:
    tokens = WORD_RE.findall(text)
    if not tokens or duration <= 0:
        return []
    weights = [max(1, len(re.sub(r"[^\w]", "", t, flags=re.UNICODE))) for t in tokens]
    total = sum(weights) or 1
    t = 0.0
    out: list[Word] = []
    for tok, w in zip(tokens, weights):
        d = duration * (w / total)
        out.append(Word(word=tok, start=t, duration=d))
        t += d
    return out


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def loudnorm(src: Path, dest: Path, i: float = TARGET_LUFS, tp: float = TARGET_TRUE_PEAK) -> Path:
    """Normalisasi loudness dua pass (I target, true peak di bawah batas)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Pass 1: ukur
    measure = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y", "-i", str(src),
            "-af", f"loudnorm=I={i}:TP={tp}:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=False,
    )
    stderr = measure.stderr or ""
    # ffmpeg menulis JSON di akhir stderr
    measured = _parse_loudnorm_json(stderr)
    if measured:
        af = (
            f"loudnorm=I={i}:TP={tp}:LRA=11:"
            f"measured_I={measured.get('input_i', i)}:"
            f"measured_TP={measured.get('input_tp', tp)}:"
            f"measured_LRA={measured.get('input_lra', 11)}:"
            f"measured_thresh={measured.get('input_thresh', -24)}:"
            f"offset={measured.get('target_offset', 0)}:"
            f"linear=true"
        )
    else:
        af = f"loudnorm=I={i}:TP={tp}:LRA=11"
    dest_wav = dest if dest.suffix.lower() in {".wav", ".mp3", ".m4a"} else dest.with_suffix(".wav")
    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-i", str(src),
        "-af", af,
        "-ar", "48000", "-ac", "1",
        "-c:a", "pcm_s16le" if dest_wav.suffix == ".wav" else "libmp3lame",
    ]
    if dest_wav.suffix != ".wav":
        cmd += ["-b:a", "192k"]
    cmd.append(str(dest_wav))
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not dest_wav.exists():
        # fallback: copy/re-encode tanpa loudnorm
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-ar", "48000", "-ac", "1", str(dest_wav)],
            capture_output=True, check=False,
        )
        log.warning("loudnorm gagal, audio tanpa normalisasi: %s", r.stderr[-400:] if r.stderr else "")
    return dest_wav


def _parse_loudnorm_json(stderr: str) -> dict | None:
    import json

    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None


class TTSClient:
    def __init__(self, settings: Settings | None = None, router: ProviderRouter | None = None):
        self.settings = settings or get_settings()
        self.router = router or ProviderRouter(self.settings)

    def synthesize(self, text: str, out_dir: Path, *, stem: str = "voice") -> TTSResult:
        text = " ".join(text.split())
        if not text:
            raise ValueError("teks TTS kosong")
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = out_dir / f"{stem}_raw.mp3"
        final = out_dir / f"{stem}.wav"
        s = self.settings
        callers = {
            "edge_tts": lambda: self._edge(text, raw),
            "gtts": lambda: self._gtts(text, raw),
        }
        if self._piper_ready():
            callers["piper"] = lambda: self._piper(text, raw)
        if shutil.which("espeak-ng") or shutil.which("espeak"):
            callers["espeak"] = lambda: self._espeak(text, raw)

        result = self.router.execute("tts", callers)
        provider_id, words = result.value
        norm = loudnorm(raw, final)
        duration = probe_duration(norm)
        if not words or (words and words[-1].end < duration * 0.7):
            words = estimate_words(text, duration)
        # rapikan durasi kata terakhir agar tidak melewati audio
        if words and duration > 0 and words[-1].end > duration:
            words[-1].duration = max(0.05, duration - words[-1].start)
        return TTSResult(
            audio_path=norm,
            words=words,
            duration=duration,
            provider_id=provider_id or result.provider_id,
            voice=s.tts_voice,
        )

    def _edge(self, text: str, raw: Path) -> tuple[str, list[Word]]:
        try:
            import edge_tts
        except ImportError as e:
            raise RuntimeError("edge-tts tidak terpasang") from e

        async def _run() -> list[Word]:
            comm = edge_tts.Communicate(text, self.settings.tts_voice, rate=self.settings.tts_rate)
            audio = b""
            words: list[Word] = []
            async for chunk in comm.stream():
                kind = chunk.get("type")
                if kind == "audio":
                    audio += chunk["data"]
                elif kind == "WordBoundary":
                    # offset/duration dalam satuan 100-nanodetik (dokumentasi edge-tts)
                    start = float(chunk.get("offset", 0)) / 1e7
                    dur = float(chunk.get("duration", 0)) / 1e7
                    words.append(Word(word=str(chunk.get("text") or ""), start=start, duration=dur))
            if not audio:
                raise RuntimeError("edge-tts tidak menghasilkan audio")
            raw.write_bytes(audio)
            return words

        words = asyncio.run(_run())
        return "edge_tts", words

    def _gtts(self, text: str, raw: Path) -> tuple[str, list[Word]]:
        try:
            from gtts import gTTS
        except ImportError as e:
            raise RuntimeError("gTTS tidak terpasang") from e
        lang = "id" if self.settings.language.startswith("id") else self.settings.language[:2]
        gTTS(text=text, lang=lang, slow=False).save(str(raw))
        if not raw.exists() or raw.stat().st_size < 100:
            raise RuntimeError("gTTS tidak menghasilkan file")
        return "gtts", []  # timestamp diperkirakan setelah durasi diketahui

    def _piper_ready(self) -> bool:
        s = self.settings
        if not s.piper_model:
            return False
        model = Path(s.piper_model)
        if not model.exists():
            return False
        return bool(shutil.which(s.piper_bin) or Path(s.piper_bin).exists())

    def _piper(self, text: str, raw: Path) -> tuple[str, list[Word]]:
        s = self.settings
        wav = raw.with_suffix(".wav")
        bin_path = shutil.which(s.piper_bin) or s.piper_bin
        r = subprocess.run(
            [bin_path, "--model", s.piper_model, "--output_file", str(wav)],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode != 0 or not wav.exists():
            raise RuntimeError(f"piper gagal: {r.stderr[-300:]}")
        # konversi ke raw.mp3 path yang diharapkan loudnorm (boleh wav)
        raw_wav = raw.with_suffix(".tmp.wav")
        wav.replace(raw) if False else wav.replace(raw.with_name(raw.stem + "_piper.wav"))
        out = raw.with_name(raw.stem + "_piper.wav")
        if not out.exists():
            out = wav
        # tulis ke raw sebagai wav dengan nama raw — loudnorm terima apa saja
        if out != raw:
            raw.write_bytes(out.read_bytes()) if out.suffix == raw.suffix else None
            # always copy via ffmpeg to raw path (mp3 name is ok, we'll just use out)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-y", "-i", str(out), str(raw)],
                capture_output=True, check=False,
            )
        return "piper", []

    def _espeak(self, text: str, raw: Path) -> tuple[str, list[Word]]:
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        wav = raw.with_suffix(".espeak.wav")
        voice = "id" if self.settings.language.startswith("id") else "en"
        r = subprocess.run(
            [exe, "-v", voice, "-s", "140", "-w", str(wav), text],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0 or not wav.exists():
            raise RuntimeError(f"espeak gagal: {r.stderr[-300:]}")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-i", str(wav), str(raw)],
            capture_output=True, check=False,
        )
        return "espeak", []
