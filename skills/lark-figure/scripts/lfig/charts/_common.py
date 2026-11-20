"""Spec validation helpers shared by chart modules. Messages are written for the model that fixes the spec."""
import math

from ..canvas import T


class LayoutError(ValueError):
    """Raised by a draw() when valid content cannot be placed; the message tells the spec author what to change."""


def need(d, key, where='spec'):
    v = d.get(key) if isinstance(d, dict) else None
    if v is None or v == '' or v == []:
        return [f'{where}.{key} is required']
    return []


def need_list(d, key, lo, hi, where='spec'):
    v = d.get(key)
    if not isinstance(v, list):
        return [f'{where}.{key} must be a list ({lo}-{hi} items)']
    if not lo <= len(v) <= hi:
        return [f'{where}.{key} has {len(v)} items; allowed {lo}-{hi}. Split into two figures or merge items']
    return []


def opt_tone(d, where):
    t = d.get('tone') if isinstance(d, dict) else None
    if t is None or t in T['tones'] or t in T['families']:
        return []
    return [f'{where}.tone {t!r} unknown; use one of {", ".join(T["tones"])}']


def num(v, where):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if not math.isfinite(v):
            return [f'{where} must be a finite number, got {v!r}']
        return []
    return [f'{where} must be a number, got {v!r}']


def fmt(v, unit=''):
    """Compact number: 1234 → 1,234; 0.5 → 0.5; keeps the unit glued."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = f'{v:,}' if isinstance(v, int) else f'{v:g}'
    return f'{s}{unit}'


def nice_ticks(lo, hi, n=5):
    """Round tick values covering [lo, hi] with about n steps."""
    import math
    span = hi - lo or abs(hi) or 1
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t < hi + step * 0.999:
        ticks.append(round(t, 10))
        t += step
    return ticks
