#!/usr/bin/env python3
"""R3: accepted fixed-flow street responses, virtual rides and held-out inference.

The frozen synthetic plan is written before native execution. No measurement
noise or atmospheric scatter is simulated; uncertainty models are assumptions.
"""

import argparse
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations"))
sys.path.insert(0, str(ROOT / "validation"))
from check_fields import check, flow_state_fingerprint  # noqa:E402
from virtual_ride import read_path, ride  # noqa:E402
from mobile_inference import (
    exhaustive_route_check,
    identifiability,
    infer_sources,
    plain,
    require,
    required_passes,
    route_information,
    select_routes,
)  # noqa:E402


def write(path, value):
    Path(path).write_text(json.dumps(plain(value), indent=2, allow_nan=False) + "\n")


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_id(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value) is not None,
        "wind/ride IDs must be safe filename components (letters, digits, _, . or -)",
    )


def configuration(preset):
    if preset == "canyon":
        case = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
        case["sources"] = []
        for name, a, b in [
            ("street-a", 3.0, 6.0),
            ("street-b", 6.0, 10.0),
            ("street-c", 10.0, 13.0),
        ]:
            case["sources"].append(
                dict(
                    kind="line",
                    id=name,
                    constituent="tracer",
                    from_m=[6.5, a, 0.15],
                    to_m=[6.5, b, 0.15],
                    rate_kg_s_m=1e-8,
                )
            )
        routes = [
            ("train-canyon", [[6.5, 3.5], [6.5, 12.5]]),
            ("train-downwind", [[10.0, 3.5], [10.0, 12.5]]),
            ("heldout-east", [[12.0, 4.5], [12.0, 11.5]]),
            ("heldout-reverse", [[11.0, 11.5], [11.0, 4.5]]),
        ]
        height = 0.4
        station = [10.0, 8.0, 0.4]
        sectors = [270.0, 225.0]
        case["numerics"].update(
            steady_algorithm="implicit_projection",
            momentum_advection="limited_upwind",
            momentum_limiter="van_albada",
            pressure_preconditioner="multigrid",
            pressure_relative_tolerance=0.1,
            max_time_step_s=100.0,
        )
    else:
        case = json.loads(
            (ROOT / "cases/verification/source-response.json").read_text()
        )
        case["flow"] = dict(
            kind="laminar",
            initial_velocity_m_s=[1.0, 0.0, 0.0],
            viscosity_m2_s=1.5e-5,
            acceleration_m_s2=[0.0, 0.0, 0.0],
        )
        case["sources"] = [
            dict(
                kind="line",
                id=f"street-{name}",
                constituent="tracer",
                from_m=[2.0, y, 3.0],
                to_m=[4.0, y, 3.0],
                rate_kg_s_m=1e-8,
            )
            for name, y in zip("abc", [1.5, 3.0, 4.5], strict=True)
        ]
        routes = [
            ("train-near", [[6.0, 0.5], [6.0, 5.5]]),
            ("train-far", [[10.0, 0.5], [10.0, 5.5]]),
            ("heldout-mid", [[8.0, 0.75], [8.0, 5.25]]),
            ("heldout-reverse", [[12.0, 5.25], [12.0, 0.75]]),
        ]
        height = 3.0
        station = [10.0, 3.0, 3.0]
        sectors = [270.0, 250.0]
    case["receptors"] = [
        dict(
            kind="path",
            id=name,
            polyline_m=points,
            height_m=height,
            sample_spacing_m=0.25,
        )
        for name, points in routes
    ]
    case["receptors"].append(
        dict(kind="point", id="reference-station", point_m=station)
    )
    case["receptors"].append(
        dict(
            kind="path",
            id="adjacent-station",
            polyline_m=[[station[0], station[1] - 0.5], [station[0], station[1] + 0.5]],
            height_m=height,
            sample_spacing_m=0.1,
        )
    )
    case["initial_conditions"] = []
    case["run"].update(
        mode="steady",
        threads=1,
        max_steps=40000,
        wall_time_limit_s=45.0,
        memory_limit_mib=1024,
    )
    case["output"].update(fields=True, checkpoint=False, max_total_mib=128)
    winds = []
    for angle in sectors:
        c = copy.deepcopy(case)
        c["name"] = f"mobile-{preset}-wind-{angle:g}"
        if c["flow"]["kind"] == "neutral_rans":
            c["flow"]["direction_deg_from"] = angle
        else:
            rad = math.radians(angle)
            c["flow"]["initial_velocity_m_s"] = [-math.sin(rad), -math.cos(rad), 0.0]
        winds.append(
            dict(
                id=f"wind-{angle:g}",
                request=dict(
                    schema_version="cfd-craft.mobile-response/1",
                    case=c,
                    groups=[
                        dict(id=s["id"], source_ids=[s["id"]]) for s in c["sources"]
                    ],
                    truth_multipliers=[0.7, 1.3, 0.4],
                    campaign_wall_time_limit_s=240.0,
                ),
            )
        )
    return dict(
        schema_version="cfd-craft.mobile-study/1",
        preset=preset,
        winds=winds,
        training_rides=[r[0] for r in routes if r[0].startswith("train")],
        heldout_rides=[r[0] for r in routes if r[0].startswith("heldout")],
        virtual_ride=dict(
            speed_m_s=1.5,
            sampling_interval_s=0.25,
            response_time_s=1.0,
            initial_kg_m3=0.0,
        ),
        noise=dict(sensor_sigma_kg_m3=2e-10, pass_scatter_sigma_kg_m3=1e-9),
        gates=dict(
            rate_relative_error=1e-3,
            heldout_relative_error=1e-3,
            relative_superposition_defect=1e-4,
            route_optimality_normalized_tolerance=2e-6,
        ),
        route_design=dict(
            riding_time_budget_s=36.0,
            setup_time_s=10.0,
            wall_time_limit_s=30.0,
            max_cuts=64,
        ),
        uncertainty=dict(
            relative_half_width=0.1,
            confidence_z=1.96,
            effective_samples_per_pass=5.0,
            systematic_sigma_kg_m3=0.0,
        ),
        experimental_validation="not_validated",
        scope="synthetic truth and idealized steady mean rides; no atmospheric scatter is simulated",
    )


def controlled_winds(plan):
    require(plan["winds"] and len(plan["winds"]) <= 12, "wind campaign budget")
    require(
        plan["virtual_ride"].get("initial_kg_m3") == 0.0,
        "linear ride responses require a zero initial sensor value",
    )
    training, heldout = plan["training_rides"], plan["heldout_rides"]
    require(training and heldout, "training and heldout rides are required")
    require(
        len(set(training + heldout)) == len(training + heldout),
        "training and heldout ride IDs must be unique and disjoint",
    )
    for route in training + heldout + ["adjacent-station"]:
        safe_id(route)
    ids = set()
    expected = None
    truth = None
    for wind in plan["winds"]:
        safe_id(wind["id"])
        require(wind["id"] not in ids, "duplicate wind ID")
        ids.add(wind["id"])
        req = copy.deepcopy(wind["request"])
        c = req["case"]
        c.pop("name", None)
        flow = c["flow"]
        for key in [
            "direction_deg_from",
            "speed_m_s",
            "velocity_m_s",
            "initial_velocity_m_s",
        ]:
            flow.pop(key, None)
        compare = dict(case=c, groups=req["groups"])
        if expected is None:
            expected = compare
            truth = req["truth_multipliers"]
        require(
            compare == expected and req["truth_multipliers"] == truth,
            "wind cases changed geometry,sources,groups,receptors or accuracy controls",
        )


def frozen_flow_identity(folder, native):
    """Recompute that every archive of one wind used the one prepared flow.

    The flow archive, each response column and the truth archive must store
    the same flow arrays as the native identity, and every response must carry
    frozen-flow evidence without flow updates. Column and truth emission rates
    are compared with the archived source rates the independent audit checked.
    """
    expected = native["flow_state_sha256"]
    columns = native["columns"]
    names = ["flow", *[column["archive"] for column in columns], "truth"]
    for name in names:
        safe_id(name)
    require(len(set(names)) == len(names), "duplicate native archive names")
    rates = []
    for name in names:
        archive = folder / name
        fields = json.loads((archive / "fields.json").read_text())
        require(
            flow_state_fingerprint(fields) == expected,
            f"{name} flow differs from the prepared frozen flow",
        )
        if name == "flow":
            continue
        summary = json.loads((archive / "summary.json").read_text())
        frozen = summary.get("frozen_flow") or {}
        require(
            frozen.get("flow_state_sha256") == expected
            and frozen.get("response_flow_updates") == 0,
            f"{name} lacks frozen flow response evidence",
        )
        require(len(summary["constituents"]) == 1, f"{name} constituent count")
        rates.append(summary["constituents"][0]["source_rate_kg_s"])
    reference = [column["integrated_reference_rate_kg_s"] for column in columns]
    truth = native["truth"]["multipliers"]
    expected_rates = [
        *reference,
        math.fsum(q * r for q, r in zip(truth, reference, strict=True)),
    ]
    for name, archived, declared in zip(names[1:], rates, expected_rates, strict=True):
        require(
            math.isfinite(declared)
            and abs(archived - declared) <= 1e-12 * max(abs(declared), 1e-300),
            f"{name} archived source rate differs from the native reference rate",
        )
    return dict(flow_state_sha256=expected, archives=names)


def observed_ride(archive, plan, path_id):
    summary = json.loads((archive / "summary.json").read_text())
    require(
        len(summary["constituents"]) == 1,
        "study driver currently fits one constituent; reuse the same prepared flow separately per bin",
    )
    constituent = summary["constituents"][0]["id"]
    path, provenance = read_path(archive, constituent, path_id)
    result = ride(path, **plan["virtual_ride"])
    result["provenance"] = provenance
    return result


def run(plan, binary, out):
    controlled_winds(plan)
    out.mkdir(parents=True, exist_ok=False)
    write(out / "frozen-study-plan.json", plan)
    report = dict(
        schema_version="cfd-craft.mobile-study-result/1",
        passed=False,
        gate="GR",
        native_runs=[],
        experimental_validation="not_validated",
        frozen_plan_sha256=file_sha256(out / "frozen-study-plan.json"),
        study_driver_sha256=file_sha256(__file__),
    )
    try:
        blocks = []
        truth_values = []
        rows = []
        source_ids = None
        reference_rates = None
        ratios = []
        candidates = []
        samples = {}
        for wind in plan["winds"]:
            wind_id = wind["id"]
            folder = out / wind_id
            request = out / (wind_id + "-request.json")
            write(request, wind["request"])
            entry = dict(
                wind=wind_id,
                exit_code=None,
                native=dict(passed=False, error="native execution not finished"),
                independent_audits=[],
            )
            report["native_runs"].append(entry)
            write(out / "report.json", report)
            timeout_error = None
            with (
                (out / (wind_id + ".stdout")).open("w") as stdout,
                (out / (wind_id + ".stderr")).open("w") as stderr,
            ):
                try:
                    process = subprocess.run(
                        [
                            str(binary.resolve()),
                            str(request.resolve()),
                            str(folder.resolve()),
                        ],
                        stdout=stdout,
                        stderr=stderr,
                        timeout=wind["request"]["campaign_wall_time_limit_s"] + 30,
                        check=False,
                    )
                    entry["exit_code"] = process.returncode
                except subprocess.TimeoutExpired as exc:
                    timeout_error = str(exc)
                    entry["error"] = timeout_error
            native = (
                json.loads((folder / "report.json").read_text())
                if (folder / "report.json").exists()
                else dict(passed=False, error="no native report")
            )
            entry["native"] = native
            write(out / "report.json", report)
            for archive in [
                folder / "flow",
                *[folder / c["archive"] for c in native.get("columns", [])],
                folder / "truth",
            ]:
                if not (archive / "complete.json").exists():
                    continue
                try:
                    audit = check(archive)
                except (ValueError, OSError, KeyError, IndexError, TypeError) as exc:
                    audit = dict(passed=False, error=str(exc))
                write(
                    archive.parent / (archive.name + "-independent-check.json"), audit
                )
                entry["independent_audits"].append(dict(archive=archive.name, **audit))
            require(
                timeout_error is None
                and entry["exit_code"] == 0
                and native["passed"]
                and entry["independent_audits"]
                and all(r["passed"] for r in entry["independent_audits"]),
                f"native response/audit failure for {wind_id}",
            )
            expected_archives = [
                "flow",
                *[c["archive"] for c in native["columns"]],
                "truth",
            ]
            require(
                [r["archive"] for r in entry["independent_audits"]]
                == expected_archives,
                f"missing independent audit of a native archive for {wind_id}",
            )
            entry["frozen_flow_identity"] = frozen_flow_identity(folder, native)
            names = [c["id"] for c in native["columns"]]
            rates = [c["integrated_reference_rate_kg_s"] for c in native["columns"]]
            if source_ids is None:
                source_ids, reference_rates = names, rates
            require(
                names == source_ids and rates == reference_rates,
                "source reference rates/identities changed between winds",
            )
            names_to_run = plan["training_rides"] + plan["heldout_rides"]
            for route in names_to_run:
                responses = [
                    observed_ride(folder / c["archive"], plan, route)
                    for c in native["columns"]
                ]
                truth = observed_ride(folder / "truth", plan, route)
                a = np.array([r["sensor_kg_m3"] for r in responses]).T
                require(
                    all(r["time_s"] == truth["time_s"] for r in responses),
                    "ride sample time mismatch",
                )
                blocks.append(a)
                truth_values.extend(truth["sensor_kg_m3"])
                rows.extend(
                    dict(
                        kind="ride",
                        wind=wind_id,
                        receptor=route,
                        sample_index=j,
                        time_s=t,
                        point_m=point,
                    )
                    for j, (t, point) in enumerate(
                        zip(truth["time_s"], truth["points_m"], strict=True)
                    )
                )
                write(folder / (route + "-virtual-truth.json"), truth)
                samples[(wind_id, route)] = truth
                if route in plan["training_rides"]:
                    candidates.append(
                        dict(
                            id=wind_id + ":" + route,
                            wind=wind_id,
                            ride=route,
                            riding_time_s=truth["time_s"][-1]
                            + plan["route_design"]["setup_time_s"],
                        )
                    )
            s = json.loads((folder / "truth/summary.json").read_text())["constituents"][
                0
            ]
            station = s["receptors_kg_m3"]["reference-station"]
            path = s["paths"]["adjacent-station"]
            virtual = observed_ride(folder / "truth", plan, "adjacent-station")
            sensor_mean = float(
                np.trapezoid(virtual["sensor_kg_m3"], virtual["time_s"])
                / virtual["time_s"][-1]
            )
            ratios.append(
                dict(
                    wind=wind_id,
                    station_kg_m3=station,
                    adjacent_path_mean_kg_m3=path["mean_kg_m3"],
                    sensor_mean_kg_m3=sensor_mean,
                    steady_path_over_station=path["mean_kg_m3"] / station
                    if station > 1e-30
                    else None,
                    sensor_mean_over_station=sensor_mean / station
                    if station > 1e-30
                    else None,
                    interpretation="modeled local-increment ratio, not measured bike/station agreement or total ambient PM",
                )
            )
        a = np.vstack(blocks)
        observed = np.asarray(truth_values)
        truth = np.array(plan["winds"][0]["request"]["truth_multipliers"])
        defect = float(
            np.linalg.norm(a @ truth - observed) / max(np.linalg.norm(observed), 1e-300)
        )
        report["relative_superposition_defect"] = defect
        fit = infer_sources(
            a,
            observed,
            rows,
            source_ids,
            plan["training_rides"],
            plan["heldout_rides"],
            **plan["noise"],
        )
        fit["relative_rate_error"] = float(
            np.linalg.norm(np.array(fit["multipliers"]) - truth) / np.linalg.norm(truth)
        )
        fit["integrated_estimated_rates_kg_s"] = (
            np.array(fit["multipliers"]) * reference_rates
        ).tolist()
        report["inference"] = fit
        report["truth_multipliers"] = truth.tolist()
        report["station_ratios"] = ratios
        info = route_information(a, rows, candidates, **plan["noise"])
        design = plan["route_design"]
        selection = select_routes(
            info,
            candidates,
            design["riding_time_budget_s"],
            max_cuts=design["max_cuts"],
            wall_time_limit_s=design["wall_time_limit_s"],
        )
        exact = exhaustive_route_check(info, candidates, design["riding_time_budget_s"])
        selection["exhaustive_check"] = exact
        selection["normalized_optimality_defect"] = abs(
            (selection["minimum_eigenvalue"] or 0.0)
            - exact["optimum_minimum_eigenvalue"]
        ) / max(selection["information_scale"], 1e-300)
        selected_rows = [
            i
            for i, row in enumerate(rows)
            if any(
                row["wind"] == candidates[j]["wind"]
                and row["receptor"] == candidates[j]["ride"]
                for j in selection["selected_indices"]
            )
        ]
        selection["selected_identifiability"] = (
            identifiability(a[selected_rows], source_ids)
            if selected_rows
            else dict(rank=0, full_column_rank=False)
        )
        report["route_selection"] = selection
        report["route_candidates"] = candidates
        alias = np.column_stack([a, a[:, 1]])
        report["ambiguous_collocated_source_control"] = identifiability(
            alias, source_ids + [source_ids[1] + "-alias"]
        )
        report["ambiguous_collocated_source_control"]["interpretation"] = (
            "the alias deliberately shares exactly the native street-b response; its individual rate is not inferable"
        )
        report["pass_count_planning"] = []
        for wind_id, route in samples:
            if route not in plan["training_rides"]:
                continue
            r = samples[(wind_id, route)]
            mean = float(np.trapezoid(r["sensor_kg_m3"], r["time_s"]) / r["time_s"][-1])
            kwargs = dict(plan["uncertainty"])
            kwargs["effective_samples_per_pass"] = min(
                kwargs["effective_samples_per_pass"], len(r["time_s"])
            )
            report["pass_count_planning"].append(
                dict(
                    wind=wind_id,
                    ride=route,
                    assumed_sensor_mean_kg_m3=mean,
                    **required_passes(mean, **plan["noise"], **kwargs),
                )
            )
        write(
            out / "mobile-response-matrix.json",
            dict(
                schema_version="cfd-craft.ride-response-matrix/1",
                source_ids=source_ids,
                reference_integrated_rates_kg_s=reference_rates,
                rows=rows,
                matrix_kg_m3=a,
                truth_values_kg_m3=observed,
                initial_sensor_kg_m3=plan["virtual_ride"]["initial_kg_m3"],
                virtual_ride=plan["virtual_ride"],
                frozen_plan_sha256=report["frozen_plan_sha256"],
                study_driver_sha256=report["study_driver_sha256"],
                producers=[
                    dict(
                        wind=entry["wind"],
                        **{
                            key: entry["native"][key]
                            for key in [
                                "core_source_sha256",
                                "driver_sha256",
                                "request_sha256",
                                "flow_state_sha256",
                            ]
                        },
                    )
                    for entry in report["native_runs"]
                ],
                noise_assumptions=plan["noise"],
            ),
        )
        with (out / "virtual-observations.csv").open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["wind", "ride", "sample_index", "concentration_kg_m3"])
            writer.writerows(
                [row["wind"], row["receptor"], row["sample_index"], float(v)]
                for row, v in zip(rows, observed, strict=True)
            )
        gates = plan["gates"]
        report["gate_checks"] = dict(
            superposition=defect <= gates["relative_superposition_defect"],
            full_rank_training=fit["individual_rates_unique"],
            rate_recovery=fit["relative_rate_error"] <= gates["rate_relative_error"],
            heldout_recovery=fit["heldout_relative_error"]
            <= gates["heldout_relative_error"],
            ambiguity_reported=report["ambiguous_collocated_source_control"]["nullity"]
            == 1,
            route_integer_optimal=selection["certified"]
            and selection["normalized_optimality_defect"]
            <= gates["route_optimality_normalized_tolerance"]
            and selection["selected_identifiability"]["full_column_rank"],
        )
        report["passed"] = all(report["gate_checks"].values())
    except (
        ValueError,
        OSError,
        KeyError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as exc:
        report["error"] = str(exc)
    write(out / "report.json", report)
    return report


def fit_csv(bundle, observations, train, heldout):
    matrix_bytes = bundle.read_bytes()
    observation_bytes = observations.read_bytes()
    data = json.loads(matrix_bytes)
    lookup = {}
    with io.StringIO(observation_bytes.decode("utf-8"), newline="") as file:
        for row in csv.DictReader(file):
            key = (row["wind"], row["ride"], int(row["sample_index"]))
            require(key not in lookup, "duplicate observed sample key")
            lookup[key] = float(row["concentration_kg_m3"])
    keys = [(r["wind"], r["receptor"], r["sample_index"]) for r in data["rows"]]
    require(len(set(keys)) == len(keys), "duplicate matrix sample key")
    require(set(lookup) == set(keys), "observation rows differ from response identity")
    result = infer_sources(
        data["matrix_kg_m3"],
        [lookup[k] for k in keys],
        data["rows"],
        data["source_ids"],
        train,
        heldout,
        **data["noise_assumptions"],
    )
    result["input_provenance"] = dict(
        matrix_sha256=hashlib.sha256(matrix_bytes).hexdigest(),
        observations_sha256=hashlib.sha256(observation_bytes).hexdigest(),
        frozen_plan_sha256=data.get("frozen_plan_sha256"),
        study_driver_sha256=data.get("study_driver_sha256"),
        virtual_ride=data.get("virtual_ride"),
        producers=data.get("producers"),
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    campaign = sub.add_parser("run")
    campaign.add_argument(
        "--preset", choices=["source-response", "canyon"], default="source-response"
    )
    campaign.add_argument("--config", type=Path)
    campaign.add_argument(
        "--binary", type=Path, default=ROOT / "target/release/examples/mobile_response"
    )
    campaign.add_argument("--output", type=Path, required=True)
    fit = sub.add_parser("fit")
    fit.add_argument("matrix", type=Path)
    fit.add_argument("observations", type=Path)
    fit.add_argument("--train", nargs="+", required=True)
    fit.add_argument("--heldout", nargs="+", required=True)
    fit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            plan = (
                json.loads(args.config.read_text())
                if args.config
                else configuration(args.preset)
            )
            result = run(plan, args.binary, args.output)
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in result.items()
                        if k not in ["native_runs", "inference", "route_selection"]
                    },
                    indent=2,
                )
            )
            return 0 if result["passed"] else 2
        result = fit_csv(args.matrix, args.observations, args.train, args.heldout)
        require(not args.output.exists(), "output already exists")
        write(args.output, result)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"CFD-M003 mobile_inference: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
