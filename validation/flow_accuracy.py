#!/usr/bin/env python3
"""Exact periodic shear decay: independent spatial and temporal refinement.

An explicit, checksummed initial-state checkpoint supplies sin(2*pi*z), using
the public restart contract. It is a generated verification state, not evidence
of a previous physical run.
"""

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tutorials"))
from common import run_case, accepted, write_report, require


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, default=ROOT / "target/release/cfd-craft")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    args.output.mkdir()
    report = dict(schema_version="cfd-craft.flow-accuracy/0.1", passed=False, runs=[])
    try:
        base = json.loads((ROOT / "cases/verification/poiseuille.json").read_text())
        base["boundaries"] = dict(x="periodic", y="periodic", z="periodic")
        base["flow"]["acceleration_m_s2"] = [0.0, 0.0, 0.0]
        base["run"]["threads"] = 1

        def trial(n, dt, label, discrete):
            c = copy.deepcopy(base)
            c["grid"]["cells"] = [2, 2, n]
            c["name"] = label
            c["numerics"]["max_time_step_s"] = dt
            c["run"]["end_time_s"] = 1e-9
            seed = run_case(args.binary, c, args.output / (label + "-seed"))
            report["runs"].append(seed)
            require(accepted(seed), "seed state generation")
            wrapper = json.loads(
                (args.output / (label + "-seed") / "checkpoint.json").read_text()
            )
            state = json.loads(wrapper["payload"])
            state["time_s"] = 0.0
            state["steps"] = 0
            state["monitor_history"] = []
            velocity = []
            dims = [2, 2, n]
            for a in range(3):
                for k in range(n):
                    for j in range(2):
                        for i in range(2):
                            z = (k + (0 if a == 2 else 0.5)) / n
                            velocity.append(
                                math.sin(2 * math.pi * z) if a == 0 else 0.0
                            )
            state["velocity"] = velocity
            wrapper["payload"] = json.dumps(state, separators=(",", ":"))
            wrapper["payload_sha256"] = hashlib.sha256(
                wrapper["payload"].encode()
            ).hexdigest()
            checkpoint = args.output / (label + "-initial.json")
            checkpoint.write_text(json.dumps(wrapper))
            c["run"]["end_time_s"] = 0.1
            run = run_case(args.binary, c, args.output / label, restart=checkpoint)
            report["runs"].append(run)
            require(accepted(run), "shear decay solve")
            s = json.loads((args.output / label / "fields.json").read_text())
            u = np.array(s["velocity"][: 4 * n]).reshape(n, 2, 2).mean(axis=(1, 2))
            rate = (
                (4 * 0.1 * math.sin(math.pi / n) ** 2 * n * n)
                if discrete
                else (4 * math.pi**2 * 0.1)
            )
            ref = np.sin(2 * math.pi * (np.arange(n) + 0.5) / n) * math.exp(-rate * 0.1)
            return float(np.linalg.norm(u - ref) / np.linalg.norm(ref))

        ns = [8, 16, 32]
        errors = [trial(n, 1e-4, f"space-{n}", False) for n in ns]
        ps = math.log(errors[1] / errors[2]) / math.log(2)
        dts = [0.01, 0.005, 0.0025]
        te = [trial(8, dt, f"time-{i}", True) for i, dt in enumerate(dts)]
        pt = math.log(te[1] / te[2]) / math.log(2)
        report.update(
            spatial=dict(grids=ns, errors=errors, observed_order=ps, target_min=1.8),
            temporal=dict(steps_s=dts, errors=te, observed_order=pt, target_min=1.8),
            scope="periodic viscous shear; pressure has zero gradient. This does not establish general open-boundary pressure temporal order.",
        )
        require(ps >= 1.8 and pt >= 1.8, "declared convergence order not recovered")
        report["passed"] = True
    except Exception as e:
        report["error"] = str(e)
    finally:
        write_report(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
