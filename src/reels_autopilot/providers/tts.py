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


def syllable_weight(token: str) -> int:
    """Bobot suku kata + huruf (bahasa Indonesia kasar: kelompok vokal)."""
    core = re.sub(r"[^\w]", "", token or "", flags=re.UNICODE).lower()
    if not core:
        return 1
    groups = re.findall(r"[aeiouéèäö]+", core)
    return max(1, len(groups)) * 3 + max(1, len(core))


def _speech_to_abs(spans: list[tuple[float, float]], t_speech: float) -> float:
    remaining = t_speech
    for a, b in spans:
        length = b - a
        if remaining <= length:
            return a + remaining
        remaining -= length
    return spans[-1][1] if spans else t_speech


def detect_speech_spans(
    path: Path,
    duration: float,
    *,
    noise_db: float = -35.0,
    min_silence: float = 0.15,
) -> list[tuple[float, float]]:
    """Span berisi ucapan (kebalikan silencedetect). Gagal → seluruh durasi."""
    if duration <= 0 or not Path(path).exists():
        return [(0.0, max(0.0, duration))]
    r = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=False,
    )
    log_text = (r.stderr or "") + (r.stdout or "")
    events: list[tuple[str, float]] = []
    for m in re.finditer(r"silence_(start|end):\s*([+-]?\d+(?:\.\d+)?)", log_text):
        events.append((m.group(1), float(m.group(2))))
    if not events:
        return [(0.0, duration)]
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for kind, t in events:
        if kind == "start":
            start = max(0.0, t)
        elif kind == "end" and start is not None:
            silences.append((start, max(start, min(duration, t))))
            start = None
    if start is not None:
        silences.append((start, duration))
    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in silences:
        if a > cursor + 0.02:
            speech.append((cursor, min(a, duration)))
        cursor = max(cursor, b)
    if cursor < duration - 0.02:
        speech.append((cursor, duration))
    speech = [(a, b) for a, b in speech if b > a + 0.02]
    return speech or [(0.0, duration)]


def estimate_words(
    text: str,
    duration: float,
    speech_spans: list[tuple[float, float]] | None = None,
) -> list[Word]:
    """Taksiran timing kata: proporsional suku kata/huruf, hanya di interval ucapan."""
    tokens = WORD_RE.findall(text)
    if not tokens or duration <= 0:
        return []
    weights = [syllable_weight(t) for t in tokens]
    total = sum(weights) or 1
    spans = speech_spans or [(0.0, duration)]
    spans = [(max(0.0, a), min(duration, b)) for a, b in spans if b > a]
    if not spans:
        spans = [(0.0, duration)]
    speech_dur = sum(b - a for a, b in spans) or duration
    out: list[Word] = []
    t_speech = 0.0
    for tok, w in zip(tokens, weights):
        d = speech_dur * (w / total)
        start = _speech_to_abs(spans, t_speech)
        end = _speech_to_abs(spans, t_speech + d)
        out.append(Word(word=tok, start=start, duration=max(0.05, end - start)))
        t_speech += d
    return normalize_word_timings(out, duration)


def normalize_word_timings(words: list[Word], duration: float | None = None) -> list[Word]:
    """Urutkan, rapikan durasi, hilangkan tumpang tindih, clamp ke durasi audio."""
    cleaned: list[Word] = []
    for w in words or []:
        token = (w.word or "").strip()
        if not token:
            continue
        start = max(0.0, float(w.start))
        dur = float(w.duration)
        if dur <= 0:
            dur = 0.08
        cleaned.append(Word(word=token, start=start, duration=dur))
    cleaned.sort(key=lambda w: (w.start, w.end))
    for i in range(len(cleaned) - 1):
        nxt = cleaned[i + 1].start
        if cleaned[i].start > nxt:
            cleaned[i].start = max(0.0, nxt - 0.05)
        if cleaned[i].end > nxt:
            cleaned[i].duration = max(0.05, nxt - cleaned[i].start)
    if duration and duration > 0 and cleaned:
        cap = duration
        kept: list[Word] = []
        for w in cleaned:
            if w.start >= cap:
                break
            if w.end > cap:
                w.duration = max(0.05, cap - w.start)
            kept.append(w)
        cleaned = kept
    return cleaned


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
    # Sisakan ruang −1 dB di bawah target agar mux AAC tidak melewati batas QC.
    tp = min(tp, -1.5)
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
    # Limiter setelah loudnorm: AAC sering menaikkan true peak ~1 dB.
    # 0.84139514 ≈ -1.5 dBFS.
    af = af + ",alimiter=limit=0.84139514:attack=5:release=50:level=false"
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


def atempo_fit(
    audio: Path,
    words: list[Word],
    duration: float,
    max_duration: float,
    dest: Path | None = None,
) -> tuple[Path, list[Word], float]:
    """Percepat audio (atempo) agar muat batas durasi, lalu skala timestamp kata."""
    audio = Path(audio)
    if duration <= max_duration or duration <= 0:
        return audio, list(words), duration
    factor = duration / max_duration
    # atempo hanya 0.5–2.0; rantai jika perlu
    parts: list[str] = []
    rest = factor
    while rest > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        rest /= 2.0
    rest = max(0.5, min(2.0, rest))
    parts.append(f"atempo={rest:.5f}")
    dest = Path(dest) if dest else audio.with_name(audio.stem + "_fit.wav")
    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-i", str(audio),
        "-af", ",".join(parts),
        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"atempo gagal: {(r.stderr or '')[-400:]}")
    new_dur = probe_duration(dest) or (duration / factor)
    tempo = duration / new_dur if new_dur else factor
    new_words = [Word(w.word, w.start / tempo, w.duration / tempo) for w in words]
    return dest, new_words, new_dur


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
        raw_duration = probe_duration(raw) if raw.exists() else 0.0
        norm = loudnorm(raw, final)
        duration = probe_duration(norm)
        # Timing WordBoundary dari audio mentah; skala tipis jika loudnorm mengubah durasi.
        if words and raw_duration > 0 and duration > 0 and abs(duration - raw_duration) > 0.05:
            scale = duration / raw_duration
            words = [Word(word=w.word, start=w.start * scale, duration=w.duration * scale) for w in words]
        if words:
            # Jangan buang timing asli hanya karena ada sunyi di ekor audio.
            if duration > 0 and words[-1].end > duration * 1.2:
                scale = duration / words[-1].end
                words = [Word(word=w.word, start=w.start * scale, duration=w.duration * scale) for w in words]
            words = normalize_word_timings(words, duration)
        if not words:
            spans = detect_speech_spans(norm, duration)
            words = estimate_words(text, duration, speech_spans=spans)
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
