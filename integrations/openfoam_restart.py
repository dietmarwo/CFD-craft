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

SCHEMA = "cfd-craft.openfoam-initial-state/0.1"
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


def require(ok, field, message):
    backend.require(ok, "initial_state." + field, message, "CFD-X012")


def identity(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def file_identity(path):
    return {"bytes": Path(path).stat().st_size, "sha256": backend.sha256(path)}


def fixed_names(kind):
    return FIXED | ({"system/wallStress"} if kind == "backstep" else set())


def local_flux(case, time_name, metadata, kind):
    # These independent readers check face ordering/orientation and every phi.
    from audit_openfoam_mesh import (
        cartesian_mesh,
        patches,
        face_fluxes,
        local_continuity,
    )

    mesh = cartesian_mesh(case)
    require(mesh["cells"] == metadata["cells"], "mesh.cells", "metadata mismatch")
    flux = face_fluxes(
        mesh, patches(mesh, kind), (Path(case) / time_name / "phi").read_text()
    )
    result = local_continuity(
        mesh, flux, metadata.get("height_m", 1), metadata.get("reference_speed_m_s", 1)
    )
    require(
        result["passed"],
        "phi.local_continuity",
        "stored initial flux fails the independent local gate",
    )
    return result


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
            set(state["fixed_inputs"]) == fixed_names(kind),
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
                    set(entry) == {"bytes", "sha256"}
                    and type(entry["bytes"]) is int
                    and entry["bytes"] > 0
                    and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
                    prefix + "." + name,
                    "invalid file identity",
                )
        expected = (
            {"0/" + name for name in fields}
            | fixed_names(kind)
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
        for name, entry in state["fixed_inputs"].items():
            require(
                definition["inputs"][name] == entry,
                "fixed_inputs." + name,
                "physics or mesh recipe changed",
            )
        controls = (Path(case) / "system/controlDict").read_text()
        for key, value in [
            ("startFrom", "startTime"),
            ("startTime", "0"),
            ("endTime", str(definition["max_iterations"])),
            ("deltaT", "1"),
            (
                "writeInterval",
                str(backend.snapshot_interval(definition["max_iterations"])),
            ),
        ]:
            require(
                re.findall(r"\b" + key + r"\s+([^;]+);", controls) == [value],
                "controls." + key,
                "unexpected stage control",
            )
        backend.final_field_checks(case, "0", kind)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(
            f"CFD-X012 initial_state: malformed receipt ({type(exc).__name__})"
        ) from exc


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
    """A rejected runtime/mesh is retained as a consistent failed archive."""
    validate(case, definition)
    state = definition["initial_state"]
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
            report["execution_status"] == "failed"
            and report.get("error") == str(exc)
            and not any(c["program"] == "foamRun" for c in report["commands"]),
            "archive",
            "initial-state mismatch was not rejected before the solve",
        )


def prepare(source, iterations, output):
    require(
        type(iterations) is int and 50 <= iterations <= 20000,
        "iterations",
        "expected 50..20000 per stage",
    )
    source = Path(source)
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
    case = source / "case"
    definition = json.loads((case / "case.json").read_text())
    require(
        backend.sha256(case / "case.json") == report["case_sha256"],
        "source.case",
        "source case changed",
    )
    require(
        definition["generator_sha256"]
        == backend.sha256(backend.ROOT / "integrations/openfoam_cases.py"),
        "source.generator",
        "generator changed; review and prepare a new source run",
    )
    kind = report["case"]
    time_name = report["numerical"]["final_time_directory"]
    backend.final_field_checks(case, time_name, kind)
    local = local_flux(case, time_name, definition["metadata"], kind)
    entries = json.loads(manifest_bytes)["files"]
    fields = {name: entries[f"case/{time_name}/{name}"] for name in FIELDS[kind]}
    mesh = {name: entries["case/constant/polyMesh/" + name] for name in MESH_FILES}
    fixed = {name: definition["inputs"][name] for name in fixed_names(kind)}
    controls = (case / "system/controlDict").read_text()
    require(
        file_identity(case / "system/controlDict")
        == definition["inputs"]["system/controlDict"],
        "source.controls",
        "source changed",
    )
    for key, value in [
        ("endTime", iterations),
        ("writeInterval", backend.snapshot_interval(iterations)),
    ]:
        controls, count = re.subn(
            r"\b" + key + r"\s+[^;]+;", f"{key} {value};", controls
        )
        require(count == 1, "controls." + key, "missing/duplicate stage control")
    previous = definition.get("initial_state") or {}
    state = {
        "schema_version": SCHEMA,
        "method": "same_mesh_steady_field_restart",
        "source_manifest_sha256": manifest_sha,
        "source_case_sha256": report["case_sha256"],
        "source_time": time_name,
        "source_completed_iterations": previous.get("source_completed_iterations", 0)
        + report["numerical"]["iterations"],
        "source_numerical_passed": report["passed"],
        "source_runtime_sha256": identity(report["runtime"]),
        "source_fields": fields,
        "source_mesh": mesh,
        "fixed_inputs": fixed,
        "source_local_continuity": local,
        "meaning": "local steady pseudo-time and solver history reset; cumulative iterations count work, not physical time or bitwise continuation",
    }
    output = Path(output)
    backend.claim_directory(output)
    for name in fixed:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case / name, destination)
    (output / "0").mkdir()
    for name in fields:
        shutil.copyfile(case / time_name / name, output / "0" / name)
    (output / "system/controlDict").write_text(controls)
    expected = {
        **fixed,
        **{"0/" + name: entry for name, entry in fields.items()},
        "system/controlDict": {
            "bytes": len(controls.encode()),
            "sha256": hashlib.sha256(controls.encode()).hexdigest(),
        },
    }
    require(
        backend.inventory(output) == expected,
        "inputs",
        "source changed while copying or copied bytes differ",
    )
    definition.update(max_iterations=iterations, inputs=expected, initial_state=state)
    backend.write_json(output / "case.json", definition)
    return backend.check_prepared(output)
