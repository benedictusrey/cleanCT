"""Detection -> cut-line copy layer (audit 0AG).

Pure mapping used by the UI auto-snap, the regression suite and the debug
overlays.  The detection core (``core.wood_bounds``) is FROZEN - this module
never re-measures anything, it only copies the detected bounds onto the
user-facing keep/cut values.

Contract (mirrors the validated load/snap pipeline from audit 0AC):

* ``cut``  = ``zb.cut`` - the pipeline's halo onset (metal threshold line).
* ``keep`` = ``zb.keep`` (verified air top); when the air top deferred and
  ``allow_wood_top_fallback`` is set, ``zb.wood_top`` - the same edge the
  dotted "wood top" guide draws.  Clamped to ``cut - 1``.
* ``x`` / ``y`` = the detected lateral envelope as fractions
  ``(x0 / W, (x1 + 1) / W)`` / ``(y0 / H, (y1 + 1) / H)``.

There is no hidden offset: the physical safety margins are part of the
detection constants (``KEEP_AIR_MARGIN_MM``, clear-air verification, halo
onset).  The user's explicit Margin control and the pipeline's lateral
air-crop stay separate layers by design.
"""
from __future__ import annotations

KEEP_SOURCE_AIR = "air"
KEEP_SOURCE_WOOD_TOP = "wood_top"

#: minimum accepted span for a lateral pair (mirrors the viewer's guard)
MIN_PAIR_SPAN = 0.04


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _pair(lo, hi, size) -> tuple[float, float] | None:
    """Validate a pixel extent into a fraction pair (0..1), or None."""
    lo_i, hi_i, size_i = _as_int(lo), _as_int(hi), _as_int(size)
    if lo_i is None or hi_i is None or size_i is None or size_i <= 0:
        return None
    if hi_i < lo_i:
        lo_i, hi_i = hi_i, lo_i
    f0 = max(0.0, min(1.0, lo_i / float(size_i)))
    f1 = max(0.0, min(1.0, (hi_i + 1) / float(size_i)))
    if f1 - f0 < MIN_PAIR_SPAN:
        return None
    return (f0, f1)


def detected_lines(bounds: dict | None, *,
                   allow_wood_top_fallback: bool = True) -> dict:
    """Copy a ``wood_bounds`` result onto the user-facing cut values.

    Returns ``{"cut", "keep", "keep_source", "x", "y"}`` with ``None`` for
    anything the detection could not provide (callers leave the previous
    value in place for ``None`` fields).  ``keep_source`` is
    ``"air"``/``"wood_top"``/``None``.
    """
    out: dict = {"cut": None, "keep": None, "keep_source": None,
                 "x": None, "y": None}
    if not isinstance(bounds, dict):
        return out

    zb = bounds.get("zb") or {}
    cut = _as_int(zb.get("cut"))
    if cut is not None:
        out["cut"] = max(0, cut)
    keep = _as_int(zb.get("keep"))
    if keep is not None:
        out["keep"] = max(0, keep)
        out["keep_source"] = KEEP_SOURCE_AIR
    elif allow_wood_top_fallback:
        wood_top = _as_int(zb.get("wood_top"))
        if wood_top is not None:
            out["keep"] = max(0, wood_top)
            out["keep_source"] = KEEP_SOURCE_WOOD_TOP
    if out["keep"] is not None and out["cut"] is not None:
        out["keep"] = min(out["keep"], max(0, out["cut"] - 1))

    out["x"] = _pair(bounds.get("x0"), bounds.get("x1"), bounds.get("W"))
    out["y"] = _pair(bounds.get("y0"), bounds.get("y1"), bounds.get("H"))
    return out
