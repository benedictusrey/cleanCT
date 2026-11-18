from __future__ import annotations

import base64
import binascii
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "cleanct-checkpoint"
VERSION = 1
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_EDGE = 2048
PLANES = {"sagittal", "coronal", "axial"}
CMAPS = {"grayscale", "spectral", "thermal", "viridis", "plasma"}
DATASETS = {"24um", "66um", "custom"}


class CheckpointError(ValueError):
    """A checkpoint is malformed, unsupported, or unsafe to load."""


def _integer(value: Any, name: str, low: int = 0, high: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CheckpointError(f"Invalid {name}.")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CheckpointError(f"Invalid {name}.")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 1_000_000:
        raise CheckpointError(f"Invalid {name}.")
    return result


def _preview(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > (MAX_PREVIEW_BYTES * 4 // 3 + 64):
        raise CheckpointError("Checkpoint preview is too large.")
    data_url = value
    if data_url.startswith("data:"):
        header, sep, data_url = data_url.partition(",")
        if not sep or header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
            raise CheckpointError("Checkpoint preview must be a PNG or JPEG image.")
    try:
        raw = base64.b64decode(data_url, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CheckpointError("Checkpoint preview is not valid base64.") from exc
    if not raw or len(raw) > MAX_PREVIEW_BYTES:
        raise CheckpointError("Checkpoint preview is empty or too large.")
    image_format = ""
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(raw)) as image:
            image_format = image.format or ""
            if image_format not in {"PNG", "JPEG"}:
                raise CheckpointError("Checkpoint preview must be a PNG or JPEG image.")
            width, height = image.size
            if width < 1 or height < 1 or width > MAX_PREVIEW_EDGE or height > MAX_PREVIEW_EDGE:
                raise CheckpointError("Checkpoint preview dimensions are invalid.")
            image.verify()
    except CheckpointError:
        raise
    except Exception as exc:
        raise CheckpointError("Checkpoint preview image is corrupt.") from exc
    mime = "image/png" if image_format == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def fit_preview(value: str, max_edge: int = 1600) -> str:
    """Scale a preview so its longest edge is at most max_edge pixels.

    The live preview can be a wide strip of slices (a 384 px scan gives an
    8202 x 640 px image), which the checkpoint limit refuses. A checkpoint needs
    a thumbnail, so the preview is scaled to fit; the limit itself is unchanged.
    """
    import io
    from PIL import Image
    data_url = value
    if data_url.startswith("data:"):
        data_url = data_url.partition(",")[2]
    raw = base64.b64decode(data_url, validate=True)
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        if max(image.size) <= max_edge:
            return value
        scale = max_edge / max(image.size)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        thumb = image.convert("RGB").resize(size, Image.LANCZOS)
    out = io.BytesIO()
    thumb.save(out, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def validate_checkpoint(document: Any) -> dict:
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise CheckpointError("This is not a cleanCT checkpoint file.")
    if document.get("version") != VERSION:
        raise CheckpointError("This checkpoint version is not supported.")
    state = document.get("state")
    if not isinstance(state, dict):
        raise CheckpointError("Checkpoint state is missing.")
    dataset = state.get("dataset")
    sample = state.get("sample")
    if not isinstance(dataset, str) or dataset not in DATASETS:
        raise CheckpointError("Checkpoint specimen type is invalid.")
    if not isinstance(sample, str) or not sample or len(sample) > 128 or any(ord(c) < 32 for c in sample):
        raise CheckpointError("Checkpoint specimen name is invalid.")
    plane = state.get("plane", "sagittal")
    cmap = state.get("cmap", "grayscale")
    if (not isinstance(plane, str) or not isinstance(cmap, str) or
            plane not in PLANES or cmap not in CMAPS):
        raise CheckpointError("Checkpoint visualization setting is invalid.")
    z = state.get("z")
    if z is not None:
        z = _integer(z, "preview slice", 0, 10_000_000)
    bounds = state.get("bounds", {})
    if not isinstance(bounds, dict):
        raise CheckpointError("Checkpoint cut-line bounds are invalid.")
    normalized_bounds = {}
    for axis in ("x", "y"):
        pair = bounds.get(axis, [0.15, 0.85])
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise CheckpointError("Checkpoint cut-line bounds are invalid.")
        low, high = (_finite(pair[0], "cut-line bound"),
                     _finite(pair[1], "cut-line bound"))
        if not 0 <= low <= 1 or not 0 <= high <= 1 or high - low < 0.04:
            raise CheckpointError("Checkpoint cut-line bounds are out of range.")
        normalized_bounds[axis] = [low, high]
    lo, hi = (_finite(state.get("lo", -950), "minimum intensity"),
              _finite(state.get("hi", 350), "maximum intensity"))
    if lo >= hi:
        raise CheckpointError("Minimum intensity must be below maximum intensity.")
    guide_mode = state.get("guide_mode", "2lines")
    if not isinstance(guide_mode, str) or guide_mode not in {"2lines", "4lines"}:
        raise CheckpointError("Checkpoint guide mode is invalid.")
    tab = state.get("tab", "auto")
    long_view = state.get("long_view", "sagittal")
    if (not isinstance(tab, str) or not isinstance(long_view, str) or
            tab not in {"auto", "prefs"} or long_view not in {"sagittal", "coronal"}):
        raise CheckpointError("Checkpoint view selection is invalid.")
    for key in ("guides", "air_crop", "pref_dirty"):
        if key in state and not isinstance(state[key], bool):
            raise CheckpointError(f"Checkpoint {key} setting is invalid.")
    source_path = document.get("source_path", "")
    source_kind = document.get("source_kind", "")
    if not isinstance(source_path, str) or len(source_path) > 4096:
        raise CheckpointError("Checkpoint source path is invalid.")
    if (not isinstance(source_kind, str) or
            source_kind not in {"", "dicom", "tiff", "nifti"}):
        raise CheckpointError("Checkpoint source format is invalid.")
    preview = _preview(document.get("preview_png"))
    normalized = {
        "dataset": dataset, "sample": sample,
        "cut": _integer(state.get("cut", 0), "cut slice"),
        "keep": _integer(state.get("keep", 0), "keep slice"),
        "n_slices": _integer(state.get("n_slices", 1), "slice count", 1),
        "margin": _integer(state.get("margin", 0), "cut margin"),
        "plane": plane, "z": z, "cmap": cmap, "lo": lo, "hi": hi,
        "bounds": normalized_bounds, "guide_mode": guide_mode,
        "guides": state.get("guides", True),
        "air_crop": state.get("air_crop", True),
        "pref_dirty": state.get("pref_dirty", False),
        "long_view": long_view,
        "axial_idx": _integer(state.get("axial_idx", 0), "axial slice"),
        "tab": tab,
    }
    if normalized["keep"] >= normalized["cut"] and normalized["cut"] > 0:
        raise CheckpointError("Checkpoint keep line must be above the cut line.")
    if normalized["margin"] > normalized["cut"]:
        raise CheckpointError("Checkpoint cut margin exceeds the cut slice.")
    return {
        "schema": SCHEMA, "version": VERSION,
        "created_utc": str(document.get("created_utc", ""))[:64],
        "source_path": source_path, "source_kind": source_kind,
        "state": normalized, "preview_png": preview,
    }


def save_checkpoint(path: str | Path, document: dict) -> Path:
    destination = Path(path)
    validated = validate_checkpoint(document)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(validated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_FILE_BYTES:
        raise CheckpointError("Checkpoint exceeds the 12 MiB size limit.")
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{destination.name}.", suffix=".tmp",
                dir=destination.parent, delete=False) as handle:
            tmp_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    except Exception:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise
    return destination


def load_checkpoint(path: str | Path) -> dict:
    source = Path(path)
    try:
        size = source.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES:
            raise CheckpointError("Checkpoint file is empty or exceeds the 12 MiB size limit.")
        with source.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise CheckpointError("Checkpoint exceeds the 12 MiB size limit.")
        document = json.loads(raw.decode("utf-8"))
    except CheckpointError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"Could not read checkpoint file: {exc}") from exc
    return validate_checkpoint(document)


def new_document(state: dict, preview_png: str = "", source_path: str = "",
                 source_kind: str = "") -> dict:
    return validate_checkpoint({
        "schema": SCHEMA, "version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path, "source_kind": source_kind,
        "state": state, "preview_png": preview_png,
    })
