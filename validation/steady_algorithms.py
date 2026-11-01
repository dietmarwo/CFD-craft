#!/usr/bin/env python3
"""Fixed-point, acceptance and cost gates for the implicit steady algorithms.

Predeclared in docs/ACCURACY_STEADY_PLAN.md (stages P4 and P5a):

- **Same fixed point.** The 24² steady cavity with a momentum scheme runs in the
  explicit mode and in the candidate mode, at the case tolerances and with both
  steady tolerances tightened 10× and 100× (stricter test settings, not looser
  gates). The maximum face-velocity difference between the modes must shrink at
  least 5× per 10× tightening. One pair converged close to round-off is reported.
- **Unchanged acceptance.** Steady cavity, Poiseuille and Couette runs in the
  candidate mode reach the unchanged steady gates.
- **Cost.** Steps and solver time at the case tolerance are recorded; a slower
  candidate is kept and reported.

The fields compared are the archived face velocities. Timings are observations
of this host, not gates.

With ``--case canyon`` (stage P5c, with P5d's tracer) the same gates run on the
development canyon (cases/canyon/wh1-wind270.json) with ``neutral_rans``:

- **Same fixed point.** Without constituents, explicit and candidate runs at the
  case tolerances and tightened 10× and 100×; the maximum differences of the
  face velocities, k and ε, each relative to the explicit field's maximum,
  must each shrink at least 5× per decade. The round-off pair uses residual
  and monitor tolerances of 1e-9: the turbulence-residual probe of `assess`
  has a round-off floor near 2e-10 on this case, so 1e-11 is unreachable.
- **Tracer.** With the case's tracer, both modes must be accepted (mass budget,
  negative mass, steady equation and mass balance gates); the receptor
  differences are reported.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tutorials"))
from common import accepted, run_case, write_report

SCHEMES = {
    "donor_cell": {},
    "van_leer": dict(momentum_advection="limited_upwind", momentum_limiter="van_leer"),
    "second_order_upwind": dict(momentum_advection="second_order_upwind"),
}
TIGHTENING = [1, 10, 100]
SHRINK_PER_DECADE = 5.0
ROUNDOFF_TOLERANCES = dict(residual=1e-11, monitor=1e-9)


def require(ok, field, message):
    if not ok:
        raise ValueError(f"CFD-B008 steady.{field}: {message}")


def cavity(n, algorithm, scheme, factor=1, tolerances=None, threads=1):
    c = json.loads((ROOT / "cases/verification/lid-cavity.json").read_text())
    c["grid"]["cells"] = [n, 2, n]
    c["run"].update(
        mode="steady",
        threads=threads,
        max_steps=200000,
        wall_time_limit_s=1800.0,
    )
    c["numerics"].update(SCHEMES[scheme], pressure_preconditioner="multigrid")
    if algorithm != "explicit":
        c["numerics"]["steady_algorithm"] = algorithm
    if tolerances is None:
        c["numerics"]["steady_residual_tolerance"] /= factor
        c["numerics"]["steady_monitor_tolerance"] /= factor
    else:
        c["numerics"]["steady_residual_tolerance"] = tolerances["residual"]
        c["numerics"]["steady_monitor_tolerance"] = tolerances["monitor"]
    c["name"] = f"cavity-{n}-{scheme}-{algorithm}-x{factor}"
    return c


CANYON_FIELDS = ["velocity", "k", "epsilon"]
CANYON_ROUNDOFF_TOLERANCES = dict(residual=1e-9, monitor=1e-9)


def canyon(algorithm, factor=1, tolerances=None, tracer=False):
    c = json.loads((ROOT / "cases/canyon/wh1-wind270.json").read_text())
    if not tracer:
        for key in ["constituents", "sources", "receptors", "initial_conditions"]:
            c[key] = []
    c["run"].update(threads=1, max_steps=200000, wall_time_limit_s=3600.0)
    if algorithm != "explicit":
        c["numerics"]["steady_algorithm"] = algorithm
    if tolerances is None:
        c["numerics"]["steady_residual_tolerance"] /= factor
        c["numerics"]["steady_monitor_tolerance"] /= factor
    else:
        c["numerics"]["steady_residual_tolerance"] = tolerances["residual"]
        c["numerics"]["steady_monitor_tolerance"] = tolerances["monitor"]
    c["name"] = f"canyon-{'tracer-' if tracer else ''}{algorithm}-x{factor}"
    return c


def field_differences(a, b):
    """Maximum difference per field, relative to the maximum of `a`'s field."""
    out = {}
    for key in CANYON_FIELDS:
        scale = max((abs(x) for x in a[key]), default=0.0)
        require(scale > 0.0, "fields", f"{key} is zero")
        out[key] = difference(a[key], b[key]) / scale
    return out


def canyon_fixed_point(binary, output, algorithm, report):
    def fields(case):
        row, _ = solve(binary, case, output, report)
        return row, json.loads((output / case["name"] / "fields.json").read_text())

    rows = []
    for factor in TIGHTENING:
        explicit, a = fields(canyon("explicit", factor))
        candidate, b = fields(canyon(algorithm, factor))
        rows.append(
            dict(
                tightening=factor,
                explicit=explicit,
                candidate=candidate,
                max_relative_difference=field_differences(a, b),
            )
        )
    gates = {
        key: shrink_gate([r["max_relative_difference"][key] for r in rows])
        for key in CANYON_FIELDS
    }
    explicit, a = fields(canyon("explicit", "roundoff", CANYON_ROUNDOFF_TOLERANCES))
    candidate, b = fields(canyon(algorithm, "roundoff", CANYON_ROUNDOFF_TOLERANCES))
    # Reported, not gated: each run's distance to the round-off explicit solution.
    for row in rows:
        for mode in ["explicit", "candidate"]:
            name = row[mode]["name"]
            x = json.loads((output / name / "fields.json").read_text())
            row[mode]["max_relative_difference_to_roundoff_explicit"] = (
                field_differences(a, x)
            )
    tracer = {}
    for mode in ["explicit", algorithm]:
        case = canyon(mode, tracer=True)
        run = run_case(binary, case, output / case["name"])
        report["runs"].append(run)
        require(accepted(run), case["name"], "run not accepted with unchanged gates")
        s = run["summary"]
        tracer[mode] = dict(
            steps=s["steps"],
            solver_s=s["elapsed_s"],
            relative_budget_defect=s["constituents"][0]["relative_budget_defect"],
            receptors_kg_m3=s["constituents"][0]["receptors_kg_m3"],
        )
    receptors = tracer["explicit"]["receptors_kg_m3"]
    tracer["max_relative_receptor_difference"] = max(
        abs(tracer[algorithm]["receptors_kg_m3"][k] - v) / abs(v)
        for k, v in receptors.items()
    )
    return dict(
        case="cases/canyon/wh1-wind270.json",
        rows=rows,
        shrink_per_decade={k: v[0] for k, v in gates.items()},
        passed=all(v[1] for v in gates.values()),
        roundoff_pair=dict(
            tolerances=CANYON_ROUNDOFF_TOLERANCES,
            explicit=explicit,
            candidate=candidate,
            max_relative_difference=field_differences(a, b),
        ),
        tracer=tracer,
    )


def solve(binary, case, output, report):
    run = run_case(binary, case, output / case["name"])
    report["runs"].append(run)
    require(accepted(run), case["name"], "run not accepted with unchanged gates")
    fields = json.loads((output / case["name"] / "fields.json").read_text())
    s = run["summary"]
    return dict(
        name=case["name"],
        steps=s["steps"],
        solver_s=s["elapsed_s"],
        pressure_iterations=s["pressure_iterations"],
        momentum_solver_iterations=s.get("momentum_solver_iterations"),
        momentum_residual=s["momentum_residual"],
    ), fields["velocity"]


def difference(a, b):
    require(len(a) == len(b), "fields", "face counts differ")
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def shrink_gate(differences):
    """Ratios of successive mode differences; each must be at least 5."""
    shrink = [
        a / max(b, 1e-300) for a, b in zip(differences, differences[1:], strict=False)
    ]
    return shrink, len(shrink) == len(differences) - 1 and all(
        s >= SHRINK_PER_DECADE for s in shrink
    )


def fixed_point(binary, output, algorithm, scheme, n, report):
    rows = []
    for factor in TIGHTENING:
        explicit, u = solve(
            binary, cavity(n, "explicit", scheme, factor), output, report
        )
        candidate, v = solve(
            binary, cavity(n, algorithm, scheme, factor), output, report
        )
        rows.append(
            dict(
                tightening=factor,
                explicit=explicit,
                candidate=candidate,
                max_velocity_difference=difference(u, v),
            )
        )
    shrink, passed = shrink_gate([r["max_velocity_difference"] for r in rows])
    explicit, u = solve(
        binary,
        cavity(n, "explicit", scheme, "roundoff", ROUNDOFF_TOLERANCES),
        output,
        report,
    )
    candidate, v = solve(
        binary,
        cavity(n, algorithm, scheme, "roundoff", ROUNDOFF_TOLERANCES),
        output,
        report,
    )
    # Reported, not gated: each mode's distance to the round-off explicit solution.
    for row, factor in zip(rows, TIGHTENING, strict=True):
        for mode in ["explicit", "candidate"]:
            name = row[mode]["name"]
            fields = json.loads((output / name / "fields.json").read_text())
            row[mode]["max_difference_to_roundoff_explicit"] = difference(
                fields["velocity"], u
            )
    return dict(
        grid=n,
        scheme=scheme,
        rows=rows,
        shrink_per_decade=shrink,
        passed=passed,
        roundoff_pair=dict(
            tolerances=ROUNDOFF_TOLERANCES,
            explicit=explicit,
            candidate=candidate,
            max_velocity_difference=difference(u, v),
        ),
    )


def acceptance(binary, output, algorithm, report):
    rows = []
    for name in ["poiseuille.json", "couette.json"]:
        c = json.loads((ROOT / "cases/verification" / name).read_text())
        c["run"].update(mode="steady", threads=1, max_steps=200000)
        c["numerics"]["steady_algorithm"] = algorithm
        c["name"] = name.removesuffix(".json") + "-" + algorithm
        row, _ = solve(binary, c, output, report)
        rows.append(row)
    for scheme in SCHEMES:
        case = cavity(24, algorithm, scheme)
        case["name"] = "accept-" + case["name"]
        row, _ = solve(binary, case, output, report)
        rows.append(row)
    return rows


def canyon_campaign(binary, output, algorithm):
    output = Path(output)
    output.mkdir()
    report = dict(
        schema_version="cfd-craft.steady-algorithms/0.1",
        algorithm=algorithm,
        case="canyon",
        passed=False,
        runs=[],
        plan=dict(
            fields=CANYON_FIELDS,
            tightening=TIGHTENING,
            shrink_per_decade=SHRINK_PER_DECADE,
            roundoff_tolerances=CANYON_ROUNDOFF_TOLERANCES,
        ),
    )
    write_report(output, report)
    try:
        report["fixed_point"] = canyon_fixed_point(binary, output, algorithm, report)
        require(
            report["fixed_point"]["passed"], "fixed_point", "fixed-point gate failed"
        )
        report["passed"] = True
    except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B008 steady.campaign: {exc}"
        )
    write_report(output, report)
    return report


def campaign(binary, output, algorithm, schemes):
    output = Path(output)
    output.mkdir()
    report = dict(
        schema_version="cfd-craft.steady-algorithms/0.1",
        algorithm=algorithm,
        passed=False,
        runs=[],
        plan=dict(
            grid=24,
            schemes=schemes,
            tightening=TIGHTENING,
            shrink_per_decade=SHRINK_PER_DECADE,
            roundoff_tolerances=ROUNDOFF_TOLERANCES,
            pressure_preconditioner="multigrid",
        ),
    )
    write_report(output, report)
    try:
        report["fixed_point"] = [
            fixed_point(binary, output, algorithm, s, 24, report) for s in schemes
        ]
        report["acceptance"] = acceptance(binary, output, algorithm, report)
        failed = [f["scheme"] for f in report["fixed_point"] if not f["passed"]]
        require(not failed, "fixed_point", f"fixed-point gate failed for {failed}")
        report["passed"] = True
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        IndexError,
        ZeroDivisionError,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = (
            str(exc)
            if str(exc).startswith("CFD-")
            else f"CFD-B008 steady.campaign: {exc}"
        )
    write_report(output, report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--algorithm", default="implicit_viscous")
    ap.add_argument("--schemes", nargs="+", default=["donor_cell", "van_leer"])
    ap.add_argument("--case", choices=["cavity", "canyon"], default="cavity")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    require(
        all(s in SCHEMES for s in args.schemes), "schemes", f"one of {sorted(SCHEMES)}"
    )
    try:
        if args.case == "canyon":
            report = canyon_campaign(args.binary.resolve(), args.output, args.algorithm)
        else:
            report = campaign(
                args.binary.resolve(), args.output, args.algorithm, args.schemes
            )
    except (ValueError, OSError) as exc:
        print(f"CFD-B008 steady.output: {exc}")
        return 1
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
