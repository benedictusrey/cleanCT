from __future__ import annotations

import faulthandler
import os
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(__file__).resolve().parents[1] / "installer" / "_pkg"
APP = PKG / "app"
ENGINE = PKG / "engine"


def main() -> int:
    state_tmp = tempfile.TemporaryDirectory(prefix="cleanct_pkg_gui_state_")
    window = None
    faulthandler.dump_traceback_later(90, exit=True)
    os.environ["CLEANCT_ENGINE"] = str(ENGINE)
    os.environ["CLEANCT_DATA"] = state_tmp.name
    os.environ["CLEANCT_OUTPUT_ROOT"] = str(Path(state_tmp.name) / "pipeline_output")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(APP))

    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        app.setApplicationName("cleanCT")

        from main_window import MainWindow
        t0 = time.perf_counter()
        window = MainWindow()
        t1 = time.perf_counter()
        app.processEvents()

        assert window.windowTitle(), "MainWindow has no title"
        assert not window.windowIcon().isNull(), "packaged cleanCT logo did not load"
        assert window.dataset == "" and window.sample == "", (
            f"empty install tried to select {window.dataset}/{window.sample}")
        assert window.payload is None and not window._loading, (
            "fresh install unexpectedly started a specimen load")
        assert window.empty_state is not None and not window.empty_state.isHidden(), (
            "production empty-state prompt is not shown")
        assert window.stack is not None and not window.stack.isHidden(), (
            "stack workspace should stay visible behind the empty-state card")
        assert window.btn_load.isEnabled(), "load action is disabled"
        assert not window.btn_process.isEnabled(), "processing is enabled without a scan"
        assert not window.btn_export.isEnabled(), "export is enabled without processed data"
        assert not window.btn_save_checkpoint.isEnabled(), (
            "checkpoint save is enabled without a preview")
        assert (APP / "core" / "checkpoint_file.py").is_file(), (
            "checkpoint implementation is missing from package")
        icons = APP / "icons"
        icon_files = [path for path in icons.rglob("*") if path.is_file()]
        assert len(icon_files) == 36, f"expected 36 packaged production graphics, found {len(icon_files)}"
        assert (icons / "app.ico").is_file() and (icons / "icon_256x256.png").is_file(), (
            "required application logo files are missing")

        started = time.perf_counter()
        while time.perf_counter() - started < 60:
            app.processEvents()
            gpu = getattr(window, "_gpu_worker", None)
            if gpu is None or not gpu.isRunning():
                break
            time.sleep(0.025)
        gpu = getattr(window, "_gpu_worker", None)
        if gpu is not None and gpu.isRunning():
            raise AssertionError("GPU capability check did not drain")

        log_text = window.log_view.toPlainText() if window.log_view else ""
        assert "initialized" in log_text, (
            f"GUI did not reach initialized state: {log_text!r}")
        print("PACKAGED GUI SMOKE: PASS "
              f"(constructed in {t1 - t0:.2f}s, empty-state ready, "
              f"{len(icon_files)} production graphics, checkpoint module present)", flush=True)
        return 0
    except Exception as exc:
        print(f"PACKAGED GUI SMOKE: FAIL ({type(exc).__name__}: {exc})",
              flush=True)
        return 1
    finally:
        if window is not None:
            window.close()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        state_tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
