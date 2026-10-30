"""Verified same-mesh field initialization for bounded steady solve stages.

Local pseudo-time starts at zero. This does not restore transient time history
or internal linear/nonlinear solver caches, and does not map between meshes.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

import openfoam_backend as backend
from openfoam_cases import control_dict

SCHEMA = "cfd-craft.openfoam-initial-state/0.2"
MESH_FILES = ("points", "faces", "owner", "neighbour", "boundary")
FIELDS = {
    "cavity": ("U", "p", "phi"),
    "backstep": ("U", "p", "k", "omega", "nut", "phi"),
}
FIXED = {
    "constant/momentumTransport",
    "constant/physicalProperties",
    "system/blockMeshDict",
    "system/fvSchemes",
    "system/fvSolution",
    "system/sampleProfiles",
}


class IneligibleSource(ValueError):
    """A verified, completed source whose stored state cannot seed a stage."""


def require(ok, field, message, error=ValueError):
    if not ok:
        raise error(f"CFD-X012 initial_state.{field}: {message}")


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def file_identity(path):
    return {"bytes": Path(path).stat().st_size, "sha256": backend.sha256(path)}


def fixed_names(kind):
    return sorted(FIXED | ({"system/wallStress"} if kind == "backstep" else set()))


def local_flux(case, time_name, metadata, kind, text=None):
    """The stored phi must pass the auditor's independent local gate (1e-4).

    The result also reports the auditor's scale-free measures; they decide
    nothing here.
    """
    from audit_openfoam_mesh import (
        cartesian_mesh,
        patches,
        face_fluxes,
        local_continuity,
    )

    mesh = cartesian_mesh(case)
    require(mesh["cells"] == metadata["cells"], "mesh.cells", "metadata mismatch")
    if text is None:
        text = (Path(case) / time_name / "phi").read_text()
    flux = face_fluxes(mesh, patches(mesh, kind), text)
    result = local_continuity(
        mesh, flux, metadata.get("height_m", 1), metadata.get("reference_speed_m_s", 1)
    )
    require(
        result["passed"],
        "phi.local_continuity",
        "stored initial flux fails the independent local gate "
        f"({result['maximum_abs_divergence_h_over_u']:.3g} > {result['target_max']:g})",
        IneligibleSource,
    )
    return result


def header_location(path):
    with Path(path).open(errors="replace") as stream:
        head = stream.read(4096)
    match = re.search(r"\blocation\s+\"([^\"]*)\"\s*;", head)
    return match[1] if match else None


def validate(case, definition):
    """Check a sealed initial-state receipt against the actual consumed inputs."""
    if "initial_state" not in definition:
        return
    state = definition["initial_state"]
    try:
        require(isinstance(state, dict), "schema_version", "expected a receipt object")
        require(
            state["schema_version"] == SCHEMA
            and state["method"] == "same_mesh_steady_field_restart",
            "schema_version",
            "unsupported initialization",
        )
        for name in [
            "source_manifest_sha256",
            "source_case_sha256",
            "source_runtime_sha256",
            "source_metadata_sha256",
        ]:
            require(
                isinstance(state[name], str)
                and re.fullmatch(r"[0-9a-f]{64}", state[name]),
                name,
                "invalid identity",
            )
        require(
            isinstance(state["source_time"], str)
            and re.fullmatch(r"[1-9]\d*", state["source_time"]),
            "source_time",
            "expected a completed steady snapshot",
        )
        require(
            type(state["source_completed_iterations"]) is int
            and state["source_completed_iterations"] >= int(state["source_time"]),
            "source_completed_iterations",
            "invalid work count",
        )
        require(
            type(state["source_numerical_passed"]) is bool,
            "source_numerical_passed",
            "expected boolean",
        )
        require(
            identity(definition["metadata"]) == state["source_metadata_sha256"],
            "source_metadata_sha256",
            "case metadata differs from the source",
        )
        kind = definition["kind"]
        require(
            type(definition["max_iterations"]) is int
            and 50 <= definition["max_iterations"] <= 20000,
            "iterations",
            "expected 50..20000 per stage",
        )
        fields = state["source_fields"]
        require(
            set(fields) == set(FIELDS[kind]),
            "source_fields",
            "missing or unexpected restart field",
        )
        require(
            set(state["source_mesh"]) == set(MESH_FILES),
            "source_mesh",
            "incomplete mesh identity",
        )
        require(
            set(state["fixed_inputs"]) == set(fixed_names(kind)),
            "fixed_inputs",
            "unexpected physics inputs",
        )
        for prefix, entries in [
            ("source_fields", fields),
            ("source_mesh", state["source_mesh"]),
            ("fixed_inputs", state["fixed_inputs"]),
        ]:
            for name, entry in entries.items():
                require(
                    isinstance(entry, dict)
                    and set(entry) == {"bytes", "sha256"}
                    and type(entry["bytes"]) is int
                    and entry["bytes"] > 0
                    and isinstance(entry["sha256"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
                    prefix + "." + name,
                    "invalid file identity",
                )
        expected = (
            {"0/" + name for name in fields}
            | set(fixed_names(kind))
            | {"system/controlDict"}
        )
        require(
            set(definition["inputs"]) == expected,
            "inputs",
            "restart input set mismatch",
        )
        for name, entry in fields.items():
            require(
                definition["inputs"]["0/" + name] == entry,
                "source_fields." + name,
                "copied field differs from the source identity",
            )
            require(
                header_location(Path(case) / "0" / name) == state["source_time"],
                "source_fields." + name,
                "copied field does not come from the source's final snapshot",
            )
        for name, entry in state["fixed_inputs"].items():
            require(
                definition["inputs"][name] == entry,
                "fixed_inputs." + name,
                "physics or mesh recipe changed",
            )
        iterations = definition["max_iterations"]
        controls = (Path(case) / "system/controlDict").read_text()
        interval = re.findall(r"\bwriteInterval\s+(\d+);", controls)
        require(
            len(interval) == 1
            and 50 <= int(interval[0]) <= 250
            and iterations % int(interval[0]) == 0
            and controls
            == stage_controls(state["source_controls"], iterations, int(interval[0])),
            "controls",
            "stage controls are not the source's with a new endTime and a final-writing "
            "writeInterval between 50 and 250",
        )
        require(
            generated_controls(state["source_controls"]),
            "source_controls",
            "the source did not use the generated steady controls",
        )
        backend.final_field_checks(case, "0", kind)
    except KeyError as exc:
        raise ValueError(f"CFD-X012 initial_state.{exc.args[0]}: missing") from exc
    except (TypeError, AttributeError, IndexError) as exc:
        raise ValueError(
            f"CFD-X012 initial_state: malformed receipt ({type(exc).__name__})"
        ) from exc


def generated_controls(text):
    """True for this generator's steady controls with some endTime and cadence."""
    end = re.findall(r"\bendTime\s+(\d+);", text)
    interval = re.findall(r"\bwriteInterval\s+(\d+);", text)
    return (
        len(end) == 1
        and len(interval) == 1
        and text == control_dict(int(end[0]), int(interval[0]))
    )


def text(data, name):
    try:
        return data.decode()
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"CFD-X012 initial_state.source.{name}: not a text file"
        ) from exc


def stage_controls(source_controls, iterations, interval):
    """The source's controls with only endTime and writeInterval replaced."""
    text = source_controls
    for key, value in [("endTime", iterations), ("writeInterval", interval)]:
        text, count = re.subn(r"\b" + key + r"\s+[^;]+;", f"{key} {value};", text)
        require(count == 1, "controls." + key, "missing or duplicated stage control")
    return text


def check_runtime(state, runtime):
    require(
        identity(runtime) == state["source_runtime_sha256"],
        "runtime",
        "runtime differs from the source stage",
    )


def check_mesh(case, state, metadata, kind):
    for name, entry in state["source_mesh"].items():
        require(
            file_identity(Path(case) / "constant/polyMesh" / name) == entry,
            "mesh." + name,
            "rebuilt mesh differs from the source mesh",
        )
    return local_flux(case, "0", metadata, kind)


def verify_receipt(case, definition, report):
    """Recheck runtime and mesh; a pre-solve rejection is a consistent failure.

    A stage archive that fails these checks is an invalid archive, never an
    ineligible source, even when the failing check is the local flux gate.
    """
    try:
        archive_receipt(case, definition, report)
    except IneligibleSource as exc:
        raise ValueError(str(exc)) from exc


def archive_receipt(case, definition, report):
    validate(case, definition)
    state = definition["initial_state"]
    if any(c["program"] == "foamRun" for c in report["commands"]):
        # A solved stage passed both checks before its solve: both are mandatory.
        require("runtime" in report, "runtime", "solved stage lacks its runtime")
        check_runtime(state, report["runtime"])
        require(
            any(
                c["program"] == "checkMesh" and c["returncode"] == 0
                for c in report["commands"]
            )
            and "Mesh OK." in (Path(case).parent / "check-mesh.log").read_text(),
            "mesh",
            "solved stage lacks a passed mesh check",
        )
        check_mesh(case, state, definition["metadata"], definition["kind"])
        return
    try:
        if "runtime" in report:
            check_runtime(state, report["runtime"])
        ready_mesh = any(
            c["program"] == "checkMesh" and c["returncode"] == 0
            for c in report["commands"]
        )
        if (
            ready_mesh
            and "Mesh OK." in (Path(case).parent / "check-mesh.log").read_text()
        ):
            check_mesh(case, state, definition["metadata"], definition["kind"])
    except ValueError as exc:
        require(
            report["execution_status"] == "failed" and report.get("error") == str(exc),
            "archive",
            "initial-state mismatch was not rejected before the solve",
        )


def read_checked(path, entry, field):
    data = Path(path).read_bytes()
    require(
        len(data) == entry["bytes"]
        and hashlib.sha256(data).hexdigest() == entry["sha256"],
        field,
        "source changed after verification",
    )
    return data


def prepare(source, iterations, output):
    require(
        type(iterations) is int and 50 <= iterations <= 20000,
        "iterations",
        "expected 50..20000 per stage",
    )
    interval = backend.snapshot_interval(iterations)
    source, output = Path(source), Path(output)
    try:
        return prepared_stage(source, iterations, interval, output)
    except KeyError as exc:
        raise ValueError(
            f"CFD-X012 initial_state.source.{exc.args[0]}: missing from the source"
        ) from exc
    except OSError as exc:
        name = Path(exc.filename).name if exc.filename else "archive"
        raise ValueError(f"CFD-X012 initial_state.source: cannot read {name}") from exc


def prepared_stage(source, iterations, interval, output):
    # Each file is read once; its verified bytes are what is checked and used.
    manifest_bytes = (source / "manifest.json").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    report = backend.verify(source)
    require(
        report["execution_status"] == "completed" and report["numerical"] is not None,
        "source.execution_status",
        "only completed stages are eligible; failed/timeout/cancelled snapshots are not",
    )
    require(
        backend.sha256(source / "manifest.json") == manifest_sha,
        "source.manifest",
        "source changed during verification",
    )
    entries = json.loads(manifest_bytes)["files"]
    case = source / "case"
    definition = json.loads(
        read_checked(case / "case.json", entries["case/case.json"], "source.case")
    )
    require(
        entries["case/case.json"]["sha256"] == report["case_sha256"],
        "source.case",
        "source case differs from its summary",
    )
    require(
        definition["generator_sha256"]
        == backend.sha256(backend.ROOT / "integrations/openfoam_cases.py"),
        "source.generator",
        "generator changed; review and prepare a new source run",
    )
    kind = report["case"]
    time_name = report["numerical"]["final_time_directory"]
    source_controls = text(
        read_checked(
            case / "system/controlDict",
            definition["inputs"]["system/controlDict"],
            "source.controls",
        ),
        "controlDict",
    )
    require(
        generated_controls(source_controls)
        and re.findall(r"\bendTime\s+(\d+);", source_controls)
        == [str(definition["max_iterations"])],
        "source.controls",
        "source did not use the generated steady controls",
    )
    controls = stage_controls(source_controls, iterations, interval)
    backend.final_field_checks(case, time_name, kind)
    phi = read_checked(
        case / time_name / "phi", entries[f"case/{time_name}/phi"], "source.phi"
    )
    local = local_flux(case, time_name, definition["metadata"], kind, text(phi, "phi"))
    fields = {name: entries[f"case/{time_name}/{name}"] for name in FIELDS[kind]}
    mesh = {name: entries["case/constant/polyMesh/" + name] for name in MESH_FILES}
    fixed = {name: definition["inputs"][name] for name in fixed_names(kind)}
    previous = definition.get("initial_state") or {}
    state = {
        "schema_version": SCHEMA,
        "method": "same_mesh_steady_field_restart",
        "source_manifest_sha256": manifest_sha,
        "source_case_sha256": report["case_sha256"],
        "source_metadata_sha256": identity(definition["metadata"]),
        "source_time": time_name,
        "source_completed_iterations": previous.get("source_completed_iterations", 0)
        + report["numerical"]["iterations"],
        "source_numerical_passed": report["passed"],
        "source_runtime_sha256": identity(report["runtime"]),
        "source_fields": fields,
        "source_mesh": mesh,
        "fixed_inputs": fixed,
        "source_controls": source_controls,
        "source_local_continuity": local,
        "meaning": "local steady pseudo-time and solver history reset; cumulative iterations count work, not physical time or bitwise continuation",
    }
    backend.claim_directory(output)
    try:
        try:
            copy_inputs(case, time_name, fixed, fields, controls, output)
        except OSError as exc:
            name = Path(exc.filename).name if exc.filename else "input"
            raise ValueError(
                f"CFD-X012 initial_state.inputs: cannot write {name}"
            ) from exc
        expected = dict(
            sorted(
                {
                    **fixed,
                    **{"0/" + name: entry for name, entry in fields.items()},
                    "system/controlDict": {
                        "bytes": len(controls.encode()),
                        "sha256": hashlib.sha256(controls.encode()).hexdigest(),
                    },
                }.items()
            )
        )
        require(
            backend.inventory(output) == expected,
            "inputs",
            "source changed while copying or copied bytes differ",
        )
        definition.update(
            max_iterations=iterations, inputs=expected, initial_state=state
        )
        # This is now a same-mesh stage. Its parent case hash binds the mapped
        # initialization; the new final-field receipt replaces that old receipt.
        definition.pop("mesh_initialization", None)
        backend.write_json(output / "case.json", definition)
        return backend.check_prepared(output)
    except BaseException:
        # The directory was created by this call; leave no partial stage behind.
        shutil.rmtree(output, ignore_errors=True)
        raise


def copy_inputs(case, time_name, fixed, fields, controls, output):
    for name in fixed:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case / name, destination)
    (output / "0").mkdir()
    for name in fields:
        shutil.copyfile(case / time_name / name, output / "0" / name)
    (output / "system/controlDict").write_text(controls)
