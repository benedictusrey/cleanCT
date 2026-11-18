"""Installer script guards.

The "Launch cleanCT" checkbox at the end of setup must start the app as the
original (non-elevated) user. An elevated cleanCT cannot traverse the
junctions it creates for loaded scans (WinError 448, untrusted mount point).
"""
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
SCRIPT = ROOT / "installer" / "cleanct.iss"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def run_section(text: str, section: str) -> list[str]:
    lines, inside, out = text.splitlines(), False, []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inside = stripped.lower() == f"[{section}]".lower()
            continue
        if inside and stripped and not stripped.startswith(";"):
            out.append(stripped)
    return out


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8")
    entries = run_section(text, "Run")
    launch = [e for e in entries if "cleanCT.exe" in e]
    check("setup has a launch entry for cleanCT.exe", len(launch) == 1, str(entries))
    if launch:
        flags = launch[0].split("Flags:", 1)[-1]
        check("the post-install launch runs as the original user",
              "runasoriginaluser" in flags, flags.strip())
    print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
