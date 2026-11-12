"""QC otomatis sesuai playbook 10.4: resolusi, fps, audio, durasi, loudness, true peak."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from reels_autopilot.config import (
    HARD_MAX_DURATION,
    MAX_DURATION,
    MIN_DURATION,
    TARGET_HEIGHT,
    TARGET_LUFS,
    TARGET_TRUE_PEAK,
    TARGET_WIDTH,
)

log = logging.getLogger("reels.qc")


@dataclass
class QCResult:
    path: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    has_audio: bool = False
    has_video: bool = False
    integrated_lufs: float | None = None
    true_peak_dbtp: float | None = None
    mean_volume_db: float | None = None
    file_size: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe gagal: {r.stderr[-400:]}")
    return json.loads(r.stdout)


def _ebur128(path: Path) -> tuple[float | None, float | None]:
    """Ukur integrated LUFS dan true peak (dBTP) via ebur128."""
    r = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "ebur128=framelog=verbose:peak=true",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=False,
    )
    text = (r.stderr or "") + (r.stdout or "")
    integ = peak = None
    # Summary block: "I:  -14.0 LUFS"  "Peak:  -1.2 dBFS" / "True peak"
    import re
    m = re.search(r"\bI:\s*([+-]?\d+(?:\.\d+)?)\s*LUFS", text)
    if m:
        integ = float(m.group(1))
    m = re.search(r"True peak:\s*([+-]?\d+(?:\.\d+)?)\s*dB", text, re.I)
    if not m:
        m = re.search(r"Peak:\s*([+-]?\d+(?:\.\d+)?)\s*dBFS", text)
    if m:
        peak = float(m.group(1))
    return integ, peak


def _mean_volume(path: Path) -> float | None:
    r = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "volumedetect", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=False,
    )
    import re
    m = re.search(r"mean_volume:\s*([+-]?\d+(?:\.\d+)?)\s*dB", (r.stderr or ""))
    return float(m.group(1)) if m else None


def inspect(path: Path | str) -> QCResult:
    path = Path(path)
    res = QCResult(path=str(path), ok=True, file_size=path.stat().st_size if path.exists() else 0)
    if not path.exists():
        res.ok = False
        res.errors.append("file tidak ada")
        return res
    try:
        info = _ffprobe(path)
    except Exception as e:
        res.ok = False
        res.errors.append(str(e))
        return res
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    try:
        res.duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        res.duration = 0.0
    for s in streams:
        if s.get("codec_type") == "video" and not res.has_video:
            res.has_video = True
            res.width = int(s.get("width") or 0)
            res.height = int(s.get("height") or 0)
            fps = s.get("r_frame_rate") or s.get("avg_frame_rate") or "0/1"
            try:
                a, b = fps.split("/")
                res.fps = float(a) / float(b) if float(b) else 0.0
            except Exception:
                res.fps = 0.0
        elif s.get("codec_type") == "audio":
            res.has_audio = True
    if res.has_audio:
        try:
            res.integrated_lufs, res.true_peak_dbtp = _ebur128(path)
        except Exception as e:
            res.warnings.append(f"ebur128 gagal: {e}")
        try:
            res.mean_volume_db = _mean_volume(path)
        except Exception as e:
            res.warnings.append(f"volumedetect gagal: {e}")

    # penilaian
    if not res.has_video:
        res.errors.append("tidak ada aliran video")
    if res.width != TARGET_WIDTH or res.height != TARGET_HEIGHT:
        res.errors.append(f"resolusi {res.width}x{res.height}, wajib {TARGET_WIDTH}x{TARGET_HEIGHT}")
    if res.fps and abs(res.fps - 30) > 1.5:
        res.warnings.append(f"fps {res.fps:.2f}, ideal 30")
    if not res.has_audio:
        res.errors.append("tidak ada aliran audio (TTS wajib terdengar)")
    if res.mean_volume_db is not None and res.mean_volume_db < -45:
        res.errors.append(f"audio terlalu sunyi (mean {res.mean_volume_db} dB)")
    if res.duration < MIN_DURATION:
        res.warnings.append(f"durasi {res.duration:.1f}s di bawah ideal {MIN_DURATION:.0f}–{MAX_DURATION:.0f}s")
    if res.duration > MAX_DURATION:
        res.warnings.append(f"durasi {res.duration:.1f}s di atas ideal {MAX_DURATION:.0f}s")
    if res.duration > HARD_MAX_DURATION:
        res.errors.append(f"durasi {res.duration:.1f}s melebihi batas keras 2:59")
    if res.integrated_lufs is not None and abs(res.integrated_lufs - TARGET_LUFS) > 1.5:
        res.warnings.append(
            f"loudness {res.integrated_lufs:.1f} LUFS, target {TARGET_LUFS:.0f} ±1.5"
        )
    if res.true_peak_dbtp is not None and res.true_peak_dbtp > TARGET_TRUE_PEAK + 0.3:
        res.errors.append(
            f"true peak {res.true_peak_dbtp:.2f} dBTP melebihi batas {TARGET_TRUE_PEAK} dBTP"
        )
    if res.ok:
        res.ok = len(res.errors) == 0
    return res


def report_text(q: QCResult) -> str:
    lines = [
        f"QC {q.path}",
        f"  ok={'YA' if q.ok else 'TIDAK'}  {q.width}x{q.height}  {q.fps:.1f}fps  {q.duration:.2f}s  "
        f"audio={'ada' if q.has_audio else 'TIDAK'}  size={q.file_size/1e6:.2f} MB",
        f"  LUFS={q.integrated_lufs}  true_peak={q.true_peak_dbtp}  mean={q.mean_volume_db}",
    ]
    for e in q.errors:
        lines.append(f"  ERROR: {e}")
    for w in q.warnings:
        lines.append(f"  PERINGATAN: {w}")
    return "\n".join(lines)
