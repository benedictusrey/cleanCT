from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CLEANCT_APP_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "installer"))
sys.path.insert(0, str(ROOT / "src"))

import launcher_main as launcher
from core import paths as app_paths

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
    exit_code = 0

    def wait(self):
        return self.exit_code


def run_launcher(env_overrides: dict[str, str | None], exit_code: int = 0) -> dict:
    env_names = ("LOCALAPPDATA", "CLEANCT_DATA", "CLEANCT_OUTPUT_ROOT",
                 "CLEANCT_ENGINE")
    previous = {name: os.environ.get(name) for name in env_names}
    original = {
        "payload_dirs": launcher.payload_dirs,
        "open_log": launcher.open_log,
        "popen": launcher.subprocess.Popen,
        "argv": sys.argv,
        "fail_box": launcher.fail_box,
    }
    captured: dict = {"boxes": []}

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["env"] = dict(kwargs["env"])
        process = FakeProcess()
        process.exit_code = exit_code
        return process

    try:
        for name in env_names:
            os.environ.pop(name, None)
        for name, value in env_overrides.items():
            if value is not None:
                os.environ[name] = value
        launcher.payload_dirs = lambda: ("C:/cleanCT/app", "C:/cleanCT/engine",
                                         "C:/cleanCT/runtime/python.exe")
        launcher.open_log = lambda _app_dir: (FakeLog(), "C:/state/logs/cleanCT.log")
        launcher.fail_box = captured["boxes"].append
        launcher.subprocess.Popen = fake_popen
        sys.argv = ["cleanCT.exe", "--selfcheck"]
        captured["return_code"] = launcher.main()
        return captured
    finally:
        launcher.payload_dirs = original["payload_dirs"]
        launcher.open_log = original["open_log"]
        launcher.subprocess.Popen = original["popen"]
        launcher.fail_box = original["fail_box"]
        sys.argv = original["argv"]
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def check_output_root_default() -> None:
    """ensure_output_root() routes an installed run that was started without
    the launcher (runtime\\python.exe app\\main.py) to per-user state, keeps an
    explicit override, and leaves the development checkout on the engine
    default."""
    names = ("CLEANCT_ENGINE", "CLEANCT_DATA", "CLEANCT_OUTPUT_ROOT")
    previous = {name: os.environ.get(name) for name in names}
    data_dir = Path(tempfile.mkdtemp(prefix="cleanct_output_root_"))
    ensure = getattr(app_paths, "ensure_output_root", None)
    try:
        os.environ.pop("CLEANCT_OUTPUT_ROOT", None)
        os.environ["CLEANCT_ENGINE"] = str(ROOT)       # marks an installed run
        os.environ["CLEANCT_DATA"] = str(data_dir)
        got = ensure() if ensure else None
        expected = data_dir / "pipeline_output"
        check("installed run without launcher gets output root under CLEANCT_DATA",
              got is not None and Path(got) == expected
              and same_path(os.environ.get("CLEANCT_OUTPUT_ROOT"), expected),
              str(got))

        os.environ["CLEANCT_OUTPUT_ROOT"] = "D:/cleanCT-output"
        got = ensure() if ensure else None
        check("output root helper keeps an explicit override",
              same_path(os.environ.get("CLEANCT_OUTPUT_ROOT"), Path("D:/cleanCT-output"))
              and got is not None and Path(got) == Path("D:/cleanCT-output"),
              str(got))

        os.environ.pop("CLEANCT_OUTPUT_ROOT", None)
        os.environ.pop("CLEANCT_ENGINE", None)
        got = ensure() if ensure else "missing"
        check("development checkout keeps the engine default",
              got is None and "CLEANCT_OUTPUT_ROOT" not in os.environ,
              str(got))
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(data_dir, ignore_errors=True)


def main() -> int:
    # the test is about a normal session; a CI runner may itself be elevated
    launcher.is_elevated = lambda: False
    check_output_root_default()
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

    real_is_elevated = getattr(launcher, "is_elevated", None)
    launcher.is_elevated = lambda: True
    try:
        elevated = run_launcher({"LOCALAPPDATA": "C:/users/test/AppData/Local"})
    finally:
        launcher.is_elevated = real_is_elevated or (lambda: False)
    check("launcher warns when started as administrator",
          len(elevated["boxes"]) == 1 and "as administrator" in elevated["boxes"][0],
          str(elevated["boxes"]))
    check("launcher still starts the app when elevated", elevated["return_code"] == 0)
    crashed = run_launcher({"LOCALAPPDATA": "C:/users/test/AppData/Local"}, exit_code=3)
    check("launcher names the log when the app exits badly at start-up",
          crashed["return_code"] == 3 and len(crashed["boxes"]) == 1
          and "cleanCT.log" in crashed["boxes"][0], str(crashed["boxes"]))
    healthy = run_launcher({"LOCALAPPDATA": "C:/users/test/AppData/Local"})
    check("launcher stays quiet on a clean exit", healthy["boxes"] == [],
          str(healthy["boxes"]))
    local_root = Path(tempfile.mkdtemp(prefix="cleanct_launcher_log_"))
    previous_local = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = str(local_root)
    try:
        handle, log_path = launcher.open_log(str(ROOT))
        check("open_log returns the open log file and its path",
              handle is not None
              and str(log_path).endswith(os.path.join("cleanCT", "logs", "cleanCT.log")),
              str(log_path))
        if handle is not None:
            handle.close()
    finally:
        if previous_local is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = previous_local
        shutil.rmtree(local_root, ignore_errors=True)

    print("RESULT: ALL PASS" if not failures
          else f"RESULT: {len(failures)} failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
