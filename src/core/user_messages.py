"""Plain-language versions of the errors the pipeline can raise.

The engine writes for developers. Each known message is mapped to a sentence a
technician can act on. Unknown messages pass through unchanged, so nothing is
hidden; the window still shows the original text under "Details".
"""
from __future__ import annotations

_TRANSLATIONS = (
    ("no clean seed slice found",
     "cleanCT could not find the wood in this scan. Check that the scan shows the "
     "wood sample with its metal base, that the wood is not cut off at the edges, "
     "and that the pixel size is set correctly. Then try again."),
)


def pipeline_error(message: str) -> str:
    """The message to show for a pipeline failure."""
    text = (message or "").strip()
    lowered = text.lower()
    for needle, plain in _TRANSLATIONS:
        if needle in lowered:
            return plain
    return text
