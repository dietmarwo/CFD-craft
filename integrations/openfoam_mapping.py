"""Bounded mapNearest volume-field initialization on a finer generated mesh.

Target boundary dictionaries stay generated. Phi is not transferred: this is
new-mesh initialization, not a conservative same-mesh field restart.
"""

import hashlib
import json
import math
import re
import time
from pathlib import Path

import numpy as np

import openfoam_backend as backend
import openfoam_restart as restart
from openfoam_cases import build, control_dict

SCHEMA = "cfd-craft.mesh-initialization/0.2"
EVIDENCE = "mapping_evidence"


def require(ok, field, message):
    backend.require(ok, "mapping." + field, message, "CFD-X014")


def coded(exc, field):
    """The CFD-X014 form of an exception raised while reading mapping evidence."""
    if isinstance(exc, KeyError):
        key = exc.args[0] if exc.args else "receipt"
        return ValueError(f"CFD-X014 mapping.{key}: missing")
    if isinstance(exc, (TypeError, AttributeError, IndexError, OverflowError)):
        return ValueError(
            f"CFD-X014 mapping.{field}: malformed record ({type(exc).__name__})"
        )
    if isinstance(exc, OSError):
        name = Path(exc.filename).name if exc.filename else "evidence"
        return ValueError(f"CFD-X014 mapping.{field}: cannot access {name}")
    if isinstance(exc, ValueError) and str(exc).startswith("CFD-"):
        return exc
    if isinstance(exc, ValueError):
        return ValueError(f"CFD-X014 mapping.{field}: invalid text/JSON evidence")
    return exc


def finite(value):
    """A JSON number that is not a bool and fits a float."""
    if type(value) is int:
        return abs(value) <= 2**53
    return type(value) is float and math.isfinite(value)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def text(data, field):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"CFD-X014 mapping.{field}: non-text input") from exc


def checked(path, entry, field, message="source changed after verification"):
    data = Path(path).read_bytes()
    require({"bytes": len(data), "sha256": digest(data)} == entry, field, message)
    return data


# Source cells, nearest centre first, among which each target cell's source must be.
CANDIDATES = 27


def nearest_replay(
    evidence, source_time, fields, source_cells, target_cells, candidates=CANDIDATES
):
    """Bind every consumed value to one nearby source cell, for all fields at once.

    Foundation 13's mapNearest gives each target cell the values of one source
    cell, the same cell for every field. On a uniformly refined mesh that is the
    cell with the nearest centre; on graded meshes its search can end at a nearby
    cell instead. The replay, with the independent mesh reader, requires for each
    target cell one source cell among the `candidates` nearest centres whose
    values equal the consumed values in every field, and reports how far down
    that list it was. This ties the consumed fields to the receipt's source
    fields rather than to the mapper's own output.
    """
    from audit_openfoam_mesh import cartesian_mesh
    from scipy.spatial import cKDTree

    source = cartesian_mesh(evidence / "source/case")
    target = cartesian_mesh(evidence / "target/case")
    require(
        source["cells"] == source_cells and target["cells"] == target_cells,
        "mesh.cells",
        "stored source/target meshes differ from the receipt's cell counts",
    )
    count = min(candidates, source_cells)
    distance, index = cKDTree(source["cell_centres"]).query(
        target["cell_centres"], k=count
    )
    distance, index = (
        distance.reshape(target_cells, -1),
        index.reshape(target_cells, -1),
    )
    match = np.ones(index.shape, bool)
    for name in fields:
        width = 3 if name == "U" else 1

        def values(path, cells):
            found = np.array(backend.internal_values(path, cells, name == "U"))
            return np.broadcast_to(found.reshape(-1, width), (cells, width))

        coarse = values(evidence / "source/case" / source_time / name, source_cells)
        mapped = values(evidence / "target/case/0" / name, target_cells)
        for rank in range(count):
            match[:, rank] &= np.all(coarse[index[:, rank]] == mapped, axis=1)
    found = match.any(axis=1)
    used = distance[np.arange(target_cells), np.argmax(match, axis=1)]
    # Rank by distance: equidistant centres share a rank.
    rank = 1 + np.sum(distance < used[:, None] * (1 - 1e-9), axis=1)
    ratio = used / np.maximum(distance[:, 0], 1e-300)
    stats = {
        "candidates": count,
        "nearest_source": int(np.sum(found & (rank == 1))),
        "other_candidate": int(np.sum(found & (rank > 1))),
        "maximum_rank": int(rank[found].max()) if found.any() else None,
        "maximum_distance_ratio": float(ratio[found].max()) if found.any() else None,
    }
    require(
        bool(found.all()),
        "mapper.values",
        f"{int((~found).sum())} target cells match no single source cell among "
        f"their {count} nearest in every field ({json.dumps(stats)})",
    )
    return stats


def volume_fields(kind):
    return [name for name in restart.FIELDS[kind] if name != "phi"]


def replace_internal(template, mapped, count, vector, field):
    # The exact generated prefix/suffix, including all BCs, are retained.
    mapped_text = Path(mapped).read_text()
    for pattern in [
        r"\bclass\s+(\w+)\s*;",
        r"\bobject\s+(\w+)\s*;",
        r"\bdimensions\s*(\[[^]]+\])\s*;",
    ]:
        wanted, actual = re.search(pattern, template), re.search(pattern, mapped_text)
        require(
            wanted is not None
            and actual is not None
            and "".join(wanted[1].split()) == "".join(actual[1].split()),
            field + ".header",
            "mapped field class/object/dimensions differ from template",
        )
    match = re.search(r"\binternalField\s+uniform\s+[^;]+;", template)
    require(
        match is not None and len(re.findall(r"\binternalField\b", template)) == 1,
        field,
        "expected one generated uniform internal field",
    )
    values = backend.internal_values(mapped, count, vector)
    require(
        field not in {"k", "nut"} or min(values) >= 0,
        field,
        "negative mapped turbulence",
    )
    require(field != "omega" or min(values) > 0, field, "nonpositive mapped omega")
    width = 3 if vector else 1
    if len(values) == width:
        value = (
            "(" + " ".join(f"{v:.17g}" for v in values) + ")"
            if vector
            else f"{values[0]:.17g}"
        )
        internal = f"internalField uniform {value};"
    else:
        rows = (
            [
                "(" + " ".join(f"{v:.17g}" for v in values[i : i + 3]) + ")"
                for i in range(0, len(values), 3)
            ]
            if vector
            else [f"{v:.17g}" for v in values]
        )
        internal = (
            f"internalField nonuniform List<{'vector' if vector else 'scalar'}>\n{count}\n(\n"
            + "\n".join(rows)
            + "\n);"
        )
    return template[: match.start()] + internal + template[match.end() :]


def check_runtime(state, runtime):
    require(
        restart.identity(runtime) == state["runtime_sha256"],
        "runtime",
        "runtime differs from mapping preparation",
    )


def check_mesh(case, state):
    for name, entry in state["target_mesh"].items():
        require(
            restart.file_identity(Path(case) / "constant/polyMesh" / name) == entry,
            "mesh." + name,
            "rebuilt target mesh differs from mapping mesh",
        )


def validate(case, definition):
    try:
        validate_inputs(Path(case), definition)
    except Exception as exc:
        error = coded(exc, "inputs")
        if error is exc:
            raise
        raise error from exc


def validate_inputs(case, definition):
    state = definition["mesh_initialization"]
    require(
        isinstance(state, dict) and "initial_state" not in definition,
        "receipt",
        "one initialization method is required",
    )
    limits = state["limits"]
    require(
        finite(limits["wall_s"])
        and 0 < limits["wall_s"] <= 3600
        and type(limits["output_mib"]) is int
        and 1 <= limits["output_mib"] <= 2048
        and type(limits["memory_mib"]) is int
        and 256 <= limits["memory_mib"] <= 8192,
        "limits",
        "invalid preparation limits",
    )
    require(
        finite(state["preparation_wall_s"]) and state["preparation_wall_s"] >= 0,
        "preparation_wall_s",
        "invalid preparation work record",
    )
    require(
        type(definition["max_iterations"]) is int
        and 50 <= definition["max_iterations"] <= 20000,
        "max_iterations",
        "expected 50..20000",
    )
    require(
        isinstance(state["source_time"], str)
        and re.fullmatch(r"[1-9][0-9]*", state["source_time"]) is not None,
        "source_time",
        "expected a positive iteration directory name",
    )
    require(
        state["schema_version"] == SCHEMA
        and state["method"] == "mapNearest_internal_only",
        "schema_version",
        "unsupported receipt schema or mapping method",
    )
    require(
        state["initial_flux_policy"] == "solver_initializes_phi_from_new_mesh_U",
        "phi",
        "unsupported flux policy",
    )
    require(not (case / "0/phi").exists(), "phi", "coarse phi must not be transferred")
    require(
        type(state["source_level"]) is int
        and type(definition["level"]) is int
        and 1 <= state["source_level"] < 3
        and definition["level"] == state["source_level"] + 1,
        "level",
        "expected one finer supported level",
    )
    require(
        restart.identity(definition["metadata"]) == state["target_metadata_sha256"],
        "target_metadata",
        "metadata mismatch",
    )
    evidence = case / EVIDENCE
    original = json.loads((evidence / "source-case.json").read_text())
    summary = json.loads((evidence / "source-summary.json").read_text())
    manifest_bytes = (evidence / "source-manifest.json").read_bytes()
    require(
        digest(manifest_bytes) == state["source_manifest_sha256"],
        "source.manifest",
        "identity mismatch",
    )
    manifest = json.loads(manifest_bytes)["files"]
    require(
        restart.file_identity(evidence / "source-summary.json")
        == manifest["summary.json"],
        "source.summary",
        "summary differs from source manifest",
    )
    require(
        backend.sha256(evidence / "source-case.json")
        == state["source_case_sha256"]
        == manifest["case/case.json"]["sha256"]
        == summary["case_sha256"],
        "source.case",
        "identity mismatch",
    )
    require(
        original["kind"] == definition["kind"] == summary["case"]
        and original["level"] == state["source_level"]
        and original["metadata"] == summary["case_metadata"],
        "source.metadata",
        "source case mismatch",
    )
    require(
        original["generator_sha256"] == definition["generator_sha256"],
        "source.generator",
        "generator differs",
    )
    for name, entry in original["inputs"].items():
        require(
            entry == manifest["case/" + name]
            and restart.file_identity(evidence / "source/case" / name) == entry,
            "source.inputs." + name,
            "source input identity mismatch",
        )
    for name in restart.MESH_FILES:
        require(
            restart.file_identity(evidence / "source/case/constant/polyMesh" / name)
            == manifest["case/constant/polyMesh/" + name],
            "source.mesh." + name,
            "source mesh identity mismatch",
        )
    require(
        "initial_state" not in original and "mesh_initialization" not in original,
        "source.initialization",
        "only cold-generated sources are supported",
    )
    require(
        summary["execution_status"] == "completed"
        and summary["passed"] is True
        and summary["numerical"]["passed"] is True
        and state["source_time"] == summary["numerical"]["final_time_directory"],
        "source.acceptance",
        "source is not an accepted final snapshot",
    )
    require(
        type(state["source_iterations"]) is int
        and state["source_iterations"] == summary["numerical"]["iterations"],
        "source_iterations",
        "source work differs from the source summary",
    )
    audit = json.loads((evidence / "source-audit.json").read_text())
    require(
        audit["passed"] is True
        and audit["numerical_passed"] is True
        and audit["run_manifest_sha256"] == state["source_manifest_sha256"],
        "source.audit",
        "source audit did not pass",
    )
    require(
        restart.identity(summary["runtime"]) == state["runtime_sha256"],
        "source.runtime",
        "identity mismatch",
    )
    fields = volume_fields(definition["kind"])
    require(
        set(state["source_fields"]) == set(fields)
        and set(state["target_mesh"]) == set(restart.MESH_FILES),
        "receipt",
        "incomplete field/mesh identities",
    )
    for name, entry in state["source_fields"].items():
        require(
            entry == manifest[f"case/{state['source_time']}/{name}"]
            and restart.file_identity(
                evidence / "source/case" / state["source_time"] / name
            )
            == entry,
            "source.fields." + name,
            "identity mismatch",
        )
        require(
            restart.header_location(
                evidence / "source/case" / state["source_time"] / name
            )
            == state["source_time"],
            "source.fields." + name,
            "snapshot time mismatch",
        )
    commands = json.loads((evidence / "commands.json").read_text())
    require(
        [r["program"] for r in commands] == ["blockMesh", "checkMesh", "mapFields"]
        and all(r["returncode"] == 0 for r in commands),
        "commands",
        "preparation commands did not succeed",
    )
    arguments = commands[2]["arguments"]
    require(
        len(arguments) == 8
        and arguments[0] == "-case"
        and arguments[3:]
        == [
            "-sourceTime",
            state["source_time"],
            "-consistent",
            "-mapMethod",
            "mapNearest",
        ],
        "mapper.arguments",
        "mapping method or source time differs from receipt",
    )
    require(
        tuple(Path(arguments[1]).parts[-3:]) == (EVIDENCE, "target", "case")
        and tuple(Path(arguments[2]).parts[-3:]) == (EVIDENCE, "source", "case")
        and Path(arguments[1]).parents[1] == Path(arguments[2]).parents[1],
        "mapper.arguments",
        "wrong source/target work case",
    )
    require(
        all(c["arguments"] == arguments[:2] for c in commands[:2]),
        "mapper.arguments",
        "mesh and mapping commands use different targets",
    )
    require(
        "Mesh OK." in (evidence / "target/check-mesh.log").read_text(),
        "mesh",
        "target mesh check failed",
    )
    mapper_log = (evidence / "target/map.log").read_text()
    require(
        "Mapping method: mapNearest" in mapper_log,
        "mapper.method",
        "mapping log reports another method",
    )
    require(
        re.search(r"Version:\s+13\b", mapper_log)
        and re.search(r"^Build\s*:\s*13-", mapper_log, re.M),
        "mapper",
        "not a Foundation-13 mapping log",
    )
    require(
        set(re.findall(r"\binterpolating\s+(\w+)", mapper_log)) == set(fields),
        "mapper.fields",
        "not every expected volume field was mapped",
    )
    require(
        re.fullmatch(r"[0-9a-f]{64}", state["mapper_sha256"]),
        "mapper.identity",
        "invalid mapper identity",
    )
    template = json.loads((evidence / "target-template.json").read_text())
    for name in [
        "constant/momentumTransport",
        "constant/physicalProperties",
        "system/fvSchemes",
        "system/fvSolution",
    ]:
        require(
            template["inputs"][name] == original["inputs"][name],
            "target.recipe." + name,
            "physics or numerical profile changed",
        )
    require(
        (case / "system/controlDict").read_text()
        == control_dict(
            definition["max_iterations"],
            backend.snapshot_interval(definition["max_iterations"]),
        ),
        "target.controls",
        "target steady controls differ from generator",
    )
    require(
        template["metadata"] == definition["metadata"]
        and template["kind"] == definition["kind"]
        and template["level"] == definition["level"]
        and template["max_iterations"] == definition["max_iterations"],
        "target.template",
        "target definition mismatch",
    )
    require(
        {p for p in definition["inputs"] if not p.startswith(EVIDENCE + "/")}
        == set(template["inputs"]),
        "inputs",
        "unexpected prepared fields",
    )
    for name, entry in template["inputs"].items():
        data = checked(
            evidence / "templates" / name,
            entry,
            "templates." + name,
            "stored template differs from the target template record",
        )
        if name.startswith("0/"):
            field = name[2:]
            require(field in fields, "fields", "unexpected volume field")
            expected = replace_internal(
                text(data, name),
                evidence / "target/case" / name,
                definition["metadata"]["cells"],
                field == "U",
                field,
            ).encode()
        else:
            expected = data
        require(
            (case / name).read_bytes() == expected,
            "inputs." + name,
            "mapped internal field or generated boundary/control changed",
        )
    for name, entry in state["target_mesh"].items():
        require(
            restart.file_identity(evidence / "target/case/constant/polyMesh" / name)
            == entry,
            "mesh." + name,
            "mapping mesh identity mismatch",
        )
    require(
        nearest_replay(
            evidence,
            state["source_time"],
            fields,
            original["metadata"]["cells"],
            definition["metadata"]["cells"],
        )
        == state["nearest_replay"],
        "mapper.replay",
        "replay statistics differ from the receipt",
    )
    backend.final_field_checks(case, "0", definition["kind"])


def verify_receipt(case, definition, report):
    """Recheck runtime and rebuilt mesh; a pre-solve rejection is a consistent failure."""
    try:
        archive_receipt(Path(case), definition, report)
    except Exception as exc:
        error = coded(exc, "archive")
        if error is exc:
            raise
        raise error from exc


def archive_receipt(case, definition, report):
    validate(case, definition)
    state = definition["mesh_initialization"]

    def mesh_passed():
        return (
            any(
                c["program"] == "checkMesh" and c["returncode"] == 0
                for c in report["commands"]
            )
            and "Mesh OK." in (case.parent / "check-mesh.log").read_text()
        )

    if any(c["program"] == "foamRun" for c in report["commands"]):
        # A solved case passed both checks before its solve: both are mandatory.
        require("runtime" in report, "runtime", "solved case lacks runtime")
        check_runtime(state, report["runtime"])
        require(mesh_passed(), "mesh", "solved case lacks a passed mesh check")
        check_mesh(case, state)
        return
    try:
        if "runtime" in report:
            check_runtime(state, report["runtime"])
        # A failed mesh check stops the run with its own error before this check.
        if mesh_passed():
            check_mesh(case, state)
    except ValueError as exc:
        require(
            report["execution_status"] == "failed" and report.get("error") == str(exc),
            "archive",
            "mismatch was not rejected before solving",
        )


def prepare(
    source,
    level,
    iterations,
    output,
    foam_root,
    data=None,
    timeout_s=300,
    output_mib=512,
    memory_mib=2048,
    stop=None,
):
    require(
        type(level) is int and level in {2, 3}, "level", "expected target level 2 or 3"
    )
    require(
        type(iterations) is int and 50 <= iterations <= 20000,
        "iterations",
        "expected 50..20000",
    )
    interval = backend.snapshot_interval(iterations)
    require(
        finite(timeout_s) and 0 < timeout_s <= 3600,
        "timeout_s",
        "expected (0,3600]",
    )
    require(
        type(output_mib) is int
        and 1 <= output_mib <= 2048
        and type(memory_mib) is int
        and 256 <= memory_mib <= 8192,
        "limits",
        "invalid output/memory budget",
    )
    source, output = Path(source), Path(output)
    try:
        return prepared(
            source,
            level,
            iterations,
            output,
            # Utilities run inside the target case: a relative root is resolved here.
            Path(foam_root).resolve(),
            data,
            timeout_s,
            output_mib,
            memory_mib,
            stop or backend.Stop(),
            interval,
        )
    except Exception as exc:
        error = coded(exc, "inputs")
        if error is exc:
            raise
        raise error from exc


def prepared(
    source,
    level,
    iterations,
    output,
    foam_root,
    data,
    timeout_s,
    output_mib,
    memory_mib,
    stop,
    interval,
):
    from audit_openfoam_mesh import audit

    start = time.monotonic()
    manifest_bytes = (source / "manifest.json").read_bytes()
    parent = backend.verify(source)
    require(
        parent["execution_status"] == "completed" and parent["passed"] is True,
        "source.acceptance",
        "source must be numerically accepted",
    )
    entries = json.loads(manifest_bytes)["files"]
    require(
        backend.sha256(source / "manifest.json") == digest(manifest_bytes),
        "source.manifest",
        "source changed",
    )
    original_bytes = checked(
        source / "case/case.json", entries["case/case.json"], "source.case"
    )
    original = json.loads(original_bytes)
    require(
        "initial_state" not in original and "mesh_initialization" not in original,
        "source.initialization",
        "initial release accepts cold-generated sources only",
    )
    require(
        original["level"] + 1 == level
        and original["generator_sha256"]
        == backend.sha256(backend.ROOT / "integrations/openfoam_cases.py"),
        "source.level",
        "expected current generator and one-level refinement",
    )
    kind, meta = original["kind"], original["metadata"]
    require(
        kind != "backstep" or data is not None,
        "data",
        "backstep mapping needs verified measurements",
    )
    dataset = backend.load(data) if kind == "backstep" else None
    family, profile = (
        meta.get("mesh_family", "legacy"),
        meta.get("solver_profile", "legacy"),
    )
    source_files, source_meta = build(
        kind, original["level"], original["max_iterations"], dataset, family, profile
    )
    source_files["system/controlDict"] = control_dict(
        original["max_iterations"],
        backend.snapshot_interval(original["max_iterations"]),
    )
    require(
        meta == source_meta and set(original["inputs"]) == set(source_files),
        "source.recipe",
        "source differs from a generated cold recipe",
    )
    for name, content in source_files.items():
        require(
            original["inputs"][name]
            == {"bytes": len(content.encode()), "sha256": digest(content.encode())},
            "source.recipe." + name,
            "source physics or boundary definition differs from the generator",
        )
    audited = audit(source)
    require(
        audited["passed"] is True and audited["numerical_passed"] is True,
        "source.audit",
        "source independent audit must pass",
    )
    binaries, env, runtime = backend.runtime(foam_root)
    require(
        restart.identity(runtime) == restart.identity(parent["runtime"]),
        "runtime",
        "runtime differs from source",
    )
    mapper = foam_root / "platforms/linux64GccDPInt32Opt/bin/mapFields"
    require(mapper.is_file(), "mapper", "missing Foundation-13 mapFields")
    mapper_sha = backend.sha256(mapper)
    fields = volume_fields(kind)
    latest = parent["numerical"]["final_time_directory"]
    target_files, target_meta = build(kind, level, iterations, dataset, family, profile)
    target_files["system/controlDict"] = control_dict(iterations, interval)
    backend.claim_directory(output)
    evidence = output / EVIDENCE
    evidence.mkdir()
    commands = []
    try:
        source_copy = evidence / "source/case"
        names = (
            list(original["inputs"])
            + ["constant/polyMesh/" + n for n in restart.MESH_FILES]
            + [latest + "/" + n for n in fields]
        )
        for name in sorted(names):
            blob = checked(
                source / "case" / name, entries["case/" + name], "source." + name
            )
            destination = source_copy / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(blob)
        target_job = evidence / "target"
        target_case = target_job / "case"
        for name, content in target_files.items():
            for parent_dir in [target_case, evidence / "templates"]:
                destination = parent_dir / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content)
        template = {
            "kind": kind,
            "level": level,
            "max_iterations": iterations,
            "metadata": target_meta,
            "inputs": backend.inventory(target_case),
        }
        backend.write_json(evidence / "target-template.json", template)
        (evidence / "source-case.json").write_bytes(original_bytes)
        (evidence / "source-manifest.json").write_bytes(manifest_bytes)
        (evidence / "source-summary.json").write_bytes(
            checked(source / "summary.json", entries["summary.json"], "source.summary")
        )
        backend.write_json(evidence / "source-audit.json", audited)
        deadline = start + timeout_s

        def command(program, label, *args):
            remaining = output_mib * 1024**2 - (
                backend.disk_bytes(output) - backend.disk_bytes(target_job)
            )
            require(
                remaining > backend.disk_bytes(target_job),
                "output",
                "preparation output budget exceeded",
            )
            try:
                record = backend.execute(
                    [str(program), "-case", str(target_case.resolve()), *args],
                    env,
                    target_job,
                    label,
                    deadline,
                    remaining,
                    memory_mib,
                    stop,
                )
            except backend.ExecutionError as exc:
                commands.append(exc.record)
                raise
            commands.append(record)

        command(binaries["blockMesh"], "mesh")
        command(binaries["checkMesh"], "check-mesh")
        require(
            "Mesh OK." in (target_job / "check-mesh.log").read_text(),
            "mesh",
            "target mesh check failed",
        )
        command(
            mapper,
            "map",
            str(source_copy.resolve()),
            "-sourceTime",
            latest,
            "-consistent",
            "-mapMethod",
            "mapNearest",
        )
        backend.write_json(evidence / "commands.json", commands)
        require(
            backend.sha256(mapper) == mapper_sha,
            "mapper.identity",
            "mapper changed during preparation",
        )
        replay = nearest_replay(
            evidence, latest, fields, meta["cells"], target_meta["cells"]
        )
        # A cancellation after the last utility still leaves no runnable case.
        backend.require(not stop.cancelled, "execution.cancel", "cancelled", "CFD-X008")
        for name, content in target_files.items():
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name.startswith("0/"):
                field = name[2:]
                content = replace_internal(
                    content,
                    target_case / name,
                    target_meta["cells"],
                    field == "U",
                    field,
                )
            destination.write_text(content)
        state = {
            "schema_version": SCHEMA,
            "method": "mapNearest_internal_only",
            "initial_flux_policy": "solver_initializes_phi_from_new_mesh_U",
            "source_manifest_sha256": digest(manifest_bytes),
            "source_case_sha256": digest(original_bytes),
            "source_level": original["level"],
            "source_time": latest,
            "source_iterations": parent["numerical"]["iterations"],
            "source_fields": {n: entries[f"case/{latest}/{n}"] for n in fields},
            "target_metadata_sha256": restart.identity(target_meta),
            "target_mesh": {
                n: restart.file_identity(target_case / "constant/polyMesh" / n)
                for n in restart.MESH_FILES
            },
            "runtime_sha256": restart.identity(runtime),
            "mapper_sha256": mapper_sha,
            "nearest_replay": replay,
            "limits": {
                "wall_s": timeout_s,
                "output_mib": output_mib,
                "memory_mib": memory_mib,
            },
            "preparation_wall_s": time.monotonic() - start,
            "meaning": "nearest-cell volume initialization only; target BCs retained; new phi and solver history; not conservation, fine-grid convergence or physical qualification",
        }
        require(
            backend.disk_bytes(output) < output_mib * 1024**2,
            "output",
            "preparation output budget exceeded",
        )
        definition = {
            "schema_version": "cfd-craft.openfoam-case/0.1",
            "backend": "OpenFOAM Foundation 13",
            "kind": kind,
            "level": level,
            "max_iterations": iterations,
            "metadata": target_meta,
            "generator_sha256": backend.sha256(
                backend.ROOT / "integrations/openfoam_cases.py"
            ),
            "mesh_initialization": state,
            "inputs": backend.inventory(output),
        }
        backend.write_json(output / "case.json", definition)
        return backend.check_prepared(output)
    except BaseException as exc:
        (output / "case.json").unlink(missing_ok=True)
        error = coded(exc, "inputs") if isinstance(exc, Exception) else exc
        backend.write_json(evidence / "commands.json", commands)
        backend.write_json(
            output / "mapping-failure.json",
            {
                "preparation_passed": False,
                "error": backend.diagnostic(error, "mapping"),
                "meaning": "non-runnable preparation evidence",
            },
        )
        if error is exc:
            raise
        raise error from exc
