#!/usr/bin/env python3
"""Synthetic receipt boundaries and actual Foundation-13 mapping tests.

The synthetic receipts and SST utility fixture are not accepted flow evidence.
Set CFD_OPENFOAM_ROOT for actual cavity/utility/initialization checks.
"""

import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "integrations"), str(ROOT / "validation")]
import openfoam_backend as backend
import openfoam_mapping as mapping
import openfoam_restart as restart
import mapping_equivalence
from audit_openfoam_mesh import audit, cartesian_mesh
from test_resolution import synthetic_data


def synthetic_prepared(root):
    """Receipt-only fixture; dummy mesh bytes, no solver and no physical claim."""
    root = Path(root)
    root.mkdir()
    evidence = root / mapping.EVIDENCE
    evidence.mkdir()
    source_case = evidence / "source/case"
    source_case.parent.mkdir()
    original = backend.prepare("cavity", 1, 50, source_case)
    original_bytes = (source_case / "case.json").read_bytes()
    (source_case / "case.json").unlink()
    snapshot = source_case / "2"
    snapshot.mkdir()
    for name in ["U", "p"]:
        contents = (
            (source_case / "0" / name)
            .read_text()
            .replace("object " + name + ";", "object " + name + '; location "2";')
        )
        (snapshot / name).write_text(contents)
    mesh = source_case / "constant/polyMesh"
    mesh.mkdir()
    for name in restart.MESH_FILES:
        (mesh / name).write_text("synthetic mesh identity fixture\n")
    summary = {
        "case": "cavity",
        "case_sha256": mapping.digest(original_bytes),
        "case_metadata": original["metadata"],
        "execution_status": "completed",
        "passed": True,
        "numerical": {"passed": True, "final_time_directory": "2"},
        "runtime": {"fixture": "synthetic"},
    }
    entries = {
        "case/" + name: entry for name, entry in backend.inventory(source_case).items()
    }
    entries["case/case.json"] = {
        "bytes": len(original_bytes),
        "sha256": mapping.digest(original_bytes),
    }
    backend.write_json(evidence / "source-summary.json", summary)
    entries["summary.json"] = restart.file_identity(evidence / "source-summary.json")
    backend.write_json(evidence / "source-manifest.json", {"files": entries})
    (evidence / "source-case.json").write_bytes(original_bytes)
    manifest_sha = backend.sha256(evidence / "source-manifest.json")
    backend.write_json(
        evidence / "source-audit.json",
        {"passed": True, "numerical_passed": True, "run_manifest_sha256": manifest_sha},
    )
    (evidence / "target").mkdir()
    template = backend.prepare("cavity", 2, 50, evidence / "templates")
    (evidence / "templates/case.json").unlink()
    backend.write_json(evidence / "target-template.json", template)
    for name in template["inputs"]:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(evidence / "templates" / name, destination)
        target = evidence / "target/case" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(destination, target)
    target_mesh = evidence / "target/case/constant/polyMesh"
    target_mesh.mkdir()
    for name in restart.MESH_FILES:
        (target_mesh / name).write_text("synthetic target mesh identity\n")
    backend.write_json(
        evidence / "commands.json",
        [
            {
                "program": p,
                "returncode": 0,
                "arguments": ["-case", "/fixture/mapping_evidence/target/case"]
                + (
                    [
                        "/fixture/mapping_evidence/source/case",
                        "-sourceTime",
                        "2",
                        "-consistent",
                        "-mapMethod",
                        "mapNearest",
                    ]
                    if p == "mapFields"
                    else []
                ),
            }
            for p in ["blockMesh", "checkMesh", "mapFields"]
        ],
    )
    (evidence / "target/check-mesh.log").write_text("Mesh OK.\n")
    (evidence / "target/map.log").write_text(
        "Version: 13\nBuild  : 13-synthetic\nMapping method: mapNearest\ninterpolating U\ninterpolating p\n"
    )
    state = {
        "schema_version": mapping.SCHEMA,
        "method": "mapNearest_internal_only",
        "initial_flux_policy": "solver_initializes_phi_from_new_mesh_U",
        "source_level": 1,
        "source_time": "2",
        "source_manifest_sha256": manifest_sha,
        "source_case_sha256": mapping.digest(original_bytes),
        "source_fields": {n: entries["case/2/" + n] for n in ["U", "p"]},
        "runtime_sha256": restart.identity(summary["runtime"]),
        "mapper_sha256": "a" * 64,
        "limits": {"wall_s": 300, "output_mib": 512, "memory_mib": 2048},
        "preparation_wall_s": 0.1,
        "target_metadata_sha256": restart.identity(template["metadata"]),
        "target_mesh": {
            n: restart.file_identity(target_mesh / n) for n in restart.MESH_FILES
        },
    }
    definition = {
        **template,
        "mesh_initialization": state,
        "inputs": backend.inventory(root),
    }
    backend.write_json(root / "case.json", definition)
    return definition


class Receipts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cfd-mapping-unit-")
        self.root = Path(self.temp.name)
        self.case = self.root / "input"
        self.definition = synthetic_prepared(self.case)

    def tearDown(self):
        self.temp.cleanup()

    def test_known_receipt_is_consistent_but_is_not_flow_evidence(self):
        mapping.validate(self.case, self.definition)
        self.assertEqual(backend.check_prepared(self.case)["level"], 2)

    def test_generated_boundaries_and_dimensions_are_retained(self):
        template = (self.case / "0/U").read_text()
        mapped = self.root / "mapped-U"
        mapped.write_text(
            template.replace(
                "internalField uniform (0 0 0)", "internalField uniform (0.2 0.3 0)"
            ).replace("type noSlip", "type zeroGradient")
        )
        result = mapping.replace_internal(template, mapped, 2304, True, "U")
        self.assertEqual(
            backend.block(result, "boundaryField"),
            backend.block(template, "boundaryField"),
        )
        self.assertIn(
            "internalField uniform (0.20000000000000001 0.29999999999999999 0)", result
        )

    def test_wrong_mapped_field_shape_class_dimensions_and_nonfinite_data_are_rejected(
        self,
    ):
        good = (self.case / "0/U").read_text()
        for change in [
            lambda s: s.replace("volVectorField", "volScalarField"),
            lambda s: s.replace("[0 1 -1 0 0 0 0]", "[0 0 0 0 0 0 0]"),
            lambda s: s.replace("(0 0 0)", "(nan 0 0)", 1),
            lambda s: s.replace("(0 0 0)", "(0 0)", 1),
        ]:
            path = self.root / "mapped"
            path.write_text(change(good))
            with self.assertRaises(ValueError):
                mapping.replace_internal(good, path, 2304, True, "U")

    def test_negative_turbulence_is_rejected(self):
        from openfoam_cases import field

        for name, value in [("k", "-0.1"), ("nut", "-0.1"), ("omega", "0")]:
            template = field(name, "[0 0 0 0 0 0 0]", "1", {})
            path = self.root / name
            path.write_text(template.replace("uniform 1", "uniform " + value))
            with self.assertRaisesRegex(ValueError, "CFD-X014"):
                mapping.replace_internal(template, path, 2304, False, name)

    def test_resealing_an_altered_target_boundary_does_not_bypass_the_receipt(self):
        path = self.case / "0/U"
        path.write_text(path.read_text().replace("type noSlip", "type zeroGradient"))
        self.definition["inputs"]["0/U"] = restart.file_identity(path)
        backend.write_json(self.case / "case.json", self.definition)
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.inputs.0/U"):
            backend.check_prepared(self.case)

    def test_coarse_phi_is_never_accepted_on_the_fine_mesh(self):
        (self.case / "0/phi").write_text("coarse face flux")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.phi"):
            mapping.validate(self.case, self.definition)

    def test_mutually_exclusive_initializations_and_bad_levels_are_rejected(self):
        for mutate in [
            lambda d: d.update(initial_state={}),
            lambda d: d.update(level=3),
            lambda d: d["mesh_initialization"].update(source_level=True),
            lambda d: d["mesh_initialization"].update(
                initial_flux_policy="mapped_coarse_phi"
            ),
        ]:
            definition = copy.deepcopy(self.definition)
            mutate(definition)
            with self.assertRaisesRegex(ValueError, "CFD-X014"):
                mapping.validate(self.case, definition)

    def test_source_must_be_accepted_and_audited(self):
        evidence = self.case / mapping.EVIDENCE
        path = evidence / "source-audit.json"
        record = json.loads(path.read_text())
        record["passed"] = False
        backend.write_json(path, record)
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.audit"):
            mapping.validate(self.case, self.definition)

    def test_snapshot_time_mesh_and_mapper_log_are_bound(self):
        evidence = self.case / mapping.EVIDENCE
        path = evidence / "target/map.log"
        old = path.read_text()
        path.write_text(old.replace("interpolating p", "interpolating q"))
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mapper.fields"):
            mapping.validate(self.case, self.definition)
        path.write_text(old)
        path = evidence / "target/case/constant/polyMesh/points"
        path.write_text("changed mesh")
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh.points"):
            mapping.validate(self.case, self.definition)

    def test_target_controls_cannot_be_changed_with_the_templates(self):
        path = self.case / "system/controlDict"
        changed = path.read_text().replace("deltaT 1;", "deltaT 2;")
        path.write_text(changed)
        (self.case / mapping.EVIDENCE / "templates/system/controlDict").write_text(
            changed
        )
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.target.controls"):
            mapping.validate(self.case, self.definition)

    def test_mapper_method_and_source_time_cannot_be_relabeled(self):
        path = self.case / mapping.EVIDENCE / "commands.json"
        original = json.loads(path.read_text())
        for index, value in [(4, "0"), (7, "interpolate")]:
            changed = copy.deepcopy(original)
            changed[2]["arguments"][index] = value
            backend.write_json(path, changed)
            with self.assertRaisesRegex(
                ValueError, "CFD-X014 mapping.mapper.arguments"
            ):
                mapping.validate(self.case, self.definition)

    def test_invalid_limits_fail_before_claiming_an_output(self):
        for kwargs in [
            {"level": 1},
            {"level": True},
            {"iterations": 1},
            {"timeout_s": 0},
            {"timeout_s": float("nan")},
            {"output_mib": 0},
        ]:
            args = {
                "source": self.root / "missing",
                "level": 2,
                "iterations": 50,
                "output": self.root / "unused",
                "foam_root": self.root,
                **kwargs,
            }
            with self.assertRaisesRegex(ValueError, "CFD-X014"):
                mapping.prepare(**args)
        self.assertFalse((self.root / "unused").exists())

    def test_a_solved_case_cannot_omit_runtime_or_mesh_checks(self):
        report = {"commands": [{"program": "foamRun", "returncode": 0}]}
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.runtime"):
            mapping.verify_receipt(self.case, self.definition, report)
        report["runtime"] = {"fixture": "synthetic"}
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.mesh"):
            mapping.verify_receipt(self.case, self.definition, report)

    def test_a_stopped_experiment_is_evidence_not_an_input_error(self):
        failed = {
            "passed": False,
            "execution_status": "timeout",
            "error": "CFD-X004 execution.deadline: fixture",
        }
        with (
            patch.object(backend, "prepare"),
            patch.object(backend, "run", return_value=failed),
        ):
            report = mapping_equivalence.experiment(
                self.root, self.root / "stopped", 60
            )
        self.assertFalse(report["passed"])
        self.assertNotIn("error", report)
        self.assertIn("CFD-X004", report["stop_reason"])


@unittest.skipUnless(
    os.environ.get("CFD_OPENFOAM_ROOT"), "set CFD_OPENFOAM_ROOT for actual mapping"
)
class ActualMapping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="cfd-real-map-")
        cls.root = Path(cls.temp.name)
        cls.foam = Path(os.environ["CFD_OPENFOAM_ROOT"])
        backend.prepare("cavity", 1, 3000, cls.root / "source-input")
        cls.source = cls.root / "source"
        record = backend.run(
            cls.root / "source-input", cls.source, cls.foam, timeout_s=60
        )
        if not record["passed"]:
            raise ValueError(record.get("error"))
        cls.mapped = cls.root / "mapped"
        cls.definition = mapping.prepare(cls.source, 2, 5000, cls.mapped, cls.foam)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()

    def test_actual_nearest_cells_and_boundaries_match_the_declared_rule(self):
        coarse = cartesian_mesh(self.source / "case")
        fine = cartesian_mesh(self.mapped / mapping.EVIDENCE / "target/case")
        count = self.definition["metadata"]["cells"]
        coords = fine["cell_centres"]
        expected = np.floor(coords[:, 0] * 24).astype(int) + 24 * np.floor(
            coords[:, 1] * 24
        ).astype(int)
        latest = backend.verify(self.source)["numerical"]["final_time_directory"]
        for field in ["U", "p"]:
            values = np.array(
                backend.internal_values(
                    self.source / "case" / latest / field, coarse["cells"], field == "U"
                )
            )
            values = values.reshape(-1, 3) if field == "U" else values
            mapped = np.array(
                backend.internal_values(self.mapped / "0" / field, count, field == "U")
            )
            mapped = mapped.reshape(-1, 3) if field == "U" else mapped
            np.testing.assert_allclose(mapped, values[expected], rtol=0, atol=1e-14)
            template = self.mapped / mapping.EVIDENCE / "templates/0" / field
            self.assertEqual(
                backend.block((self.mapped / "0" / field).read_text(), "boundaryField"),
                backend.block(template.read_text(), "boundaryField"),
            )
        self.assertFalse((self.mapped / "0/phi").exists())

    def test_mapped_run_converges_and_can_supply_a_same_mesh_continuation(self):
        record = backend.run(
            self.mapped, self.work / "run", self.foam, timeout_s=120, output_mib=512
        )
        self.assertTrue(record["passed"], record.get("error"))
        self.assertTrue(backend.verify(self.work / "run")["passed"])
        self.assertTrue(audit(self.work / "run")["passed"])
        definition = restart.prepare(self.work / "run", 50, self.work / "restart")
        self.assertNotIn("mesh_initialization", definition)
        self.assertEqual(
            definition["initial_state"]["source_completed_iterations"],
            record["numerical"]["iterations"],
        )
        continued = backend.run(
            self.work / "restart", self.work / "continued", self.foam, timeout_s=60
        )
        self.assertTrue(continued["passed"])
        self.assertTrue(backend.verify(self.work / "continued")["passed"])
        for parent, name in [
            (self.work / "run", "mapped-parent"),
            (self.work / "continued", "continued-parent"),
        ]:
            with self.assertRaisesRegex(
                ValueError, "CFD-X014 mapping.source.initialization"
            ):
                mapping.prepare(parent, 3, 50, self.work / name, self.foam)
            self.assertFalse((self.work / name).exists())

    def test_occupied_output_and_nonaccepted_source_are_rejected(self):
        output = self.work / "occupied"
        output.mkdir()
        (output / "marker").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "CFD-E062"):
            mapping.prepare(self.source, 2, 5000, output, self.foam)
        self.assertEqual((output / "marker").read_text(), "preserve")
        backend.prepare("cavity", 1, 50, self.work / "cold-input")
        backend.run(
            self.work / "cold-input", self.work / "cold", self.foam, timeout_s=60
        )
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.acceptance"):
            mapping.prepare(
                self.work / "cold", 2, 50, self.work / "not-created", self.foam
            )
        self.assertFalse((self.work / "not-created").exists())

    def test_source_copy_race_is_rejected_without_a_runnable_case(self):
        real = mapping.checked

        def changed(path, entry, field):
            if field == "source.696/U":
                return real(path, {"bytes": 1, "sha256": "0" * 64}, field)
            return real(path, entry, field)

        with patch.object(mapping, "checked", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.696/U"):
                mapping.prepare(self.source, 2, 50, self.work / "failed", self.foam)
        self.assertFalse((self.work / "failed/case.json").exists())
        self.assertTrue((self.work / "failed/mapping-failure.json").exists())

    def test_deadline_and_cancellation_leave_only_nonrunnable_preparation_evidence(
        self,
    ):
        for name, timeout, stop, code in [
            ("deadline", 1e-9, backend.Stop(), "CFD-X004"),
            ("cancelled", 60, backend.Stop(), "CFD-X008"),
        ]:
            if name == "cancelled":
                stop.cancelled = True
            output = self.work / name
            with self.assertRaisesRegex(ValueError, code):
                mapping.prepare(
                    self.source, 2, 50, output, self.foam, timeout_s=timeout, stop=stop
                )
            self.assertFalse((output / "case.json").exists())
            self.assertTrue((output / "mapping-failure.json").exists())

    def test_runtime_mismatch_stops_before_the_solve_and_failure_verifies(self):
        prepared = self.work / "input"
        shutil.copytree(self.mapped, prepared)
        definition = json.loads((prepared / "case.json").read_text())
        definition["mesh_initialization"]["runtime_sha256"] = "0" * 64
        # Direct check is precise; a forged receipt is rejected before execution.
        with self.assertRaisesRegex(ValueError, "CFD-X014 mapping.source.runtime"):
            mapping.validate(prepared, definition)
        binaries, env, identity = backend.runtime(self.foam)
        with patch.object(
            backend,
            "runtime",
            return_value=(binaries, env, {**identity, "fixture": "different runtime"}),
        ):
            result = backend.run(
                self.mapped,
                self.work / "failed",
                self.foam,
                timeout_s=60,
                output_mib=512,
            )
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("CFD-X014 mapping.runtime", result["error"])
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        self.assertEqual(backend.verify(self.work / "failed")["error"], result["error"])

    def test_rebuilt_mesh_mismatch_stops_before_solving_and_failure_verifies(self):
        execute = backend.execute

        def changed(command, env, output, label, *args):
            result = execute(command, env, output, label, *args)
            if label == "mesh":
                with (Path(output) / "case/constant/polyMesh/points").open(
                    "a"
                ) as stream:
                    stream.write("\n")
            return result

        with patch.object(backend, "execute", side_effect=changed):
            result = backend.run(
                self.mapped,
                self.work / "failed",
                self.foam,
                timeout_s=60,
                output_mib=512,
            )
        self.assertEqual(result["execution_status"], "failed")
        self.assertIn("CFD-X014 mapping.mesh.points", result["error"])
        self.assertFalse(any(c["program"] == "foamRun" for c in result["commands"]))
        self.assertEqual(backend.verify(self.work / "failed")["error"], result["error"])

    def test_sst_field_format_and_boundary_preservation_on_actual_meshes(self):
        # Synthetic uniform SST fields, real mesh generation/mapFields only.
        # No accepted turbulent-flow result is fabricated or reported.
        from openfoam_cases import build

        binaries, env, _ = backend.runtime(self.foam)
        for name, level in [("source", 1), ("target", 2)]:
            files, metadata = build(
                "backstep", level, 50, synthetic_data(), "wall-resolved", "simplec"
            )
            case = self.work / name / "case"
            for path, contents in files.items():
                destination = case / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(contents)
            backend.execute(
                [str(binaries["blockMesh"])],
                env,
                case.parent,
                "mesh",
                time.monotonic() + 60,
                256 * 1024**2,
                2048,
                backend.Stop(),
            )
        target = self.work / "target/case"
        mapper = self.foam / "platforms/linux64GccDPInt32Opt/bin/mapFields"
        backend.execute(
            [
                str(mapper),
                str((self.work / "source/case").resolve()),
                "-consistent",
                "-sourceTime",
                "0",
                "-mapMethod",
                "mapNearest",
            ],
            env,
            target.parent,
            "map",
            time.monotonic() + 60,
            256 * 1024**2,
            2048,
            backend.Stop(),
        )
        for name in ["U", "p", "k", "omega", "nut"]:
            template = files["0/" + name]
            combined = mapping.replace_internal(
                template, target / "0" / name, metadata["cells"], name == "U", name
            )
            self.assertEqual(
                backend.block(combined, "boundaryField"),
                backend.block(template, "boundaryField"),
            )
        self.assertFalse((target / "0/phi").exists())


if __name__ == "__main__":
    unittest.main()
