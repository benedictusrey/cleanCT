"""Chrome colours come from theme.py, not from hex codes typed into widgets.

A hard-coded text colour looked fine in the dark theme and was unreadable in
the light one (the About dialog's amber, the Properties dialog's near-white).
The scan canvas and the viewer overlays are data, so they keep their colours.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# Files whose hex colours are data or the always-dark canvas, not chrome.
EXEMPT_FILES = {"theme.py", "viewer_2d.py", "viewer_3d.py"}
# A legend chip painted on the dark canvas keeps its overlay colour.
CANVAS_CHIP = "background-color:#0b0d10"

failures: list[str] = []
offenders: list[str] = []
for path in sorted(SRC.rglob("*.py")):
    if path.name in EXEMPT_FILES:
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not HEX.search(line) or CANVAS_CHIP in line:
            continue
        offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:90]}")

for item in offenders:
    print("FAIL hard-coded chrome colour " + item)
    failures.append(item)
if not offenders:
    print("PASS no hard-coded chrome colours outside theme.py and the viewers")

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
