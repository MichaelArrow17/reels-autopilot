"""Easing, interpolasi, dan spring — dipakai gaya penjelas dan cerita."""

from __future__ import annotations

import math


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_pt(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (lerp(a[0], b[0], t), lerp(a[1], b[1], t))


def lerp_color(
    a: tuple[int, ...], b: tuple[int, ...], t: float
) -> tuple[int, ...]:
    t = clamp(t)
    return tuple(int(round(lerp(float(x), float(y), t))) for x, y in zip(a, b))


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def ease_in_quad(t: float) -> float:
    t = clamp(t)
    return t * t


def ease_out_quad(t: float) -> float:
    t = clamp(t)
    return 1 - (1 - t) * (1 - t)


def ease_in_out_quad(t: float) -> float:
    t = clamp(t)
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def ease_in_cubic(t: float) -> float:
    t = clamp(t)
    return t * t * t


def ease_out_cubic(t: float) -> float:
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float, s: float = 1.70158) -> float:
    """Overshoot sedikit lalu mendarat — cocok untuk pop kartu/teks."""
    t = clamp(t)
    s += 1
    return 1 + s * (t - 1) ** 3 + (s - 1) * (t - 1) ** 2


def ease_out_elastic(t: float) -> float:
    t = clamp(t)
    if t == 0 or t == 1:
        return t
    c4 = (2 * math.pi) / 3
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def ease_in_out_sine(t: float) -> float:
    t = clamp(t)
    return -(math.cos(math.pi * t) - 1) / 2


def spring_settle(t: float, *, frequency: float = 6.0, damping: float = 7.0) -> float:
    """0→1 dengan ayunan yang meredam (underdamped spring). t dinormalisasi 0–1 (≈ durasi visual)."""
    t = clamp(t)
    if t >= 1:
        return 1.0
    #x(t) = 1 - e^(-d*t) * cos(2πf t)
    return 1.0 - math.exp(-damping * t) * math.cos(2 * math.pi * frequency * t)


def entrance(t: float, start: float, duration: float = 0.42, kind: str = "back") -> float:
    """Progres masuk elemen sejak `start`. 0 sebelum mulai, 1 setelah selesai."""
    if duration <= 0:
        return 1.0 if t >= start else 0.0
    u = (t - start) / duration
    if u <= 0:
        return 0.0
    if u >= 1:
        return 1.0
    if kind == "elastic":
        return ease_out_elastic(u)
    if kind == "spring":
        return spring_settle(u)
    if kind == "cubic":
        return ease_out_cubic(u)
    if kind == "quad":
        return ease_out_quad(u)
    return ease_out_back(u)


def fade(t: float, start: float, duration: float = 0.25) -> float:
    return clamp((t - start) / duration) if duration > 0 else (1.0 if t >= start else 0.0)


def pulse(t: float, period: float = 2.0, lo: float = 0.85, hi: float = 1.0) -> float:
    if period <= 0:
        return hi
    s = 0.5 + 0.5 * math.sin(2 * math.pi * t / period)
    return lerp(lo, hi, s)
