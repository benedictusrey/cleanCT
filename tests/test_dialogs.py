"""Every top-level dialog paints the active theme's ground, reads in both themes,
and keeps to the copy rules (no em dashes, pictographs or all-caps labels).

A stylesheet rule that made every widget transparent also made top-level
dialogs transparent, which Windows paints black. The Load dialog then showed
dark text on black in the light theme. The Properties dialog hard-coded its
text colours, so its values were invisible on the light panel.
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
from dialogs.load_dialog import LoadDialog  # noqa: E402
from dialogs.about_dialog import AboutDialog  # noqa: E402
from dialogs.properties_dialog import SpecimenPropertiesDialog  # noqa: E402

failures: list[str] = []
ACRONYMS = {"XCT", "DICOM", "TIFF", "NIFTI", "GPU", "ROI", "CT", "HU", "KPI"}
PICTOGRAPHS = re.compile("[\u2014\u2713\u2717\u2460-\u2473\u2192\u2190]")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


def ground_hex(widget) -> str:
    """The colour of a pixel in the empty margin of a rendered dialog."""
    img = widget.grab().toImage()
    return img.pixelColor(4, widget.height() - 4).name()


def copy_problems(dialog) -> list[str]:
    problems = []
    for label in dialog.findChildren(QLabel):
        text = label.text()
        if PICTOGRAPHS.search(text):
            problems.append(f"pictograph or em dash in {text[:40]!r}")
        for word in re.findall(r"\b[A-Z]{3,}\b", re.sub(r"<[^>]+>", " ", text)):
            if word not in ACRONYMS:
                problems.append(f"all-caps word {word!r}")
    return problems


SPECIMEN = {"name": "2-5", "slices": 428, "dims": "458x449", "um": 66.21,
            "size_label": "1.2 GB", "dataset": "custom", "kind_label": "DICOM",
            "source": str(ROOT)}

for mode in ("light", "dark"):
    theme.set_mode(mode)
    theme.apply(app)
    for factory in (LoadDialog, AboutDialog,
                    lambda: SpecimenPropertiesDialog(None, SPECIMEN),
                    lambda: SpecimenPropertiesDialog(None, {"name": "bare"})):
        dialog = factory()
        dialog.show()
        app.processEvents()
        name = type(dialog).__name__
        got = ground_hex(dialog)
        want = theme.color("app").lower()
        check(f"{mode}: {name} paints the window ground", got == want,
              f"got {got}, want {want}")
        problems = copy_problems(dialog)
        check(f"{mode}: {name} copy follows the design rules", not problems,
              "; ".join(problems[:3]))
        dialog.close()

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
