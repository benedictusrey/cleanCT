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


def check_stale_rollbacks() -> None:
    """A build that was killed leaves its previous package behind (about 700 MB).
    The next build must remove those, and keep the rollback of its own run."""
    import importlib.util
    import tempfile
    spec = importlib.util.spec_from_file_location("build_installer", BUILDER)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    cache = Path(tempfile.mkdtemp(prefix="cleanct_rollback_"))
    dead = cache / "_pkg_rollback-4294967"       # no such process
    live = cache / f"_pkg_rollback-{os.getpid()}"
    for folder in (dead, live):
        (folder / "runtime").mkdir(parents=True)
        (folder / "runtime" / "payload.bin").write_bytes(b"x")
    builder.prune_stale_rollbacks(cache)
    check("a rollback from a build that is no longer running is removed", not dead.exists())
    check("the rollback of this run is kept", live.exists())


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8")
    check_launch("cleanct.iss", run_section(text, "Run"))
    check_launch("build_installer.py template", builder_run_entries())
    check_stale_rollbacks()
    print("RESULT: " + ("ALL PASS" if not failures else f"{len(failures)} FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
