"""Tulis rangkaian frame Pillow + audio ke MP4 via ffmpeg (pipe raw RGB)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image

from reels_autopilot.config import TARGET_FPS, TARGET_HEIGHT, TARGET_WIDTH

log = logging.getLogger("reels.encode")


def encode_video(
    dest: Path,
    audio_path: Path | None,
    duration: float,
    frames,
    *,
    fps: int = TARGET_FPS,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    n_expect = max(1, int(round(duration * fps)))
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
    ]
    if audio_path and Path(audio_path).exists():
        cmd += [
            "-i", str(audio_path),
            "-af", "aresample=48000,alimiter=limit=0.84139514:attack=5:release=50:level=false",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "1", "-shortest",
        ]
    else:
        # diam: tetap ada aliran audio agar QC lolos (gaya cerita tanpa VO pun wajib ada audio;
        # pemanggil sebaiknya tetap menyediakan jalur ambient).
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={duration:.3f}", "-c:a", "aac", "-b:a", "128k"]
    cmd += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "fast",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    written = 0
    try:
        for frame in frames:
            if written >= n_expect:
                break
            if not isinstance(frame, Image.Image):
                raise TypeError("frame harus Image")
            if frame.size != (width, height):
                frame = frame.resize((width, height), Image.Resampling.LANCZOS)
            proc.stdin.write(frame.convert("RGB").tobytes())
            written += 1
        # isi sisa jika iterator pendek
        if written and written < n_expect:
            last = frame.convert("RGB")
            raw = last.tobytes()
            for _ in range(n_expect - written):
                proc.stdin.write(raw)
                written += 1
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        rc = proc.wait()
    except Exception:
        proc.kill()
        raise
    if rc != 0 or not dest.exists():
        raise RuntimeError(f"ffmpeg encode gagal ({rc}): {stderr[-800:]}")
    log.info("Encode selesai: %s (%.1fs, %s frame)", dest, duration, written)
    return dest
