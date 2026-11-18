from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "installer"))

import launcher_main as launcher

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}"
          + (f" [{detail}]" if detail else ""), flush=True)
    if not condition:
        failures.append(name)


def same_path(actual: str | None, expected: Path) -> bool:
    return actual is not None and Path(actual) == expected


class FakeLog:
    def close(self):
        pass


class FakeProcess:
    def wait(self):
        return 0


def run_launcher(env_overrides: dict[str, str | None]) -> dict:
    env_names = ("LOCALAPPDATA", "CLEANCT_DATA", "CLEANCT_OUTPUT_ROOT",
                 "CLEANCT_ENGINE")
    previous = {name: os.environ.get(name) for name in env_names}
    original = {
        "payload_dirs": launcher.payload_dirs,
        "open_log": launcher.open_log,
        "popen": launcher.subprocess.Popen,
        "argv": sys.argv,
    }
    captured: dict = {}

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["env"] = dict(kwargs["env"])
        return FakeProcess()

    try:
        for name in env_names:
            os.environ.pop(name, None)
        for name, value in env_overrides.items():
            if value is not None:
                os.environ[name] = value
        launcher.payload_dirs = lambda: ("C:/cleanCT/app", "C:/cleanCT/engine",
                                         "C:/cleanCT/runtime/python.exe")
        launcher.open_log = lambda _app_dir: FakeLog()
        launcher.subprocess.Popen = fake_popen
        sys.argv = ["cleanCT.exe", "--selfcheck"]
        captured["return_code"] = launcher.main()
        return captured
    finally:
        launcher.payload_dirs = original["payload_dirs"]
        launcher.open_log = original["open_log"]
        launcher.subprocess.Popen = original["popen"]
        sys.argv = original["argv"]
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    local = run_launcher({"LOCALAPPDATA": "C:/users/test/AppData/Local"})
    check("launcher routes packaged outputs to per-user state",
          same_path(local["env"].get("CLEANCT_OUTPUT_ROOT"),
                    Path("C:/users/test/AppData/Local") / "cleanCT" / "pipeline_output"),
          str(local["env"].get("CLEANCT_OUTPUT_ROOT")))
    check("launcher initializes the matching writable state root",
          same_path(local["env"].get("CLEANCT_DATA"),
                    Path("C:/users/test/AppData/Local") / "cleanCT"),
          str(local["env"].get("CLEANCT_DATA")))
    check("launcher passes health-check arguments to embedded Python",
          local["return_code"] == 0 and local["args"][-1] == "--selfcheck",
          str(local["args"]))

    explicit_state = run_launcher({"CLEANCT_DATA": "C:/cleanCT-user-state"})
    check("explicit user state selects matching output root",
          same_path(explicit_state["env"].get("CLEANCT_OUTPUT_ROOT"),
                    Path("C:/cleanCT-user-state") / "pipeline_output"),
          str(explicit_state["env"].get("CLEANCT_OUTPUT_ROOT")))

    explicit_output = run_launcher({
        "LOCALAPPDATA": "C:/users/test/AppData/Local",
        "CLEANCT_OUTPUT_ROOT": "D:/cleanCT-output",
    })
    check("explicit output-root override is preserved",
          same_path(explicit_output["env"].get("CLEANCT_OUTPUT_ROOT"),
                    Path("D:/cleanCT-output")),
          str(explicit_output["env"].get("CLEANCT_OUTPUT_ROOT")))

    print("RESULT: ALL PASS" if not failures
          else f"RESULT: {len(failures)} failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
