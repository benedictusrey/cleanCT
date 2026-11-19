"""Auto Snap to Detection suite (audit 0AG).

Copy-layer verification only: the detection core is frozen.

1. ``core.auto_snap.detected_lines`` pure mapping - cut/keep, the wood-top
   fallback, keep<cut clamping, lateral pair conversion and validation.
2. Offscreen MainWindow behavior - load applies detection, manual edits
   suspend the copy layer until the next detection, the toggle off keeps
   stored lines + neutral pairs, checkpoint restore suspends, the Snap
   button re-arms.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if (not os.environ.get("CLEANCT_ENGINE") or not os.environ.get("CLEANCT_DATA")
        or not os.environ.get("CLEANCT_TEST_TMP_DIR")):
    raise SystemExit("Set isolated CLEANCT_ENGINE, CLEANCT_DATA, and "
                     "CLEANCT_TEST_TMP_DIR paths first")

APP = os.environ.get("CLEANCT_APP_ROOT", str(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, str(APP))
sys.path.insert(0, os.path.join(APP, "src"))

from PySide6.QtWidgets import QApplication

from core import auto_snap
import main_window as mw

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


class QuietWindow(mw.MainWindow):
    """MainWindow without startup IO / auto-select."""

    def _check_gpu(self):
        self._gpu_worker = None

    def _refresh_sidebar(self):
        pass

    def _select_sample(self, ds: str, sample: str, _async: bool = True):
        pass


def make_payload(*, cut=1000, keep=100, wood_top=90, H=400, W=300,
                 x0=40, x1=260, y0=50, y1=380, n=1200,
                 report_cut=None, report_keep=None, unprocessed=False) -> dict:
    """Minimal but complete payload shaped like viewer_core's output."""
    report = {
        "n_slices": n, "source_kind": "dicom",
        "win_lo": -1000.0, "win_hi": 350.0,
        "cut_from": int(report_cut if report_cut is not None else cut),
        "keep_from": int(report_keep if report_keep is not None else
                         (keep if keep is not None else 0)),
        "cut_margin_slices": 0,
        "anchor": cut, "detected_cut_from": cut,
        "intensity_unit": "HU",
    }
    bounds = {
        "y0": y0, "y1": y1, "x0": x0, "x1": x1, "H": H, "W": W, "n": n,
        "zb": {"keep": keep, "cut": cut, "wood_top": wood_top,
               "wood_bottom": y1, "top_ok": keep is not None},
        "anchor": {"ok": True, "z": [cut, cut + 20],
                   "guard_applied": False, "source": "detector-fused"},
        "margins": {"y": [y0, H - 1 - y1], "x": [x0, W - 1 - x1]},
        "voxel_um": 24.852, "scale": {}, "evidence": {},
    }
    return {"report": report, "bounds": bounds, "frames": [], "cloud": None,
            "unprocessed": unprocessed, "key": "auto_snap:test",
            "sample": "TEST", "dataset": "custom"}


def pure_mapping() -> None:
    print("[1] auto_snap.detected_lines mapping")
    b = {"zb": {"cut": 1074, "keep": 10, "wood_top": 28},
         "x0": 89, "x1": 1110, "y0": 97, "y1": 1111, "H": 1200, "W": 1198}
    m = auto_snap.detected_lines(b)
    check("keep rides the wood top (not the air top)", m["keep"] == 28
          and m["keep_source"] == auto_snap.KEEP_SOURCE_WOOD_TOP, str(m))
    ma = auto_snap.detected_lines(b, keep_on_wood_top=False)
    check("air-top keep copied when the wood-top rule is off", ma["keep"] == 10
          and ma["keep_source"] == auto_snap.KEEP_SOURCE_AIR, str(ma))
    # 2_666_5: the air top sits 5 slices above the wood top; the auto Keep is the wood top
    b6 = {"zb": {"cut": 521, "keep": 83, "wood_top": 88},
          "x0": 0, "x1": 10, "y0": 0, "y1": 10, "H": 100, "W": 100}
    check("keep snaps to the wood top, not the air top above it",
          auto_snap.detected_lines(b6)["keep"] == 88, str(auto_snap.detected_lines(b6)))
    check("cut copied", m["cut"] == 1074, str(m))
    # the Cut is placed on the physical metal top (the yellow line at 405 on
    # 2-5), not on the halo onset (353), when the payload carries it
    b5 = {"zb": {"cut": 353, "metal_top": 405, "keep": 19, "wood_top": 19},
          "x0": 0, "x1": 10, "y0": 0, "y1": 10, "H": 100, "W": 100}
    check("cut follows the metal top, not the halo onset",
          auto_snap.detected_lines(b5)["cut"] == 405, str(auto_snap.detected_lines(b5)))
    check("x pair fraction", m["x"] == (89 / 1198.0, 1111 / 1198.0),
          str(m["x"]))
    check("y pair fraction", m["y"] == (97 / 1200.0, 1112 / 1200.0),
          str(m["y"]))

    b2 = {"zb": {"cut": 1074, "keep": None, "wood_top": 65},
          "x0": 0, "x1": 10, "y0": 0, "y1": 10, "H": 100, "W": 100}
    m2 = auto_snap.detected_lines(b2)
    check("deferred air top falls back to wood top",
          m2["keep"] == 65
          and m2["keep_source"] == auto_snap.KEEP_SOURCE_WOOD_TOP, str(m2))
    m2s = auto_snap.detected_lines(b2, keep_on_wood_top=False)
    check("air-only mode leaves deferred keep unset",
          m2s["keep"] is None and m2s["keep_source"] is None, str(m2s))

    b3 = {"zb": {"cut": 100, "keep": 500, "wood_top": 10},
          "x0": 0, "x1": 10, "y0": 0, "y1": 10, "H": 100, "W": 100}
    check("keep clamped below cut", auto_snap.detected_lines(b3, keep_on_wood_top=False)["keep"] == 99)

    check("empty/None bounds -> all None",
          auto_snap.detected_lines(None) == {"cut": None, "keep": None,
                                             "keep_source": None,
                                             "x": None, "y": None})
    b4 = {"zb": {}, "x0": 0, "x1": 10, "y0": 0, "y1": 10, "H": 0, "W": 100}
    m4 = auto_snap.detected_lines(b4)
    check("zero-size axis yields no pair for that axis",
          m4["x"] is not None and m4["y"] is None, str(m4))
    check("degenerate pair span rejected",
          auto_snap.detected_lines(
              {"zb": {}, "x0": 50, "x1": 50, "y0": 0, "y1": 90,
               "H": 100, "W": 1000})["x"] is None)


def window_behavior(app: QApplication) -> None:
    print("[2] offscreen window: apply / suspend / re-detect / toggle")
    w = QuietWindow()
    try:
        p = make_payload()
        w._apply_sample_payload("custom", "TEST", p)
        check("load: state carries the detection",
              w.spin_cut.value() == 1000 and w.spin_keep.value() == 90
              and w._wood_bounds_raw is not None,
              f"cut={w.spin_cut.value()} keep={w.spin_keep.value()}")
        check("load: auto snap armed and clean",
              not w._auto_snap_suspended and not w.pref_dirty)
        pairs = w.pref_viewer.axisBounds()
        check("load: lateral pairs adopted",
              abs(pairs["x"][0] - 40 / 300.0) < 1e-6
              and abs(pairs["y"][1] - 381 / 400.0) < 1e-6, str(pairs))
        check("toggle default ON", w.chk_auto_snap.isChecked())

        # manual edit -> suspended (temporarily), dirty
        w.spin_cut.setValue(950)
        check("manual edit suspends auto snap",
              w._auto_snap_suspended and w.pref_dirty
              and w.spin_cut.value() == 950)
        # next detection re-applies and re-arms
        w._apply_sample_payload("custom", "TEST", make_payload())
        check("re-detect re-applies and re-arms",
              w.spin_cut.value() == 1000 and not w._auto_snap_suspended
              and not w.pref_dirty)

        # deferred air top: fallback on load
        f = make_payload(keep=None, wood_top=90)
        w._apply_sample_payload("custom", "TEST", f)
        log = w.log_view.toPlainText()
        check("fallback keep = wood top on load",
              w.spin_keep.value() == 90, f"keep={w.spin_keep.value()}")
        check("fallback documented in the action log",
              "wood top" in log and "air top deferred" in log)

        # Snap button re-arms after a manual keep drag
        w.spin_keep.setValue(0)
        check("manual keep edit suspends", w._auto_snap_suspended)
        w._snap_lines_to_detection()
        check("Snap button restores detection and re-arms",
              w.spin_keep.value() == 90 and not w._auto_snap_suspended)

        # toggle OFF: stored report lines + neutral pairs, no detection copy
        off = make_payload(cut=1000, keep=100, report_cut=900, report_keep=80)
        w.chk_auto_snap.setChecked(False)
        w._apply_sample_payload("custom", "TEST", off)
        pairs = w.pref_viewer.axisBounds()
        check("toggle off: detection not copied",
              w.spin_cut.value() == 900 and w.spin_keep.value() == 80,
              f"cut={w.spin_cut.value()} keep={w.spin_keep.value()}")
        check("toggle off: neutral pairs, no stale leak",
              abs(pairs["x"][0] - 0.15) < 1e-6
              and abs(pairs["y"][1] - 0.85) < 1e-6, str(pairs))
        # toggle back ON applies immediately
        w.chk_auto_snap.setChecked(True)
        pairs = w.pref_viewer.axisBounds()
        check("toggle on: detection applied immediately",
              w.spin_cut.value() == 1000 and w.spin_keep.value() == 90
              and abs(pairs["x"][0] - 40 / 300.0) < 1e-6,
              f"cut={w.spin_cut.value()} keep={w.spin_keep.value()} "
              f"pairs={pairs}")

        # checkpoint restore counts as manual state -> suspended
        state = {"cut": 800, "keep": 60, "margin": 3, "plane": "coronal",
                 "z": 10, "n_slices": 1200, "cmap": "grayscale",
                 "lo": -1000.0, "hi": 350.0,
                 "bounds": {"x": [0.2, 0.8], "y": [0.1, 0.9]},
                 "guide_mode": "4lines", "guides": True, "air_crop": True,
                 "pref_dirty": True, "long_view": "sagittal",
                 "axial_idx": 5, "tab": "prefs"}
        w._apply_checkpoint_controls(state, schedule=False)
        check("checkpoint restore suspends auto snap",
              w._auto_snap_suspended and w.spin_cut.value() == 800
              and w.spin_keep.value() == 60,
              f"cut={w.spin_cut.value()} keep={w.spin_keep.value()} "
              f"suspended={w._auto_snap_suspended}")

        # unprocessed specimen path applies the pre-process detection too
        up = make_payload(unprocessed=True)
        w._apply_sample_payload("custom", "TEST", up)
        check("unprocessed load applies pre-process detection",
              bool(w.payload.get("unprocessed")) and w.spin_cut.value() == 1000
              and w.spin_keep.value() == 90 and not w._auto_snap_suspended,
              f"cut={w.spin_cut.value()} keep={w.spin_keep.value()}")
    finally:
        w.close()


def main() -> int:
    pure_mapping()
    app = QApplication.instance() or QApplication(sys.argv)
    window_behavior(app)
    print("RESULT:", "ALL PASS" if not failures else f"FAILURES: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
