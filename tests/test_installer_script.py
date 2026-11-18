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
BUILDER = ROOT / "installer" / "build_installer.py"

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


def builder_run_entries() -> list[str]:
    """The [Run] entries in the template that build_installer.py writes.

    The regression gate runs before the builder rewrites cleanct.iss, so the
    template must be checked too: a stale template silently drops the flag.
    """
    text = BUILDER.read_text(encoding="utf-8")
    start = text.index("[Run]")
    section = text[start:text.index("[UninstallDelete]", start)]
    return [line.strip() for line in section.splitlines()[1:]
            if line.strip() and not line.strip().startswith(";")]


def check_launch(label: str, entries: list[str]) -> None:
    launch = [e for e in entries if "cleanCT.exe" in e]
    check(f"{label}: one launch entry for cleanCT.exe", len(launch) == 1, str(entries))
    if launch:
        flags = launch[0].split("Flags:", 1)[-1]
        check(f"{label}: the post-install launch runs as the original user",
              "runasoriginaluser" in flags, flags.strip())


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8")
    check_launch("cleanct.iss", run_section(text, "Run"))
    check_launch("build_installer.py template", builder_run_entries())
    print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
