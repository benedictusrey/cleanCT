"""The L/R (and sagittal Y) box as pixel ranges: one rule for the preview and the export."""
from __future__ import annotations


def lateral_range(pair, n: int) -> tuple[int, int] | None:
    """Pixels [a, b) inside a lateral pair given as fractions, or None for the whole axis."""
    if not pair:
        return None
    lo, hi = (float(v) for v in pair)
    a = max(0, min(n - 1, int(round(lo * n))))
    b = max(a + 1, min(n, int(round(hi * n))))
    return None if (a == 0 and b == n) else (a, b)
