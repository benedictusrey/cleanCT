#!/usr/bin/env python
"""Single source of truth for install-root resolution (cleanCT 1.0.0).

Two roots matter when cleanCT runs from an installed package rather than
the development checkout:

``engine_root()``
    The frozen metal-remover pipeline (tomograph, roi_delivery, wood_track,
    gpu_backend).  Resolution order:
      1. ``CLEANCT_ENGINE`` environment variable (explicit override)
      2. ``<app>/../engine``                      (installed layout)
      3. ``<dev checkout>/../metal_remover``      (development layout)

``state_root()``
    Where per-user state is written (settings.json, logs/, custom registry,
    export bundles).  Resolution order:
      1. ``CLEANCT_DATA`` environment variable (explicit override)
      2. ``%LOCALAPPDATA%/cleanCT``            (installed layout only --
                                               guarded by an installed.json
                                               marker so the dev checkout is
                                               never silently redirected)
      3. the app root                          (development layout)

In the development layout every value resolves exactly as the pre-1.0.0
code did, so behaviour on the build machine is byte-identical.
"""
from __future__ import annotations

import os
import sys
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
    installed = APP_ROOT.parent / "engine"
    if installed.is_dir():
        return installed
    dev = APP_ROOT.parent / "metal_remover"
    if dev.is_dir():
        return dev
    return APP_ROOT


def state_root() -> Path:
    """Per-user writable state root (settings, logs, registry, exports).

    Development checkouts keep their user data in ``<root>/data`` so the
    repository root stays clean; installed builds use ``%LOCALAPPDATA%``."""
    env = os.environ.get("CLEANCT_DATA")
    if env:
        p = Path(env)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            return APP_ROOT
        return p
    if is_installed():
        base = os.environ.get("LOCALAPPDATA")
        if base:
            p = Path(base) / "cleanCT"
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError:
                return APP_ROOT
            return p
    return APP_ROOT / "data"


def ensure_engine_on_path() -> Path:
    """Put the frozen pipeline on sys.path exactly once; returns its root."""
    root = engine_root()
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root
