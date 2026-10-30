#!/usr/bin/env python3
"""Bounded Foundation-13 execution for CFD-craft's generated cases.

This result is an external-execution artifact, not cfd-craft.result/0.1 and not
an optimization result. Inputs are trusted generated OpenFOAM dictionaries.
"""

import argparse
import json
import math
import os
import re
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))
from backstep_data import load, sha256
from openfoam_cases import build, control_dict

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def require(ok, field, message, code="CFD-X001"):
    if not ok:
        raise ValueError(f"{code} {field}: {message}")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def claim_directory(path):
    try:
        Path(path).mkdir()
    except FileExistsError as exc:
        raise ValueError(f"CFD-E062 output: directory already exists: {path}") from exc
    except OSError as exc:
        raise ValueError(f"CFD-E063 output: cannot create {path}: {exc}") from exc


def diagnostic(exc, field):
    return str(exc) if str(exc).startswith("CFD-") else f"CFD-X001 {field}: {exc}"


def inventory(directory, symlinks=None):
    """File sizes and hashes. A symlink is an error, or is listed in `symlinks`."""
    directory = Path(directory)
    entries = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            require(
                symlinks is not None,
                str(path.relative_to(directory)),
                "symlink rejected",
            )
            symlinks.append(path.relative_to(directory).as_posix())
            continue
        if path.is_file():
            entries[path.relative_to(directory).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
    return entries


def snapshot_interval(iterations):
    """Largest cadence <=250 that writes the requested final iteration.

    A run that stops at its iteration limit writes a final field only when the
    limit is a multiple of the cadence. Limits without a divisor in 50..250
    would need near per-iteration writes (8 MB per snapshot at level 1), so they
    are rejected rather than slowing a bounded stage into a timeout.
    """
    interval = max(n for n in range(1, min(iterations, 250) + 1) if iterations % n == 0)
    require(
        interval >= min(iterations, 50),
        "iterations",
        "choose a limit with a divisor between 50 and 250, such as a multiple of 50",
    )
    return interval


def prepare(
    kind,
    level,
    iterations,
    output,
    data=None,
    mesh_family="legacy",
    solver_profile="legacy",
):
    require(
        kind != "backstep" or data is not None,
        "data",
        "backstep needs verified measurements",
        "CFD-D001",
    )
    dataset = load(data) if kind == "backstep" else None
    files, metadata = build(
        kind, level, iterations, dataset, mesh_family, solver_profile
    )
    files["system/controlDict"] = control_dict(
        iterations, snapshot_interval(iterations)
    )
    output = Path(output)
    claim_directory(output)
    for name, text in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    manifest = {
        "schema_version": "cfd-craft.openfoam-case/0.1",
        "backend": "OpenFOAM Foundation 13",
        "kind": kind,
        "level": level,
        "max_iterations": iterations,
        "metadata": metadata,
        "generator_sha256": sha256(ROOT / "integrations/openfoam_cases.py"),
        "inputs": inventory(output),
    }
    write_json(output / "case.json", manifest)
    return manifest


def check_prepared(directory):
    directory = Path(directory)
    record = json.loads((directory / "case.json").read_text())
    require(
        record["schema_version"] == "cfd-craft.openfoam-case/0.1",
        "case.schema_version",
        "unsupported",
    )
    require(record["kind"] in {"cavity", "backstep"}, "case.kind", "unsupported")
    require(
        record.get("generator_sha256")
        == sha256(ROOT / "integrations/openfoam_cases.py"),
        "case.generator_sha256",
        "generator changed; prepare a new case",
    )
    actual = inventory(directory)
    actual.pop("case.json")
    require(
        actual == record["inputs"],
        "case.inputs",
        "changed, missing or additional files",
    )
    if "initial_state" in record:
        from openfoam_restart import validate

        validate(directory, record)
    return record


# The child sees a fixed environment. Inherited OpenFOAM site or user settings,
# a preloaded library or a user configuration under HOME could change what the
# hashed runtime does.
INHERITED_ENVIRONMENT = ("LANG", "LC_ALL", "TZ", "TMPDIR")


def runtime(foam_root):
    root = Path(foam_root).resolve()
    base = root / "platforms/linux64GccDPInt32Opt"
    env = {k: os.environ[k] for k in INHERITED_ENVIRONMENT if k in os.environ}
    env.update(
        HOME="/nonexistent",
        WM_PROJECT="OpenFOAM",
        WM_PROJECT_VERSION="13",
        WM_PROJECT_DIR=str(root),
        WM_OPTIONS="linux64GccDPInt32Opt",
        FOAM_ETC=str(root / "etc"),
        FOAM_LIBBIN=str(base / "lib"),
        FOAM_APPBIN=str(base / "bin"),
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
    )
    # Serial Pstream avoids requiring an MPI installation for these small cases.
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        [str(base / "lib"), str(base / "lib/dummy")]
    )
    env["PATH"] = os.pathsep.join([str(base / "bin"), "/usr/bin", "/bin"])
    binaries = {
        name: base / "bin" / name
        for name in ["blockMesh", "checkMesh", "foamRun", "foamPostProcess"]
    }
    for name, path in binaries.items():
        require(
            path.is_file() and os.access(path, os.X_OK),
            f"runtime.{name}",
            "missing executable",
            "CFD-X002",
        )
    result = subprocess.run(
        [str(binaries["foamRun"]), "-help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    require(
        result.returncode == 0 and "Using: OpenFOAM-13 " in result.stdout,
        "runtime.version",
        "requires Foundation 13; forks/other versions are not qualified",
        "CFD-X002",
    )
    # Hash libraries as well as the loader executable: the solver is a .so module.
    paths = (
        list(binaries.values())
        + sorted((base / "lib").glob("*.so"))
        + sorted((base / "lib/dummy").glob("*.so"))
    )
    paths += [root / "etc/controlDict"]
    identities = {
        p.relative_to(root).as_posix(): sha256(p) for p in paths if p.is_file()
    }
    identity = {
        "name": "OpenFOAM Foundation",
        "version": "13",
        "help": result.stdout.strip(),
        "files_sha256": identities,
        "serial": True,
        "precision": "f64",
        "label_bits": 32,
    }
    return binaries, env, identity


class Stop:
    cancelled = False

    def signal(self, signum, frame):
        self.cancelled = True


class ExecutionError(ValueError):
    def __init__(self, message, record):
        super().__init__(message)
        self.record = record


def stop_process(process):
    # The leader can exit while a descendant keeps running or holding the log.
    # Always stop the group, even after Popen has reaped the leader.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def disk_bytes(directory):
    """Bytes of all files below `directory`. OpenFOAM deletes old snapshots
    (purgeWrite) while it runs, so a file can vanish between listing and stat."""
    total = 0
    for base, _, names in os.walk(directory):
        for name in names:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except FileNotFoundError:
                pass
    return total


NONFINITE_LINE = re.compile(
    r"(?:Initial residual|Final residual|sum local|global)\s*=\s*[-+]?(?:nan|inf(?:inity)?)\b",
    re.I,
)
CONTINUITY_LINE = re.compile(r"\bsum local\s*=\s*(" + NUMBER + ")")
# The generated cases are scaled to U_ref = H = 1 and steady runs use deltaT 1,
# so "sum local" is the volume-averaged |div(phi)| in units of U_ref/H. Converged
# and stalled runs stay below 1e-3, also during their first iterations. A value of
# one means the velocity field has grown by orders of magnitude.
CONTINUITY_BREAKDOWN = 1.0


class SolverLogScan:
    """Reads a growing solver log once, in order. The first breakdown is kept."""

    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.partial = b""
        self.finding = None

    def update(self, final=False):
        if self.finding is not None:
            return self.finding
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read()
        self.offset += len(data)
        data = self.partial + data
        cut = len(data) if final else data.rfind(b"\n") + 1
        self.partial = data[cut:][-65536:]
        for line in data[:cut].decode(errors="replace").splitlines():
            if NONFINITE_LINE.search(line):
                self.finding = "execution.solve.residual: nonfinite solver output"
                break
            values = [float(v) for v in CONTINUITY_LINE.findall(line)]
            if any(v >= CONTINUITY_BREAKDOWN for v in values):
                self.finding = (
                    f"execution.solve.continuity: sum local {max(values):.6g} "
                    f">= {CONTINUITY_BREAKDOWN:g}"
                )
                break
        return self.finding


def execute(command, env, output, label, deadline, max_bytes, memory_mib, stop):
    output = Path(output)
    log = output / (label + ".log")

    def limits():
        limit = memory_mib * 1024**2
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))

    start = time.monotonic()
    for kind, wanted, field in [
        (resource.RLIMIT_AS, memory_mib * 1024**2, "limits.memory_mib"),
        (resource.RLIMIT_FSIZE, max_bytes, "limits.output_mib"),
    ]:
        hard = resource.getrlimit(kind)[1]
        require(
            hard == resource.RLIM_INFINITY or wanted <= hard,
            field,
            f"exceeds this host's hard limit of {hard} bytes",
            "CFD-X001",
        )
    require(start < deadline, "execution.deadline", "wall-time limit", "CFD-X004")
    require(not stop.cancelled, "execution.cancel", "cancelled", "CFD-X008")
    failure = None
    scan = SolverLogScan(log) if label == "solve" else None
    with log.open("wb") as stream:
        process = subprocess.Popen(
            command,
            env=env,
            cwd=output / "case",
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=limits,
        )
        try:
            while process.poll() is None:
                if scan is not None and scan.update() is not None:
                    raise ValueError("CFD-X010 " + scan.finding)
                require(not stop.cancelled, "execution.cancel", "cancelled", "CFD-X008")
                require(
                    time.monotonic() < deadline,
                    "execution.deadline",
                    "wall-time limit",
                    "CFD-X004",
                )
                require(
                    disk_bytes(output) <= max_bytes,
                    "execution.output",
                    "output budget exceeded",
                    "CFD-X005",
                )
                time.sleep(0.05)
        except (ValueError, OSError) as exc:
            failure = diagnostic(exc, f"execution.{label}")
        finally:
            stop_process(process)
    record = {
        "program": Path(command[0]).name,
        "arguments": command[1:],
        "returncode": process.returncode,
        "wall_s": time.monotonic() - start,
        "log": log.name,
    }
    if failure is None and scan is not None and scan.update(final=True) is not None:
        failure = "CFD-X010 " + scan.finding
    if failure is None and disk_bytes(output) >= max_bytes:
        failure = "CFD-X005 execution.output: output budget reached"
    if failure is None and process.returncode != 0:
        failure = (
            f"CFD-X003 execution.{label}: exit {process.returncode}; see {log.name}"
        )
    if failure is not None:
        raise ExecutionError(failure, record)
    return record


def block(text, key):
    match = re.search(r"\b" + re.escape(key) + r"\s*\{", text)
    require(match is not None, f"fields.{key}", "missing block", "CFD-X006")
    start = match.end()
    depth = 1
    for i in range(start, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if depth == 0:
            return text[start:i]
    raise ValueError(f"CFD-X006 fields.{key}: unterminated block")


def scalar_value(text, key, count):
    match = re.search(r"\b" + key + r"\s+uniform\s+(" + NUMBER + r")\s*;", text)
    if match:
        value = float(match[1])
        require(math.isfinite(value), f"fields.{key}", "nonfinite", "CFD-X006")
        return [value] * count
    match = re.search(
        r"\b" + key + r"\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;",
        text,
        re.S,
    )
    require(
        match is not None, f"fields.{key}", "expected ASCII scalar list", "CFD-X006"
    )
    tokens = match[2].split()
    require(
        int(match[1]) == count == len(tokens),
        f"fields.{key}",
        "wrong count",
        "CFD-X006",
    )
    try:
        values = [float(x) for x in tokens]
    except ValueError as exc:
        raise ValueError(f"CFD-X006 fields.{key}: nonnumeric value") from exc
    require(
        all(math.isfinite(x) for x in values), f"fields.{key}", "nonfinite", "CFD-X006"
    )
    return values


def internal_values(path, count, vector=False):
    """Read this adapter's ASCII vol field, checking every returned cell."""
    text = Path(path).read_text()
    width = 3 if vector else 1
    uniform = re.search(r"\binternalField\s+uniform\s+([^;]+);", text)
    if uniform:
        tokens = uniform[1].replace("(", " ").replace(")", " ").split()
        expected = width
    else:
        cls = "vector" if vector else "scalar"
        match = re.search(
            r"\binternalField\s+nonuniform\s+List<"
            + cls
            + r">\s+(\d+)\s*\((.*?)\)\s*;",
            text,
            re.S,
        )
        require(
            match is not None,
            f"fields.{Path(path).name}",
            "invalid ASCII internal field",
            "CFD-X006",
        )
        require(
            int(match[1]) == count,
            f"fields.{Path(path).name}",
            "cell count mismatch",
            "CFD-X006",
        )
        tokens = match[2].replace("(", " ").replace(")", " ").split()
        expected = count * width
    require(
        len(tokens) == expected,
        f"fields.{Path(path).name}",
        "wrong value count",
        "CFD-X006",
    )
    try:
        values = [float(x) for x in tokens]
    except ValueError as exc:
        raise ValueError(
            f"CFD-X006 fields.{Path(path).name}: nonnumeric value"
        ) from exc
    require(
        all(math.isfinite(x) for x in values),
        f"fields.{Path(path).name}",
        "nonfinite value",
        "CFD-X006",
    )
    return values


def final_field_checks(case, latest, kind):
    case = Path(case)
    count = json.loads((case / "case.json").read_text())["metadata"]["cells"]
    fields = {}
    for name in ["U", "p", "k", "omega", "nut"] if kind == "backstep" else ["U", "p"]:
        values = internal_values(case / latest / name, count, name == "U")
        minimum, maximum = min(values), max(values)
        require(
            name not in {"k", "nut"} or minimum >= 0,
            f"fields.{name}",
            "negative final turbulence field",
            "CFD-X006",
        )
        require(
            name != "omega" or minimum > 0,
            "fields.omega",
            "nonpositive dissipation",
            "CFD-X006",
        )
        fields[name] = {"minimum": minimum, "maximum": maximum, "all_finite": True}
    return {"cells": count, "fields": fields}


def sample_checks(case, latest, metadata, kind):
    columns = ["U_x", "U_y", "U_z"] + (
        ["wallShearStress_x", "wallShearStress_y", "wallShearStress_z"]
        if kind == "backstep"
        else []
    )
    for name, spec in metadata["expected_samples"].items():
        path = Path(case) / "postProcessing/sampleProfiles" / latest / (name + ".xy")
        lines = path.read_text().splitlines()
        require(
            lines and lines[0].lstrip("#").split() == [spec["axis"], *columns],
            f"samples.{name}.columns",
            "wrong field order",
            "CFD-X006",
        )
        try:
            rows = [
                [float(x) for x in line.split()]
                for line in lines[1:]
                if line.strip() and not line.startswith("#")
            ]
        except ValueError as exc:
            raise ValueError(f"CFD-X006 samples.{name}: nonnumeric value") from exc
        require(
            len(rows) == len(spec["positions"]),
            f"samples.{name}",
            "wrong number of points",
            "CFD-X006",
        )
        for row, position in zip(rows, spec["positions"], strict=True):
            require(
                len(row) == len(columns) + 1 and all(math.isfinite(x) for x in row),
                f"samples.{name}",
                "wrong shape or nonfinite value",
                "CFD-X006",
            )
            require(
                abs(row[0] - position) <= 1e-12,
                f"samples.{name}.position",
                "wrong coordinate",
                "CFD-X006",
            )


def face_count(mesh, name):
    found = re.search(r"nFaces\s+(\d+)", block(mesh, name))
    require(found is not None, f"mesh.{name}.nFaces", "missing", "CFD-X006")
    return int(found[1])


def flux_balance(case, time_name):
    mesh = (Path(case) / "constant/polyMesh/boundary").read_text()
    phi = (Path(case) / time_name / "phi").read_text()
    patches = block(phi, "boundaryField")
    total = []
    for name in [
        "inlet",
        "outlet",
        "lowerWall",
        "stepWall",
        "upperWall",
        "upstreamWall",
    ]:
        if not re.search(r"\b" + name + r"\s*\{", mesh):
            continue
        values = scalar_value(block(patches, name), "value", face_count(mesh, name))
        total.extend(values)
    if not total:  # The cavity has only no-slip walls and no open-boundary flow.
        for name in ["lid", "walls"]:
            total.extend(
                scalar_value(block(patches, name), "value", face_count(mesh, name))
            )
    incoming = -math.fsum(x for x in total if x < 0)
    defect = abs(math.fsum(total))
    return {
        "net_flux_m3_s": math.fsum(total),
        "inflow_m3_s": incoming,
        "relative_boundary_imbalance": defect / max(incoming, 1e-30),
    }


TIME_LINE = re.compile(r"^Time = (" + NUMBER + r")(?:s)?\s*$", re.M)
CONVERGED_LINE = re.compile(r"^SIMPLE solution converged in (\d+) iterations\s*$", re.M)


def iteration_blocks(log):
    """(time name, text) for each steady iteration, from its `Time =` line to the next."""
    marks = list(TIME_LINE.finditer(log))
    return [
        (m[1], log[m.end() : marks[i + 1].start() if i + 1 < len(marks) else len(log)])
        for i, m in enumerate(marks)
    ]


def first_residual(text, field):
    """OpenFOAM's residualControl uses the first solve of a field in an iteration."""
    found = re.search(
        r"Solving for " + field + r", Initial residual = (" + NUMBER + r")", text
    )
    return float(found[1]) if found else None


def residual_trend(blocks, fields):
    """Median first-solve residual over the last tenth of the iterations and over
    the tenth before it: a ratio near 1 at a high level is a stall, not progress."""
    window = max(1, len(blocks) // 10)
    trend = {"window_iterations": window}
    for field in fields:
        values = [first_residual(text, field) for _, text in blocks]
        values = [v for v in values if v is not None]
        last = values[-window:]
        previous = values[-2 * window : -window]
        trend[field] = {
            "median_last_window": statistics.median(last),
            "median_previous_window": statistics.median(previous) if previous else None,
        }
    return trend


def numerical_assessment(case, log, kind):
    # Foundation 13 appends the time unit even for a steady pseudo-iteration.
    blocks = iteration_blocks(log)
    times = [name for name, _ in blocks]
    require(times, "execution.iterations", "no iterations", "CFD-X006")
    require(
        [float(t) for t in times] == list(range(1, len(times) + 1)),
        "execution.iterations",
        "incomplete or nonsequential steady iteration log",
        "CFD-X006",
    )
    latest, final = blocks[-1]
    require(
        (Path(case) / latest / "U").is_file(),
        "fields.time",
        "final field missing",
        "CFD-X006",
    )
    residuals = {}
    required = ["Ux", "Uy", "p"] + (["k", "omega"] if kind == "backstep" else [])
    for field in required:
        value = first_residual(final, field)
        require(
            value is not None,
            f"residuals.{field}",
            "not reported in the final iteration",
            "CFD-X006",
        )
        residuals[field] = value
    local = [abs(float(x)) for x in re.findall(r"sum local = (" + NUMBER + r")", final)]
    require(local, "continuity", "not reported in the final iteration", "CFD-X006")
    flux = flux_balance(case, latest)
    checked_fields = final_field_checks(case, latest, kind)
    reports = CONVERGED_LINE.findall(log)
    require(
        len(reports) <= 1 and all(int(n) == len(times) for n in reports),
        "execution.convergence",
        "convergence report disagrees with the iteration log",
        "CFD-X006",
    )
    converged = bool(reports)
    passed = (
        converged
        and all(v <= 1e-7 for v in residuals.values())
        and local[-1] <= 1e-6
        and flux["relative_boundary_imbalance"] <= 1e-6
    )
    return {
        "passed": passed,
        "solver_reported_convergence": converged,
        "iterations": len(times),
        "final_time_directory": latest,
        "initial_residuals_final_iteration": residuals,
        "residual_trend": residual_trend(blocks, required),
        "reported_local_continuity_final": local[-1],
        "final_fields": checked_fields,
        "turbulence_bounding_log_messages": len(
            re.findall(r"\bbounding (?:k|omega)\b", log)
        ),
        **flux,
        "meaning": "solver residual report plus independently summed stored boundary phi; not physical validation",
    }


def progress(output):
    observed = [m[1] for m in TIME_LINE.finditer((output / "solve.log").read_text())]
    return {
        "started_iterations": len(observed),
        "last_started_iteration": observed[-1] if observed else None,
        "saved_time_directories": sorted(
            (
                p.name
                for p in (output / "case").iterdir()
                if p.is_dir() and re.fullmatch(NUMBER, p.name)
            ),
            key=float,
        ),
        "meaning": "started iterations and saved snapshots; a partial final iteration is not a completed solve",
    }


def run(
    prepared,
    output,
    foam_root,
    timeout_s=600,
    output_mib=256,
    memory_mib=2048,
    stop=None,
):
    require(
        math.isfinite(timeout_s) and 0 < timeout_s <= 3600,
        "limits.timeout_s",
        "expected (0,3600]",
    )
    require(1 <= output_mib <= 2048, "limits.output_mib", "expected 1..2048")
    require(256 <= memory_mib <= 8192, "limits.memory_mib", "expected 256..8192")
    record = check_prepared(prepared)
    output = Path(output).resolve()
    claim_directory(output)
    start = time.monotonic()
    stop = stop or Stop()
    report = {
        "schema_version": "cfd-craft.external-run/0.1",
        "backend": "OpenFOAM Foundation 13",
        "case": record["kind"],
        "case_metadata": record["metadata"],
        "case_sha256": sha256(Path(prepared) / "case.json"),
        "passed": False,
        "execution_status": "incomplete",
        "commands": [],
        "numerical": None,
        "experimental_validation": "not_assessed_by_execution_adapter",
        "limits": {
            "wall_s": timeout_s,
            "output_mib": output_mib,
            "address_space_mib": memory_mib,
        },
        "implementation_sha256": {
            p.name: sha256(p)
            for p in [
                Path(__file__),
                ROOT / "integrations/openfoam_cases.py",
                ROOT / "validation/backstep_data.py",
            ]
        },
    }
    if "initial_state" in record:
        report["initial_state"] = record["initial_state"]
        report["implementation_sha256"]["openfoam_restart.py"] = sha256(
            ROOT / "integrations/openfoam_restart.py"
        )
    try:
        # The copy is what the solver consumes, so it is checked, not the source.
        shutil.copytree(prepared, output / "case", symlinks=True)
        copied = inventory(output / "case")
        copied_case = copied.pop("case.json")
        require(
            copied == record["inputs"]
            and copied_case["sha256"] == report["case_sha256"],
            "case.inputs",
            "changed while being copied",
        )
        binaries, env, identity = runtime(foam_root)
        report["runtime"] = identity
        if "initial_state" in record:
            from openfoam_restart import check_runtime

            check_runtime(record["initial_state"], identity)
        deadline = start + timeout_s

        def command(program, label, *extra):
            args = [str(binaries[program]), "-case", str(output / "case"), *extra]
            try:
                result = execute(
                    args,
                    env,
                    output,
                    label,
                    deadline,
                    output_mib * 1024**2,
                    memory_mib,
                    stop,
                )
            except ExecutionError as exc:
                report["commands"].append(exc.record)
                raise
            report["commands"].append(result)

        command("blockMesh", "mesh")
        command("checkMesh", "check-mesh")
        require(
            "Mesh OK." in (output / "check-mesh.log").read_text(),
            "mesh",
            "mesh quality failed",
            "CFD-X006",
        )
        if "initial_state" in record:
            from openfoam_restart import check_mesh

            check_mesh(
                output / "case",
                record["initial_state"],
                record["metadata"],
                record["kind"],
            )
        command("foamRun", "solve")
        report["numerical"] = numerical_assessment(
            output / "case", (output / "solve.log").read_text(), record["kind"]
        )
        # Export fields from the actual final time, even if convergence failed.
        if record["kind"] == "backstep":
            command(
                "foamPostProcess",
                "wall-stress",
                "-latestTime",
                "-solver",
                "incompressibleFluid",
                "-func",
                "wallStress",
            )
        fields = "(U wallShearStress)" if record["kind"] == "backstep" else "(U)"
        command(
            "foamPostProcess",
            "samples",
            "-latestTime",
            "-fields",
            fields,
            "-func",
            "sampleProfiles",
        )
        sample_checks(
            output / "case",
            report["numerical"]["final_time_directory"],
            record["metadata"],
            record["kind"],
        )
        report["execution_status"] = "completed"
        report["passed"] = report["numerical"]["passed"]
        if not report["passed"]:
            report["error"] = (
                "CFD-X007 numerical: convergence/continuity gate not reached"
            )
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = diagnostic(exc, "execution")
        if "CFD-X004" in str(exc):
            report["execution_status"] = "timeout"
        elif "CFD-X008" in str(exc):
            report["execution_status"] = "cancelled"
        else:
            report["execution_status"] = "failed"
    finally:
        if (output / "solve.log").exists():
            report["progress"] = progress(output)
        report["wall_s"] = time.monotonic() - start
        report["output_bytes_before_manifest"] = disk_bytes(output)
        # A symlink left by a child is evidence of a failed run, not a reason to
        # leave the archive unsealed.
        symlinks = []
        files = inventory(output, symlinks)
        if symlinks:
            report.update(
                passed=False,
                execution_status="failed",
                error=f"CFD-X006 archive.symlinks: {', '.join(symlinks)}",
            )
        write_json(output / "summary.json", report)
        files["summary.json"] = {
            "bytes": (output / "summary.json").stat().st_size,
            "sha256": sha256(output / "summary.json"),
        }
        write_json(
            output / "manifest.json",
            {
                "schema_version": "cfd-craft.external-archive/0.1",
                "files": files,
                "symlinks": symlinks,
            },
        )
        write_json(
            output / "complete.json",
            {"manifest_sha256": sha256(output / "manifest.json")},
        )
    return report


STATUS_CODES = {"timeout": "CFD-X004", "cancelled": "CFD-X008"}
PROGRAMS = {
    "cavity": ["blockMesh", "checkMesh", "foamRun", "foamPostProcess"],
    "backstep": [
        "blockMesh",
        "checkMesh",
        "foamRun",
        "foamPostProcess",
        "foamPostProcess",
    ],
}


def case_file_allowed(name, inputs):
    """A file in an archived case is a consumed input or a known solver output."""
    parts = name.split("/")
    input_directories = {key.split("/")[0] for key in inputs}
    if name == "case.json" or name in inputs:
        return True
    if name.startswith("constant/polyMesh/"):
        return True
    if parts[0] in input_directories:
        return False
    return parts[0] == "postProcessing" or re.fullmatch(NUMBER, parts[0]) is not None


def verify(directory):
    """Check that an archive is complete and internally consistent: hashes, consumed
    inputs, the numerical summary recomputed from the returned log and fields, status,
    return codes, runtime identity and samples. Unkeyed hashes are not tamper-evidence:
    a consistent rewrite of log, fields and summary is not detectable here."""
    try:
        return verified(Path(directory))
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(
            f"CFD-X006 archive: malformed record ({type(exc).__name__}: {exc})"
        ) from exc


def verified(directory):
    complete = json.loads((directory / "complete.json").read_text())
    require(
        complete["manifest_sha256"] == sha256(directory / "manifest.json"),
        "archive.manifest",
        "checksum mismatch",
        "CFD-X006",
    )
    manifest = json.loads((directory / "manifest.json").read_text())
    require(
        manifest.get("schema_version") == "cfd-craft.external-archive/0.1",
        "archive.schema_version",
        "unsupported manifest version",
        "CFD-X006",
    )
    actual = inventory(directory)
    actual.pop("manifest.json")
    actual.pop("complete.json")
    require(
        actual == manifest["files"],
        "archive.files",
        "changed, missing or additional files",
        "CFD-X006",
    )
    report = json.loads((directory / "summary.json").read_text())
    require(
        report.get("schema_version") == "cfd-craft.external-run/0.1",
        "summary.schema_version",
        "unsupported result version",
        "CFD-X006",
    )
    status, error = report["execution_status"], report.get("error")
    if status == "completed":
        require(
            error is None or error.startswith("CFD-X007"),
            "archive.error",
            "a completed run reports another failure",
            "CFD-X006",
        )
        require(
            report["numerical"] is not None
            and [c["program"] for c in report["commands"]] == PROGRAMS[report["case"]]
            and all(c["returncode"] == 0 for c in report["commands"]),
            "archive.commands",
            "a completed run needs every command to have exited 0",
            "CFD-X006",
        )
    elif status in STATUS_CODES:
        require(
            str(error).startswith(STATUS_CODES[status]),
            "archive.error",
            f"{status} needs {STATUS_CODES[status]}",
            "CFD-X006",
        )
    else:
        require(
            status == "failed"
            and error is not None
            and not error.startswith(("CFD-X004", "CFD-X007", "CFD-X008")),
            "archive.execution_status",
            "unknown status or wrong error code",
            "CFD-X006",
        )
    if "runtime" in report:
        require(
            "Using: OpenFOAM-13 " in report["runtime"]["help"],
            "archive.runtime",
            "not a Foundation-13 runtime",
            "CFD-X006",
        )
    case = directory / "case"
    if case.exists():
        require(
            sha256(case / "case.json") == report["case_sha256"],
            "archive.case_sha256",
            "case identity mismatch",
            "CFD-X006",
        )
        definition = json.loads((case / "case.json").read_text())
        require(
            definition.get("initial_state") == report.get("initial_state"),
            "archive.initial_state",
            "summary differs from consumed initial state",
            "CFD-X006",
        )
        if "initial_state" in definition:
            from openfoam_restart import verify_receipt

            verify_receipt(case, definition, report)
        require(
            definition["kind"] == report["case"]
            and definition["metadata"] == report["case_metadata"],
            "archive.case_metadata",
            "summary mismatch",
            "CFD-X006",
        )
        for name, identity in definition["inputs"].items():
            require(
                actual.get("case/" + name) == identity,
                "archive.inputs." + name,
                "consumed input changed",
                "CFD-X006",
            )
        for name in actual:
            if name.startswith("case/"):
                require(
                    case_file_allowed(name[len("case/") :], definition["inputs"]),
                    "archive." + name,
                    "neither a consumed input nor a solver output",
                    "CFD-X006",
                )
    solve_log = directory / "solve.log"
    if solve_log.exists():
        header = solve_log.read_text()[:4000]
        require(
            re.search(r"Version:\s+13\b", header)
            and re.search(r"^Build\s*:\s*13-", header, re.M),
            "archive.solve_log",
            "not written by Foundation 13",
            "CFD-X006",
        )
        if case.exists():
            require(
                progress(directory) == report.get("progress"),
                "archive.progress",
                "summary differs from the log and saved snapshots",
                "CFD-X006",
            )
    if report["numerical"] is not None:
        numerical = numerical_assessment(case, solve_log.read_text(), report["case"])
        require(
            numerical == report["numerical"],
            "archive.numerical",
            "summary differs from returned fields/log",
            "CFD-X006",
        )
        if status == "completed":
            sample_checks(
                case,
                numerical["final_time_directory"],
                report["case_metadata"],
                report["case"],
            )
    expected_pass = (
        status == "completed"
        and report["numerical"] is not None
        and report["numerical"]["passed"]
    )
    require(
        report["passed"] == bool(expected_pass),
        "archive.passed",
        "inconsistent assessment",
        "CFD-X006",
    )
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--case", choices=["cavity", "backstep"], required=True)
    p.add_argument("--level", type=int, default=1)
    p.add_argument("--iterations", type=int, default=3000)
    p.add_argument("--data", type=Path)
    p.add_argument(
        "--mesh-family", choices=["legacy", "wall-resolved"], default="legacy"
    )
    p.add_argument(
        "--solver-profile", choices=["legacy", "simplec", "simple"], default="legacy"
    )
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("prepare-restart")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=6000)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--case", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--foam-root", type=Path, required=True)
    p.add_argument("--timeout-s", type=float, default=600)
    p.add_argument("--output-mib", type=int, default=256)
    p.add_argument("--memory-mib", type=int, default=2048)
    p = sub.add_parser("report")
    p.add_argument("directory", type=Path)
    args = ap.parse_args()
    stop = Stop()
    if args.command == "run":
        # Only a solve is stopped gracefully; prepare and report stop at once.
        for signum in [signal.SIGINT, signal.SIGTERM]:
            signal.signal(signum, stop.signal)
    try:
        if args.command == "prepare":
            result = prepare(
                args.case,
                args.level,
                args.iterations,
                args.output,
                args.data,
                args.mesh_family,
                args.solver_profile,
            )
        elif args.command == "prepare-restart":
            from openfoam_restart import prepare as prepare_restart

            result = prepare_restart(args.source, args.iterations, args.output)
        elif args.command == "run":
            result = run(
                args.case,
                args.output,
                args.foam_root,
                args.timeout_s,
                args.output_mib,
                args.memory_mib,
                stop,
            )
        else:
            result = verify(args.directory)
        print(json.dumps(result, indent=2, allow_nan=False))
        if result.get("passed", True):
            return 0
        # Exit 2: a completed, stopped or verified run without accepted numerical
        # evidence. Exit 1: the execution itself failed (runtime, input, I/O).
        return 1 if result.get("execution_status") == "failed" else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"passed": False, "error": diagnostic(exc, "input")}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
