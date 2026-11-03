"""Installed-wheel acceptance. Use python -I, outside the source checkout."""

import argparse
import copy
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from concurrent.futures import ThreadPoolExecutor

import cfd_craft as cfd


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def numerical(summary):
    return {
        k: v
        for k, v in summary.items()
        if k not in {"elapsed_s", "source_sha256", "build_version"}
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    # Embedded fixture: this checker must work without any checkout resources.
    case = {
        "schema_version": "cfd-craft.case/0.1",
        "name": "installed-tracer",
        "domain": {"size_m": [4.0, 4.0, 4.0]},
        "grid": {"cells": [8, 8, 8]},
        "boundaries": {"x": "periodic", "y": "periodic", "z": "periodic"},
        "flow": {"kind": "prescribed_uniform", "velocity_m_s": [0.5, 0.0, 0.0]},
        "geometry": [],
        "constituents": [{"id": "tracer", "diffusivity_m2_s": 0.05}],
        "initial_conditions": [
            {
                "kind": "periodic_gaussian",
                "constituent": "tracer",
                "center_m": [2.0, 2.0, 2.0],
                "sigma_m": [0.7, 0.7, 0.7],
                "total_mass_kg": 1e-6,
            }
        ],
        "sources": [],
        "receptors": [
            {
                "kind": "volume_average",
                "id": "R1",
                "min_m": [1.0, 1.0, 1.0],
                "max_m": [3.0, 3.0, 3.0],
            }
        ],
        "numerics": {
            "transport": "muscl",
            "max_time_step_s": 0.1,
            "advective_cfl_max": 0.4,
            "pressure_relative_tolerance": 1e-10,
            "pressure_max_iterations": 1200,
            "steady_residual_tolerance": 1e-5,
            "steady_monitor_tolerance": 0.001,
            "monitor_window": 30,
        },
        "run": {
            "mode": "transient",
            "end_time_s": 0.2,
            "max_steps": 20,
            "wall_time_limit_s": 10.0,
            "threads": 1,
            "memory_limit_mib": 64,
        },
        "output": {"fields": True, "checkpoint": True, "max_total_mib": 8},
    }
    version = importlib.metadata.version("cfd-craft")
    require(
        cfd.__version__ == version == cfd.describe()["version"], "version agreement"
    )
    require(cfd.check(case)["valid"], "valid fixture preflight")
    for bad in [
        b'{"schema_version":"a","schema_version":"b"}',
        cfd.case_bytes(case) + b" {}",
        cfd.case_bytes(dict(case, unknown=1)),
    ]:
        report = cfd.check(bad)
        require(
            not report["valid"] and report["diagnostics"][0]["code"] == "CFD-E000",
            "strict JSON parsing",
        )
        try:
            cfd.simulate(bad)
        except cfd.CfdError as error:
            require(
                error.diagnostics == report["diagnostics"],
                "structured native diagnostics",
            )
        else:
            raise RuntimeError("simulate accepted invalid JSON")
    invalid = copy.deepcopy(case)
    invalid["run"]["wall_time_limit_s"] = 0
    require(not cfd.check(invalid)["valid"], "invalid wall budget")
    result = cfd.simulate(case)
    require(
        result["assessment"] == "transient_interval_completed", "completed assessment"
    )
    require(
        result["experimental_validation"].startswith("not_validated"),
        "honest validation scope",
    )
    require(len(result["source_sha256"]) == 64, "nonempty source fingerprint")
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(cfd.simulate, [case, case]))
    require(
        all(numerical(value) == numerical(result) for value in values),
        "independent concurrent call identity",
    )
    short = copy.deepcopy(case)
    short["run"]["max_steps"] = 1
    incomplete = cfd.simulate(short)
    require(
        incomplete["termination"] == "iteration_limit"
        and incomplete["assessment"] != "transient_interval_completed",
        "incomplete is retained",
    )
    cli = shutil.which("cfd-craft-python", path=sysconfig.get_path("scripts"))
    require(cli is not None, "installed console entry point")
    checks = [
        "versions",
        "strict_JSON",
        "diagnostics",
        "completed_summary",
        "concurrent_identity",
        "incomplete_summary",
        "cancellation",
        "console",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        cancel = folder / "cancel"
        cancel.touch()
        cancelled = cfd.simulate(case, cancel_file=cancel)
        require(
            cancelled["termination"] == "cancelled", "pre-existing cancellation file"
        )
        case_file = folder / "case.json"
        case_file.write_bytes(cfd.case_bytes(case))
        for command in [
            [cli, "simulate"],
            [sys.executable, "-I", "-m", "cfd_craft", "simulate"],
        ]:
            proc = subprocess.run(
                [*command, str(case_file)], capture_output=True, check=True
            )
            require(
                numerical(json.loads(proc.stdout)) == numerical(result),
                "installed CLI identity",
            )
        case_file.write_bytes(cfd.case_bytes(short))
        proc = subprocess.run(
            [cli, "simulate", str(case_file)], capture_output=True, check=False
        )
        require(proc.returncode == 2, "incomplete CLI exit code")
        if args.binary:
            case_file.write_bytes(cfd.case_bytes(case))
            proc = subprocess.run(
                [
                    str(args.binary.resolve()),
                    "run",
                    str(case_file),
                    "--output",
                    str(folder / "native"),
                ],
                capture_output=True,
                check=True,
            )
            require(
                numerical(json.loads(proc.stdout)) == numerical(result),
                "native CLI parity",
            )
            checks.append("native_CLI_parity")
    # A timer needs the GIL: this also detects a bridge that holds it throughout
    # the solve. The child must join its native worker before it exits.
    long_case = copy.deepcopy(case)
    long_case["run"].update(end_time_s=1000.0, max_steps=100000, wall_time_limit_s=5.0)
    code = """import _thread, json, threading
import cfd_craft
case = json.loads(CASE_JSON)
timer = threading.Timer(0.2, _thread.interrupt_main)
timer.start()
try:
    cfd_craft.simulate(case)
except KeyboardInterrupt:
    print('interrupted')
else:
    raise RuntimeError('native solve did not raise KeyboardInterrupt')
finally:
    timer.cancel()
    timer.join()
""".replace("CASE_JSON", repr(json.dumps(long_case)))
    interrupted = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, check=True, timeout=15
    )
    require(
        interrupted.stdout.strip() == b"interrupted", "GIL release and Python signal"
    )
    checks.append("GIL_release_and_interrupt")
    args.output.write_text(
        json.dumps(
            {"passed": True, "version": version, "checks": checks},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
