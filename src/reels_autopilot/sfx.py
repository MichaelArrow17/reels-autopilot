"""Efek suara dan musik latar prosedural — tanpa aset berhak cipta."""

from __future__ import annotations

import math
import random
import struct
import subprocess
import wave
from pathlib import Path

from reels_autopilot.providers.tts import loudnorm, probe_duration

SAMPLE_RATE = 44100


def _clip(x: float) -> float:
    return -1.0 if x < -1.0 else 1.0 if x > 1.0 else x


def write_wav(path: Path, samples: list[float], rate: int = SAMPLE_RATE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(samples)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        # pack in chunks
        buf = bytearray()
        for s in samples:
            v = int(_clip(s) * 32767)
            buf += struct.pack("<h", v)
        w.writeframes(bytes(buf))
    return path


def zeros(duration: float, rate: int = SAMPLE_RATE) -> list[float]:
    return [0.0] * max(0, int(duration * rate))


def _env(i: int, n: int, attack: float = 0.01, release: float = 0.08, rate: int = SAMPLE_RATE) -> float:
    if n <= 0:
        return 0.0
    t = i / rate
    dur = n / rate
    a = attack
    r = release
    if t < a and a > 0:
        return t / a
    if t > dur - r and r > 0:
        return max(0.0, (dur - t) / r)
    return 1.0


def pop_sfx(duration: float = 0.13, freq: float = 720.0, rng: random.Random | None = None) -> list[float]:
    rate = SAMPLE_RATE
    n = int(duration * rate)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        f = freq * (1.0 - 0.35 * t / duration)
        env = math.exp(-14.0 * t) * _env(i, n, 0.003, 0.04, rate)
        out[i] = env * (
            0.7 * math.sin(2 * math.pi * f * t)
            + 0.25 * math.sin(2 * math.pi * f * 2 * t)
        )
    return out


def whoosh_sfx(duration: float = 0.32, rising: bool = True) -> list[float]:
    rate = SAMPLE_RATE
    n = int(duration * rate)
    out = [0.0] * n
    rng = random.Random(7)
    # noise + resonan yang menyapu
    for i in range(n):
        t = i / rate
        u = t / duration
        # envelope: triangle-ish
        env = (u * 2 if u < 0.4 else (1 - u) * 1.2)
        env = max(0.0, min(1.0, env))
        noise = rng.uniform(-1, 1)
        f0 = 400 + (1800 * u if rising else 1800 * (1 - u))
        sine = math.sin(2 * math.pi * f0 * t)
        out[i] = 0.35 * env * (0.55 * noise + 0.45 * sine) * math.exp(-1.8 * u)
    return out


def click_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.045 * rate)
    rng = random.Random(3)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-90 * t)
        out[i] = env * (0.5 * math.sin(2 * math.pi * 1900 * t) + 0.3 * rng.uniform(-1, 1))
    return out


def bubble_sfx(rng: random.Random | None = None) -> list[float]:
    rng = rng or random.Random(11)
    rate = SAMPLE_RATE
    duration = rng.uniform(0.12, 0.28)
    n = int(duration * rate)
    f0 = rng.uniform(500, 900)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        f = f0 + 1400 * (t / duration)
        env = math.exp(-7 * t) * _env(i, n, 0.005, 0.05, rate)
        out[i] = 0.45 * env * math.sin(2 * math.pi * f * t)
    return out


def thud_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.35 * rate)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        env = math.exp(-9 * t)
        out[i] = env * (0.8 * math.sin(2 * math.pi * 68 * t) + 0.2 * math.sin(2 * math.pi * 110 * t))
    return out


def break_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.55 * rate)
    rng = random.Random(21)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        noise = rng.uniform(-1, 1) * math.exp(-8 * t)
        metal = math.sin(2 * math.pi * 620 * t) * math.exp(-6 * t)
        low = math.sin(2 * math.pi * 80 * t) * math.exp(-5 * t)
        out[i] = 0.45 * noise + 0.35 * metal + 0.4 * low
    return out


def chime_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.7 * rate)
    freqs = (523.25, 659.25, 783.99)  # C E G
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        s = 0.0
        for k, f in enumerate(freqs):
            delay = k * 0.07
            if t < delay:
                continue
            tt = t - delay
            s += math.sin(2 * math.pi * f * tt) * math.exp(-3.2 * tt)
        out[i] = 0.28 * s
    return out


def chain_rattle_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.4 * rate)
    rng = random.Random(42)
    out = [0.0] * n
    for i in range(n):
        t = i / rate
        # beberapa klik logam acak
        s = 0.0
        for k in range(5):
            start = 0.04 * k
            if t >= start:
                tt = t - start
                s += math.sin(2 * math.pi * (700 + k * 180) * tt) * math.exp(-28 * tt)
                s += 0.15 * rng.uniform(-1, 1) * math.exp(-20 * tt)
        out[i] = 0.35 * s
    return out


def sparkle_sfx() -> list[float]:
    rate = SAMPLE_RATE
    n = int(0.4 * rate)
    out = [0.0] * n
    freqs = (1174, 1568, 2093)
    for i in range(n):
        t = i / rate
        s = sum(math.sin(2 * math.pi * f * t) * math.exp(-8 * t) for f in freqs)
        out[i] = 0.22 * s
    return out


SFX_BANK = {
    "pop": pop_sfx,
    "whoosh": whoosh_sfx,
    "click": click_sfx,
    "bubble": bubble_sfx,
    "thud": thud_sfx,
    "break": break_sfx,
    "chime": chime_sfx,
    "chain": chain_rattle_sfx,
    "sparkle": sparkle_sfx,
}


def render_named(name: str) -> list[float]:
    fn = SFX_BANK.get((name or "").lower())
    if not fn:
        return pop_sfx()
    return fn()


def mix_events(
    events: list[tuple[float, str | list[float]]],
    duration: float,
    *,
    gain: float = 0.55,
    rate: int = SAMPLE_RATE,
) -> list[float]:
    n = max(1, int(duration * rate))
    out = [0.0] * n
    for start, name in events:
        samples = name if isinstance(name, list) else render_named(str(name))
        off = int(max(0.0, start) * rate)
        for i, s in enumerate(samples):
            j = off + i
            if 0 <= j < n:
                out[j] += s * gain
    # soft clip
    peak = max((abs(x) for x in out), default=1.0)
    if peak > 0.95:
        scale = 0.95 / peak
        out = [x * scale for x in out]
    return out


def soft_pad(duration: float, *, gain: float = 0.07, rate: int = SAMPLE_RATE, seed: int = 1) -> list[float]:
    """Pad lembut (akor pelan) untuk latar gaya penjelas. Volume rendah di bawah VO."""
    n = int(duration * rate)
    out = [0.0] * n
    # progresi tenang, C major-ish tetapi rendah
    chords = [
        (130.81, 164.81, 196.00),  # C3 E3 G3
        (110.00, 164.81, 196.00),  # A2
        (87.31, 130.81, 174.61),   # F
        (98.00, 146.83, 196.00),   # G
    ]
    chord_len = 5.0
    for i in range(n):
        t = i / rate
        ci = int(t / chord_len) % len(chords)
        u = (t % chord_len) / chord_len
        env = 0.4 + 0.6 * math.sin(math.pi * u)  # naik-turun halus
        # fade in/out keseluruhan
        edge = min(1.0, t / 1.2, max(0.0, (duration - t) / 1.5))
        s = 0.0
        for k, f in enumerate(chords[ci]):
            s += math.sin(2 * math.pi * f * t + k) * 0.5
            s += math.sin(2 * math.pi * (f * 2.005) * t) * 0.18
        out[i] = gain * env * edge * s / 2.0
    return out


def underwater_ambient(duration: float, *, gain: float = 0.22, rate: int = SAMPLE_RATE) -> list[float]:
    n = int(duration * rate)
    rng = random.Random(99)
    out = [0.0] * n
    # noise "coklat" kasar + LFO rendah + gelembung sporadis
    brown = 0.0
    for i in range(n):
        t = i / rate
        brown += rng.uniform(-1, 1) * 0.04
        brown *= 0.98
        lfo = 0.7 + 0.3 * math.sin(2 * math.pi * 0.12 * t)
        low = 0.15 * math.sin(2 * math.pi * 40 * t) + 0.08 * math.sin(2 * math.pi * 55.1 * t)
        out[i] = gain * lfo * (0.65 * brown + low)
    # gelembung acak
    t = 0.4
    while t < duration - 0.3:
        bub = bubble_sfx(rng)
        off = int(t * rate)
        for i, s in enumerate(bub):
            j = off + i
            if j < n:
                out[j] += s * 0.22 * gain / 0.22
        t += rng.uniform(0.7, 2.2)
    peak = max((abs(x) for x in out), default=1.0)
    if peak > 0.9:
        out = [x * 0.9 / peak for x in out]
    return out


def surface_triumph(duration: float = 2.5, rate: int = SAMPLE_RATE) -> list[float]:
    """Cahaya emas / sampai permukaan: pad naik + chime."""
    n = int(duration * rate)
    out = [0.0] * n
    ch = chime_sfx()
    for i in range(n):
        t = i / rate
        env = min(1.0, t / 0.3) * math.exp(-0.6 * t)
        s = (
            math.sin(2 * math.pi * 261.6 * t)
            + 0.6 * math.sin(2 * math.pi * 329.6 * t)
            + 0.4 * math.sin(2 * math.pi * 392.0 * t)
        )
        out[i] = 0.2 * env * s
        if i < len(ch):
            out[i] += ch[i] * 0.8
    return out


def mix_to_wav(
    dest: Path,
    duration: float,
    *,
    voice: Path | None = None,
    music: list[float] | None = None,
    sfx: list[float] | None = None,
    voice_gain: float = 1.0,
    music_gain: float = 1.0,
    sfx_gain: float = 1.0,
    loudnorm_on: bool = True,
) -> Path:
    """Campur VO + musik + SFX ke WAV, lalu loudnorm. Semua opsional."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rate = SAMPLE_RATE
    n = max(1, int(duration * rate))
    base = [0.0] * n
    if music:
        for i, s in enumerate(music):
            if i < n:
                base[i] += s * music_gain
    if sfx:
        for i, s in enumerate(sfx):
            if i < n:
                base[i] += s * sfx_gain
    raw = dest.with_name(dest.stem + "_mixraw.wav")
    write_wav(raw, base, rate)
    inputs = []
    filters = []
    idx = 0
    if voice and Path(voice).exists():
        inputs += ["-i", str(voice)]
        filters.append(f"[{idx}:a]volume={voice_gain},aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=mono[v]")
        idx += 1
    inputs += ["-i", str(raw)]
    filters.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=mono[bg]")
    if voice and Path(voice).exists():
        filters.append("[v][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
        fmap = "[a]"
    else:
        fmap = "[bg]"
    mid = dest.with_name(dest.stem + "_mid.wav")
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", fmap,
        "-t", f"{duration:.3f}",
        "-ar", str(rate), "-ac", "1",
        str(mid),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    src = mid if mid.exists() and r.returncode == 0 else raw
    if loudnorm_on:
        out = loudnorm(src, dest)
        return Path(out)
    if src != dest:
        if src.exists():
            if dest.suffix == src.suffix:
                dest.write_bytes(src.read_bytes())
            else:
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-y", "-i", str(src), str(dest)],
                    capture_output=True, check=False,
                )
    return dest if dest.exists() else Path(src)


def events_from_scene_starts(
    windows: list[tuple[float, float, dict]],
    *,
    first_pop: bool = True,
) -> list[tuple[float, str]]:
    """Pop di awal tiap adegan, whoosh di transisi."""
    ev: list[tuple[float, str]] = []
    for i, (a, _b, sc) in enumerate(windows):
        named = sc.get("sfx") if isinstance(sc, dict) else None
        if named:
            if isinstance(named, str):
                ev.append((max(0.0, a), named))
            elif isinstance(named, (list, tuple)):
                for j, nm in enumerate(named):
                    ev.append((max(0.0, a + 0.04 * j), str(nm)))
            continue
        if i == 0 and first_pop:
            ev.append((max(0.0, a + 0.05), "pop"))
        else:
            ev.append((max(0.0, a - 0.04), "whoosh"))
            ev.append((max(0.0, a + 0.08), "pop"))
    return ev
