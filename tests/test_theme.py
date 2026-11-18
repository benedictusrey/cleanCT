"""The two cleanCT palettes (dark and light) keep text readable and switch cleanly.

Every text colour must reach WCAG AA contrast (4.5:1) on the ground it sits
on, in both themes. The scan canvas stays dark in both, so an image keeps its
contrast whatever the chrome is.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import theme  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


def luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAIRS = [
    ("text", "app"), ("text", "panel"), ("text", "raised"),
    ("text_2", "app"), ("text_2", "panel"),
    ("text_3", "app"), ("text_3", "panel"), ("text_3", "raised"),
    ("accent", "panel"), ("accent", "app"),
    ("on_accent", "accent"), ("ok", "panel"), ("warn", "panel"),
    ("error", "panel"), ("info", "panel"),
]

for mode in ("dark", "light"):
    palette = theme.DARK if mode == "dark" else theme.LIGHT
    for fg, bg in PAIRS:
        ratio = contrast(palette[fg], palette[bg])
        check(f"{mode}: {fg} on {bg} reads at AA",
              ratio >= 4.5, f"{ratio:.2f}:1")

theme.set_mode("dark")
dark_app = theme.color("app")
theme.set_mode("light")
light_app = theme.color("app")
check("switching to light changes the window ground", dark_app != light_app,
      f"{dark_app} vs {light_app}")
check("the stylesheet follows the active mode", "#f1f3f5" in theme.qss()
      and "#15181d" not in theme.qss())
theme.set_mode("dark")
check("the stylesheet has no leftover amber from the old theme",
      "#f2b23c" not in theme.qss().lower())
check("canvas stays dark in both themes",
      theme.DARK["canvas"] == theme.LIGHT["canvas"]
      and luminance(theme.LIGHT["canvas"]) < 0.05)

print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
sys.exit(1 if failures else 0)
