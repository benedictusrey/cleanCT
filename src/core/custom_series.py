#!/usr/bin/env python
"""User-loaded image volumes ("custom specimens") for the app.

Users point the app at a folder containing a DICOM series (or at one file
inside it); the app validates the series, registers it under a specimen id
derived from the folder name, and exposes it to the *unchanged* pipeline by
creating a directory junction:

    <app>/build/custom/data/<specimen>/XY  ->  <user folder>   (junction)

Legacy DICOM registrations retain their directory-junction behavior. TIFF
and NIfTI registrations keep a reference to the original file/folder and use
the shared slice-oriented volume adapter.

The registry lives in <app>/build/custom/registry.json and survives
restarts; registered specimens appear in the sidebar under
"Loaded specimens" and are processed exactly like built-in ones.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from core.paths import ensure_engine_on_path, state_root
except ImportError:  # direct import (no package context)
    from paths import ensure_engine_on_path, state_root

ensure_engine_on_path()

from roi_delivery import read_dicom, sorted_source_files  # noqa: E402
from volume_io import (VolumeInputError, detect_source_kind,
                       inspect_source)  # noqa: E402
try:
    from core.bundle_export import quarantine_corrupt
except ImportError:  # direct import (no package context)
    from bundle_export import quarantine_corrupt


class LoadError(RuntimeError):
    pass


# Registry home: per-user state dir when installed; <checkout>\data\custom
# in the structured dev checkout (registry + junctions live with the other
# per-user data). Dev state root resolution lives in core.paths.
CUSTOM_DIR = state_root() / "custom"
DATA_DIR = CUSTOM_DIR / "data"
REGISTRY = CUSTOM_DIR / "registry.json"
MIN_SLICES = 12          # below this a "volume" is not processable
CUSTOM_KEY = "custom"    # DatasetSpec key used for all loaded series

# user-adjustable Preferences keys (app Preferences tab); stored per specimen
# in the registry's config_overrides and passed to the pipeline untouched
PREF_KEYS = ("cut_override", "keep_from", "cut_margin_slices")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
def _read_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        quarantine_corrupt(REGISTRY, "not valid JSON")
        return []
    except OSError:
        return []
    if not isinstance(data, list):
        quarantine_corrupt(REGISTRY, "not a JSON list")
        return []
    # skip entries a hand edit left without a specimen id, instead of raising
    return [e for e in data if isinstance(e, dict) and e.get("specimen")]


def _write_registry(entries: list[dict]) -> None:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY)


def load_registry() -> list[dict]:
    return _read_registry()


def registered_specimens() -> dict[str, dict]:
    """specimen id -> registry entry (stable order = registry order)."""
    return {e["specimen"]: e for e in _read_registry()}


def as_dataset(specimen: str):
    """DatasetSpec for a registered specimen, honouring its stored
    Preferences (config_overrides) so the pipeline sees cut / keep / margin
    exactly as configured on the Preferences tab."""
    import tomograph as tg
    entry = registered_specimens().get(specimen)
    if entry is None:
        raise LoadError(f"unknown specimen {specimen}")
    return tg.DatasetSpec(
        key=CUSTOM_KEY,
        source=DATA_DIR,
        out_sub=CUSTOM_KEY,
        ground_truth={},
        config_overrides=dict(entry.get("config_overrides") or {}),
        source_kind=str(entry.get("source_kind") or "dicom"),
        source_path=(Path(entry["source_path"])
                     if entry.get("source_path") else None),
        source_metadata=dict(entry.get("source_metadata") or {}),
    )


# --------------------------------------------------------------------------
# validation + config guessing
# --------------------------------------------------------------------------
_WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL",
                         *(f"COM{i}" for i in range(1, 10)),
                         *(f"LPT{i}" for i in range(1, 10))}


# A specimen id is a folder name under %LOCALAPPDATA% and in the output tree.
# Output paths add about 70 characters, and Windows refuses paths over 260
# characters unless long paths are enabled, which is not the default.
MAX_SPECIMEN_LEN = 48


def _sanitize_specimen(name: str) -> str:
    s = (re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:MAX_SPECIMEN_LEN]
         .strip("_") or "specimen")
    # Windows reserves these names: a folder called CON or COM1 cannot be made
    if s.upper() in _WINDOWS_DEVICE_NAMES:
        s = f"{s}_scan"
    return s


def config_overrides_for_spacing(um: float) -> dict:
    """Pixel-scale config overrides (um = pixel size in MICROMETRES),
    extrapolating the validated presets."""
    if um <= 35.0:             # 24 µm-class
        return dict(roi_seed_min_area=20_000, roi_min_area=400,
                    platform_min_voxels=20_000)
    if um <= 80.0:             # 66 µm-class (warm-up swell guard included)
        return dict(roi_seed_min_area=7_500, roi_min_area=150,
                    platform_min_voxels=7_400, min_onset_slope_hu=0.5)
    # generic: scale the 24 µm reference areas by pixel-area ratio
    s = (24.852 / um) ** 2
    return dict(roi_seed_min_area=max(300, int(20_000 * s)),
                roi_min_area=max(50, int(400 * s)),
                platform_min_voxels=max(1_000, int(20_000 * s)))


def resolve_series_folder(folder: Path) -> tuple[Path, str]:
    """Accept the natural ways a user points at a series; return the folder
    whose *.dcm files form the series plus a convention label:

      <pick>/XY/*.dcm          -> (pick/XY, "sample-dir")   dataset layout
      <pick>/*.dcm             -> (pick,     "series-dir")  most natural
      <pick>/xxx.dcm (a file)  -> (parent,   "file")
      <pick>/<sub>/*.dcm       -> (sub,      "nested-dir")  single subfolder
    """
    folder = Path(folder)
    if folder.is_file():
        if folder.suffix.lower() == ".dcm":
            return folder.parent, "file"
        raise LoadError(f"not a DICOM file: {folder.name}")
    if not folder.is_dir():
        raise LoadError(f"folder not found: {folder}")
    if (folder / "XY").is_dir():
        return folder / "XY", "sample-dir"
    if any(folder.glob("*.dcm")):
        return folder, "series-dir"
    subs = [d for d in folder.iterdir() if d.is_dir()]
    hits = [d for d in subs if any(d.glob("*.dcm"))]
    if len(hits) == 1:
        return hits[0], "nested-dir"
    raise LoadError(
        f"no .dcm series found in {folder.name} — pick the folder that "
        f"directly contains the .dcm files (or a .dcm file inside it)")


def validate_series(folder: Path, progress=None) -> dict:
    """Validate a DICOM series folder; returns summary (no volume load).

    NOTE: pipeline helpers like sorted_source_files() append '/XY' themselves,
    so validation here lists the resolved series folder directly.
    """
    series_dir, convention = resolve_series_folder(Path(folder))
    files = sorted(series_dir.glob("*.dcm"))
    if not files:
        raise LoadError(f"no .dcm files in {series_dir.name}")
    if len(files) < MIN_SLICES:
        raise LoadError(f"only {len(files)} DICOM slices found — "
                        f"need at least {MIN_SLICES} to form a volume")
    if progress:
        progress(0, len(files), "headers")
    ds0 = read_dicom(files[0], stop_before_pixels=True)
    try:
        um = float(ds0.PixelSpacing[0]) * 1000.0
        rows, cols = int(ds0.Rows), int(ds0.Columns)
        read_dicom(files[len(files) // 2], stop_before_pixels=True)
    except Exception as e:
        raise LoadError(f"series is not readable DICOM: {e}") from e
    if progress:
        progress(1, len(files), "headers")
    return {"source_folder": str(series_dir), "n_slices": len(files),
            "pixel_um": round(um, 4), "rows": rows, "cols": cols,
            "picked_folder": str(folder), "convention": convention,
            "first_file": files[0].name, "last_file": files[-1].name}


def validate_input(path: Path, *, intensity: str = "auto",
                   progress=None) -> dict:
    """Auto-detect and validate one DICOM, TIFF, or NIfTI volume source."""
    path = Path(path).expanduser().resolve()
    try:
        kind = detect_source_kind(path)
        if kind == "dicom":
            info = validate_series(path, progress=progress)
            info["source_kind"] = "dicom"
            info["source_path"] = info["source_folder"]
            return info
        # Use the pipeline's allocation estimate before TIFF/NIfTI preflight
        # decodes sampled planes or expands a compressed NIfTI to temp storage.
        import tomograph as tg
        info = inspect_source(path, intensity=intensity,
                              memory_check=tg._check_load_memory)
        n, rows, cols = (int(v) for v in info["shape_zyx"])
        if n < MIN_SLICES:
            raise LoadError(f"only {n} slices found — need at least {MIN_SLICES} to form a processable volume")
        spacing = info.get("pixel_spacing_yx_mm") or [None, None]
        pixel_um = (float(spacing[0]) * 1000.0
                    if spacing[0] and float(spacing[0]) > 0 else 0.0)
        info.update(source_folder=str(path), n_slices=n,
                    rows=rows, cols=cols,
                    pixel_um=round(pixel_um, 4),
                    picked_folder=str(path), convention=kind)
        if progress:
            progress(n, n, "validated")
        return info
    except LoadError:
        raise
    except (VolumeInputError, OSError, ValueError, MemoryError) as exc:
        raise LoadError(str(exc)) from exc


_DRIVE_REMOTE = 4          # GetDriveTypeW: a network drive, mapped or not


def is_local_folder(path: Path) -> bool:
    """True when the folder is on this PC rather than on a network share.

    An NTFS junction can only point at a local folder, so a share cannot be
    linked. A mapped network drive letter is not local either.
    """
    text = str(path)
    if text.startswith("\\\\?\\"):          # extended-length prefix on a local path
        text = text[4:]
    if text.startswith("\\\\") or text.startswith("//"):
        return False                        # UNC: \\server\share\...
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        drive = os.path.splitdrive(os.path.abspath(text))[0]
        if not drive:
            return True
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
    except (AttributeError, OSError):
        return True
    return kind != _DRIVE_REMOTE


def register_series(folder: Path, specimen: str | None = None,
                    progress=None, *, intensity: str = "auto") -> dict:
    """Validate and register any supported source; returns its registry entry.

    progress(done, total, stage) is called at each step: 'headers'
    (DICOM spot-reads), 'link' (junction setup), 'pipeline' (full series
    read through the pipeline's own sorted_source_files path).
    """
    info = validate_input(folder, intensity=intensity, progress=progress)
    source_kind = str(info.get("source_kind") or "dicom")
    if source_kind != "dicom":
        guess_from = Path(folder)
        if guess_from.is_file():
            guess_from = guess_from.parent
        if not specimen:
            specimen = guess_from.name
        specimen = _sanitize_specimen(specimen)
        entries = _read_registry()
        existing = {e["specimen"] for e in entries}
        base, suffix = specimen, 2
        while specimen in existing:
            specimen = f"{base}_{suffix}"
            suffix += 1
        spacing = info.get("pixel_spacing_yx_mm") or [None, None]
        pixel_um = float(spacing[0]) * 1000 if spacing[0] else 0.0
        # If a TIFF lacks physical resolution, use the validated 66-µm-class
        # pixel-count defaults as a conservative detector seed; geometry is
        # explicitly marked assumed in every report/output.
        cfg_um = pixel_um if pixel_um > 0 and not info.get("geometry_assumed") else 66.2
        overrides = config_overrides_for_spacing(cfg_um)
        overrides["save_dicom"] = False
        entry = {
            **info, "specimen": specimen, "dataset_key": CUSTOM_KEY,
            "source_kind": source_kind,
            "source_path": str(Path(info["source_path"]).resolve()),
            "source_metadata": dict(info),
            "config_overrides": overrides,
            "added": datetime.now().isoformat(timespec="seconds"),
        }
        entries.append(entry)
        _write_registry(entries)
        return entry

    dcm_dir = Path(info["source_folder"])      # real folder with the .dcm files
    if not specimen:
        # guess: the series folder name; for a picked .dcm file use its
        # PARENT folder (the filename itself is never a good specimen id);
        # if that folder is literally "XY" (dataset layout), use the
        # grandparent, which carries the sample name
        guess_from = (Path(folder).parent
                      if Path(folder).is_file() else Path(folder))
        if guess_from.name.lower() == "xy":
            guess_from = guess_from.parent
        specimen = guess_from.name
    specimen = _sanitize_specimen(specimen)
    entries = _read_registry()
    existing = {e["specimen"] for e in entries}
    base = specimen
    k = 2
    while specimen in existing:                  # never overwrite a specimen
        specimen = f"{base}_{k}"
        k += 1

    if not is_local_folder(dcm_dir):
        raise LoadError("This scan is on a network share. cleanCT links each scan "
                        "with a junction, and a junction must point to a folder on "
                        "this PC. Copy the scan folder to this PC, then load it.")
    if progress:
        progress(0, 1, "link")
    link = DATA_DIR / specimen / "XY"
    try:
        if not link.parent.exists():
            link.parent.mkdir(parents=True)
        _link_source(link, dcm_dir)
    except OSError as e:
        raise LoadError(f"could not link the series folder: {e}") from e

    # exercise the exact pipeline read path via the junction (it sorts by
    # physical slice position) — fail loudly BEFORE registering if broken
    try:
        if progress:
            progress(0, info["n_slices"], "pipeline")
        n_sorted = len(sorted_source_files(DATA_DIR / specimen))
        if n_sorted != info["n_slices"]:
            raise LoadError(f"series sort mismatch via junction "
                            f"({n_sorted} != {info['n_slices']})")
    except Exception as e:
        try:
            _rmdir_junction(link)
        except OSError as exc:      # a failed cleanup must not hide the real error
            print(f"cleanCT: could not remove the link {link}: {exc}", file=sys.stderr)
        raise LoadError(f"series failed pipeline validation: {e}") from e

    entry = {**info, "specimen": specimen, "dataset_key": CUSTOM_KEY,
             "source_kind": "dicom",
             "config_overrides": config_overrides_for_spacing(
                 info["pixel_um"]),
             "added": datetime.now().isoformat(timespec="seconds")}
    entries.append(entry)
    _write_registry(entries)
    return entry


def set_specimen_overrides(specimen: str, overrides: dict) -> dict:
    """Persist user Preferences (cut slice, collection range) for a loaded
    specimen; keys set to None/absent reset to defaults. Returns the entry.
    """
    entries = _read_registry()
    entry = next((e for e in entries if e["specimen"] == specimen), None)
    if entry is None:
        raise LoadError(f"unknown specimen {specimen}")
    bad = [k for k in overrides if k not in PREF_KEYS]
    if bad:
        raise LoadError(f"unknown preference keys: {', '.join(sorted(bad))}")
    for k in PREF_KEYS:
        if k in overrides:
            v = overrides[k]
            if v is None or (isinstance(v, int) and not isinstance(v, bool)
                             and v >= 0):
                if v is None:
                    entry.get("config_overrides", {}).pop(k, None)
                else:
                    entry.setdefault("config_overrides", {})[k] = int(v)
            else:
                raise LoadError(f"{k} must be a non-negative integer")
    co = entry.get("config_overrides") or {}
    if "keep_from" in co and "cut_override" in co \
            and co["keep_from"] >= co["cut_override"]:
        raise LoadError(
            f"keep_from {co['keep_from']} must be below the cut slice "
            f"{co['cut_override']}")
    _write_registry(entries)
    return entry


def set_specimen_lateral(specimen: str, box: dict | None) -> dict:
    """Persist the lateral box the export crops to: ``{"x": (lo, hi), "y": (lo, hi)}``,
    fractions of the width and height.  ``None`` clears it.

    Kept outside ``config_overrides``: the pipeline rejects unknown keys there,
    and the crop is applied at export time only."""
    entries = _read_registry()
    entry = next((e for e in entries if e["specimen"] == specimen), None)
    if entry is None:
        raise LoadError(f"unknown specimen {specimen}")
    if box is None:
        entry.pop("lateral", None)
    else:
        clean = {}
        for axis in ("x", "y"):
            lo, hi = (float(v) for v in box[axis])
            if not (0.0 <= lo < hi <= 1.0):
                raise LoadError(f"lateral {axis} must satisfy 0 <= lo < hi <= 1, got {lo}, {hi}")
            clean[axis] = [lo, hi]
        entry["lateral"] = clean
    _write_registry(entries)
    return entry


def lateral_box(specimen: str) -> dict | None:
    """The lateral box applied to a registered specimen, or None."""
    lateral = (registered_specimens().get(specimen) or {}).get("lateral")
    if not lateral:
        return None
    return {axis: (float(lateral[axis][0]), float(lateral[axis][1])) for axis in ("x", "y")}


def remove_specimen(specimen: str) -> bool:
    """Unregister the ID, then remove its link (pipeline outputs are kept).

    The registry is written first: a link that cannot be removed (for example
    from an elevated process) must not keep the ID registered forever.
    """
    entries = _read_registry()
    keep = [e for e in entries if e["specimen"] != specimen]
    if len(keep) == len(entries):
        return False
    _write_registry(keep)
    link = DATA_DIR / specimen / "XY"
    if os.path.lexists(link):             # also catches a junction whose source moved
        try:
            _rmdir_junction(link)
            link.parent.rmdir()
        except OSError as exc:
            print(f"cleanCT: unregistered {specimen}; its link could not be removed: {exc}",
                  file=sys.stderr)
    return True


def unique_specimen_id(desired: str, *, ignore: str | None = None) -> str:
    """Sanitized, registry-unique specimen id (suffix _2, _3, ...)."""
    base = _sanitize_specimen(desired)
    specimen = base
    k = 2
    existing = {e["specimen"] for e in _read_registry()}
    existing.discard(ignore)
    while specimen in existing:
        specimen = f"{base}_{k}"
        k += 1
    return specimen


def rename_specimen(old: str, new_id: str) -> str:
    """Rename a registered specimen (registry id; the DICOM junction
    folder follows so the pipeline keeps reading it).  The new id is
    sanitized and made unique.  Processed output folders are renamed by
    the caller (window layer) because they live outside the registry.
    Returns the accepted id."""
    entries = _read_registry()
    entry = next((e for e in entries if e["specimen"] == old), None)
    if entry is None:
        raise LoadError(f"unknown specimen {old}")
    new = unique_specimen_id(new_id, ignore=old)
    if new == old:
        return old
    entry["specimen"] = new
    link_parent = DATA_DIR / old
    if link_parent.is_dir():
        link_parent.rename(DATA_DIR / new)
    _write_registry(entries)
    return new


def duplicate_specimen(specimen: str, new_id: str | None = None) -> dict:
    """Register the same source under a new specimen id (no copy of the
    scan: the registry entry is duplicated; DICOM junctions are linked
    to the same target).  Returns the new registry entry."""
    entry = registered_specimens().get(specimen)
    if entry is None:
        raise LoadError(f"unknown specimen {specimen}")
    new = unique_specimen_id(new_id or f"{specimen}_copy")
    clone = dict(entry)
    clone["specimen"] = new
    clone["added"] = datetime.now().isoformat(timespec="seconds")
    if str(entry.get("source_kind") or "dicom") == "dicom":
        source_folder = entry.get("source_folder") or ""
        if not source_folder:
            source_folder = str(Path(entry.get("picked_folder") or "")
                                if entry.get("picked_folder") else "")
        dcm_dir = Path(source_folder)
        if not dcm_dir.is_dir():
            raise LoadError(f"source folder no longer exists: {dcm_dir}")
        link = DATA_DIR / new / "XY"
        try:
            link.parent.mkdir(parents=True, exist_ok=True)
            _link_source(link, dcm_dir)
        except OSError as e:
            raise LoadError(f"could not link the series folder: {e}") from e
    entries = _read_registry()
    entries.append(clone)
    _write_registry(entries)
    return clone


# --------------------------------------------------------------------------
# junction helpers (mklink /J needs no admin rights)
# --------------------------------------------------------------------------
def _mklink_junction(link: Path, target: Path) -> None:
    # no shell: & | ^ % in folder names are plain characters
    import _winapi
    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:
        raise OSError(f"could not create junction {link}: {exc}") from exc
    if not link.is_dir():
        raise OSError(f"junction {link} does not resolve to {target}")


def _link_source(link: Path, target: Path) -> None:
    """Point ``link`` at ``target``. A junction left behind by a moved source
    reports exists() False, so it is repointed rather than re-created."""
    if os.path.lexists(link):
        _retarget_junction(link, target)
    else:
        _mklink_junction(link, target)


def _retarget_junction(link: Path, target: Path) -> None:
    """Existing junction pointing elsewhere (moved folder) — repoint it."""
    try:
        cur = Path(os.readlink(link))
    except OSError:
        cur = None
    if cur is not None and cur.resolve() == target.resolve():
        return
    _rmdir_junction(link)
    _mklink_junction(link, target)


def _rmdir_junction(link: Path) -> None:
    # os.rmdir on a junction removes only the link, never the target contents
    os.rmdir(link)
