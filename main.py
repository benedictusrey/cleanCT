#!/usr/bin/env python
"""Native cleanCT application entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _selfcheck() -> int:
    """Headless health check (cleanCT.exe --selfcheck).

    Verifies the embedded runtime payload: required wheels import, the
    frozen engine imports, the GPU backend makes its decision, and Qt can
    create a widget offscreen.  Exit 0 = PASS, 2 = FAIL.
    """
    print("cleanCT selfcheck")
    print(f"  python   : {sys.version.split()[0]} ({sys.executable})")
    print(f"  app root : {ROOT}")
    ok = True
    try:
        try:
            from core.paths import engine_root, state_root, is_installed, \
                ensure_engine_on_path, ensure_output_root
        except ImportError:
            from paths import engine_root, state_root, is_installed, \
                ensure_engine_on_path, ensure_output_root
        er, sr = engine_root(), state_root()
        out = ensure_output_root()
        print(f"  engine   : {er} "
              f"({'found' if (er / 'tomograph.py').is_file() else 'MISSING'})")
        print(f"  state    : {sr}")
        print(f"  output   : {out or 'engine default (development checkout)'}")
        print(f"  installed: {is_installed()}")
        if not (er / "tomograph.py").is_file():
            ok = False
        # the packaged payload must always carry its window icon
        try:
            from icon_utils import icons_dir
        except ImportError:
            from icon_utils import icons_dir
        ico_dir = icons_dir(ROOT)
        ico = (ico_dir / "app.ico") if ico_dir else None
        if ico is None or not ico.is_file():
            print("  icon     : MISSING (app.ico)")
            ok = False
        else:
            print(f"  icon     : app.ico found ({ico.stat().st_size} B)")
    except Exception as e:
        print(f"  paths    : FAILED {type(e).__name__}: {e}")
        return 2
    for name, imp in (("numpy", "numpy"), ("scipy", "scipy"),
                      ("pydicom", "pydicom"), ("nibabel", "nibabel"),
                      ("Pillow", "PIL"), ("tifffile", "tifffile"),
                      ("cupy", "cupy"), ("PySide6", "PySide6.QtCore")):
        try:
            mod = __import__(imp, fromlist=["x"])
            print(f"  {name:<9}: {getattr(mod, '__version__', '?')}")
        except Exception as e:
            print(f"  {name:<9}: FAILED {type(e).__name__}: {e}")
            ok = False
    try:
        ensure_engine_on_path()
        import gpu_backend  # noqa: F401
        import roi_delivery  # noqa: F401
        import tomograph  # noqa: F401
        import volume_io  # noqa: F401
        import wood_track  # noqa: F401
        print("  engine   : imports OK (tomograph, roi_delivery, volume_io, wood_track,"
              " gpu_backend)")
    except Exception as e:
        print(f"  engine   : import FAILED {type(e).__name__}: {e}")
        ok = False
    try:
        from gpu_backend import get_backend
        be = get_backend(verbose=False)
        if be.active:
            print(f"  gpu      : ACTIVE {be.info.name} via {be.backend} "
                  f"(CC {be.info.compute_capability})")
        else:
            print(f"  gpu      : CPU fallback "
                  f"({be.info.reason or 'no usable CUDA framework'})")
    except Exception as e:
        print(f"  gpu      : probe failed ({type(e).__name__}: {e}) — "
              "CPU fallback")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel
        _app = QApplication.instance() or QApplication([])
        _w = QLabel("selfcheck")
        print("  qt       : OK (offscreen widget created)")
    except Exception as e:
        print(f"  qt       : FAILED {type(e).__name__}: {e}")
        ok = False
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 2


def main() -> int:
    try:
        from core.paths import ensure_output_root
    except ImportError:
        from paths import ensure_output_root
    # before any engine import: the engine reads CLEANCT_OUTPUT_ROOT at call time
    ensure_output_root()
    if "--selfcheck" in sys.argv:
        return _selfcheck()

    # Set Windows AppUserModelId for taskbar icon clarity & grouping
    import icon_utils
    icon_utils.set_windows_app_id()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from core import single_instance
    from main_window import MainWindow
    import theme

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    if not single_instance.acquire():
        # two windows would rewrite the same registry and settings files
        QMessageBox.information(
            None, "cleanCT", "cleanCT is already open. Use its window instead.")
        return 0
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setApplicationName("cleanCT")
    # NOTE: no setApplicationDisplayName — Qt appends it to every window
    # title, which duplicated the title bar as "… Metal-Base Removal - cleanCT"

    # Set Window and Taskbar Icon (Multi-res with all pixel mipmaps)
    app_icon = icon_utils.get_app_icon(ROOT)
    app.setWindowIcon(app_icon)

    # Apply Dark Graphite Theme
    app.setStyleSheet(theme.QSS)

    window = MainWindow()
    window.setWindowIcon(app_icon)
    window.center_on_screen()
    window.show()

    # Explicit Win32 WM_SETICON for native taskbar
    icon_utils.apply_native_window_icon(int(window.winId()), ROOT)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
