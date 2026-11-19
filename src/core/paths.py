#!/usr/bin/env python
"""Single source of truth for install-root resolution (cleanCT 1.0.0).

Two roots matter when cleanCT runs from an installed package rather than
the development checkout:

``engine_root()``
    The frozen metal-remover pipeline (tomograph, roi_delivery, wood_track,
    gpu_backend).  Resolution order:
      1. ``CLEANCT_ENGINE`` environment variable (explicit override)
      2. ``<checkout>/engine``                    (checkout layout)
      3. ``<app>/../engine``                      (installed layout)

``state_root()``
    Where per-user state is written (settings.json, logs/, custom registry,
    export bundles).  Resolution order:
      1. ``CLEANCT_DATA`` environment variable (explicit override)
      2. ``%LOCALAPPDATA%/cleanCT``            (installed layout only; the
                                               development checkout is never
                                               redirected)
      3. ``<app root>/data``                   (development layout)
    If the chosen folder cannot be created, state goes to ``<temp>/cleanCT``
    with a message on stderr. It never falls back into the install folder.

In the development layout every value resolves exactly as the pre-1.0.0
code did, so behaviour on the build machine is byte-identical.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()


def _find_app_root() -> Path:
    """Walk up to the directory holding ``main.py``.

    Works for both layouts without hard-coding depth:
      - src-layout checkout: ``<root>/src/core/paths.py`` -> ``<root>``
      - packaged/dev flat layout:   ``<root>/core/paths.py`` -> ``<root>``
    """
    for parent in _HERE.parents:
        if (parent / "main.py").is_file():
            return parent
    return _HERE.parents[1]


APP_ROOT = _find_app_root()


def is_installed() -> bool:
    """True when running from the installed package layout (app/ + engine/
    + runtime/ siblings) or under an explicit ``CLEANCT_ENGINE``."""
    if (APP_ROOT.parent / "engine").is_dir() and (APP_ROOT / "main.py").is_file():
        return True
    return bool(os.environ.get("CLEANCT_ENGINE"))


def engine_root() -> Path:
    """Frozen pipeline root (imports: tomograph, roi_delivery, ...)."""
    env = os.environ.get("CLEANCT_ENGINE")
    if env and Path(env).is_dir():
        return Path(env)
    bundled = APP_ROOT / "engine"
    if bundled.is_dir():
        return bundled
    installed = APP_ROOT.parent / "engine"
    if installed.is_dir():
        return installed
    return APP_ROOT


def _temp_state_root(reason: str) -> Path:
    p = Path(tempfile.gettempdir()) / "cleanCT"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    print(f"cleanCT: user state folder unavailable ({reason}); using {p}",
          file=sys.stderr)
    return p


def state_root() -> Path:
    """Per-user writable state root (settings, logs, registry, exports).

    Development checkouts keep their user data in ``<root>/data`` so the
    repository root stays clean; installed builds use ``%LOCALAPPDATA%``."""
    env = os.environ.get("CLEANCT_DATA")
    if env:
        p = Path(env)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _temp_state_root(f"CLEANCT_DATA: {exc}")
        return p
    if is_installed():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            p = Path(base) / "cleanCT"
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return _temp_state_root(f"LOCALAPPDATA: {exc}")
            return p
    return APP_ROOT / "data"


def ensure_engine_on_path() -> Path:
    """Put the frozen pipeline on sys.path exactly once; returns its root."""
    root = engine_root()
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def ensure_output_root() -> Path | None:
    """Give an installed run a per-user output root for the engine.

    The engine's built-in output folder is a fixed path on the build
    machine's H: drive. The launcher sets CLEANCT_OUTPUT_ROOT, but a run
    started as runtime\\python.exe app\\main.py does not. Returns the root in
    use, or None for a development checkout, which keeps the engine default.
    """
    if os.environ.get("CLEANCT_OUTPUT_ROOT"):
        return Path(os.environ["CLEANCT_OUTPUT_ROOT"])
    if not is_installed():
        return None
    root = state_root() / "pipeline_output"
    os.environ["CLEANCT_OUTPUT_ROOT"] = str(root)
    return root
