"""Independent, deliberately naive reference implementations (plain Python lists).

They follow the textbook definitions step by step and share no code with
``analisis_acciones.indicators``. Results are compared to 1e-8.
"""

from __future__ import annotations

import math

NaN = float("nan")


def ref_sma(xs: list[float], n: int) -> list[float]:
    return [NaN if i < n - 1 else sum(xs[i - n + 1 : i + 1]) / n for i in range(len(xs))]


def ref_ema(xs: list[float], n: int) -> list[float]:
    out = [NaN] * len(xs)
    first = next((i for i, x in enumerate(xs) if not math.isnan(x)), None)
    if first is None or len(xs) - first < n:
        return out
    k = 2 / (n + 1)
    seed_at = first + n - 1
    out[seed_at] = sum(xs[first : seed_at + 1]) / n
    for i in range(seed_at + 1, len(xs)):
        out[i] = xs[i] * k + out[i - 1] * (1 - k)
    return out


def ref_rsi(closes: list[float], n: int) -> list[float]:
    out = [NaN] * len(closes)
    if len(closes) <= n:
        return out
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(max(c, 0) for c in changes[:n]) / n
    avg_loss = sum(max(-c, 0) for c in changes[:n]) / n

    def value(g: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if g == 0 else 100.0
        return 100 - 100 / (1 + g / loss)

    out[n] = value(avg_gain, avg_loss)
    for i in range(n + 1, len(closes)):
        c = changes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(c, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-c, 0)) / n
        out[i] = value(avg_gain, avg_loss)
    return out


def ref_macd(closes: list[float], fast: int, slow: int, signal: int) -> tuple[list[float], ...]:
    ef, es = ref_ema(closes, fast), ref_ema(closes, slow)
    line = [a - b for a, b in zip(ef, es, strict=True)]
    sig = ref_ema(line, signal)
    hist = [a - b for a, b in zip(line, sig, strict=True)]
    return line, sig, hist


def ref_bollinger(closes: list[float], n: int, k: float) -> tuple[list[float], ...]:
    upper, middle, lower = [], [], []
    for i in range(len(closes)):
        if i < n - 1:
            upper.append(NaN)
            middle.append(NaN)
            lower.append(NaN)
            continue
        window = closes[i - n + 1 : i + 1]
        mean = sum(window) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in window) / n)
        upper.append(mean + k * sd)
        middle.append(mean)
        lower.append(mean - k * sd)
    return upper, middle, lower


def ref_atr(high: list[float], low: list[float], close: list[float], n: int) -> list[float]:
    trs = []
    for i in range(len(close)):
        if i == 0:
            trs.append(high[0] - low[0])
        else:
            pc = close[i - 1]
            trs.append(max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc)))
    out = [NaN] * len(close)
    if len(trs) < n:
        return out
    out[n - 1] = sum(trs[:n]) / n
    for i in range(n, len(trs)):
        out[i] = (out[i - 1] * (n - 1) + trs[i]) / n
    return out
