#!/usr/bin/env python3
"""Strict spatial-pair evaluation. No permissive defaults for a missing protocol."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from check_fields import require


def read_csv(path, column):
    result = {}
    for row in csv.DictReader(Path(path).open()):
        key = (row["case_id"], row["wall"], row["sample_id"])
        require(key not in result, "duplicate sample ID")
        v = float(row[column])
        require(math.isfinite(v) and v >= 0, "invalid concentration")
        result[key] = v
    require(result, "no samples")
    return result


def evaluate(protocol, observations, predictions):
    require(protocol["status"] == "frozen", "experimental protocol is not frozen")
    require(
        protocol["pairing"] == "wall taps paired in space, not arc maxima",
        "wrong pairing",
    )
    require(
        protocol["observation_sha256"]
        == hashlib.sha256(Path(observations).read_bytes()).hexdigest(),
        "observations do not match frozen hash",
    )
    o = read_csv(observations, "observed_c_plus")
    p = read_csv(predictions, "predicted_c_plus")
    require(o.keys() == p.keys(), "missing or extra predictions")
    expected = {tuple(x) for x in protocol["required_sample_ids"]}
    require(expected == set(o), "sample set does not match frozen protocol")
    t = protocol["thresholds"]
    require(t is not None, "thresholds unavailable")
    groups = {}
    for case, wall, _ in o:
        groups[(case, wall)] = None
    result = {}
    for group in [None, *sorted(groups)]:
        keys = [k for k in o if group is None or k[:2] == group]
        a = [o[k] for k in keys]
        b = [p[k] for k in keys]
        n = len(a)
        mean_o = math.fsum(a) / n
        mean_p = math.fsum(b) / n
        require(
            mean_o > 0 and mean_p > 0, "zero-mean group cannot support these metrics"
        )
        fb = 2 * (mean_o - mean_p) / (mean_o + mean_p)
        nmse = (
            math.fsum((x - y) ** 2 for x, y in zip(a, b, strict=True))
            / n
            / (mean_o * mean_p)
        )
        # Zero observations are counted separately, never divided by zero.
        positive = [(x, y) for x, y in zip(a, b, strict=True) if x > 0]
        fac2 = (
            math.fsum(0.5 <= y / x <= 2 for x, y in positive) / len(positive)
            if positive
            else None
        )
        nmae = math.fsum(abs(x - y) for x, y in zip(a, b, strict=True)) / math.fsum(a)
        passed = (
            abs(fb) <= t["abs_fb_max"]
            and nmse <= t["nmse_max"]
            and fac2 is not None
            and fac2 >= t["fac2_min"]
            and nmae <= t["nmae_max"]
        )
        result["all" if group is None else "/".join(group)] = dict(
            samples=n,
            zero_observations=n - len(positive),
            fb=fb,
            nmse=nmse,
            fac2_positive_observations=fac2,
            nmae=nmae,
            passed=passed,
        )
    return dict(
        status="evaluated",
        passed=all(x["passed"] for x in result.values()),
        groups=result,
        interpretation="dataset-specific spatial criteria; no Hanna-Chang arc-maximum compliance claim",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", required=True, type=Path)
    ap.add_argument("--observations", type=Path)
    ap.add_argument("--predictions", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    try:
        protocol = json.loads(args.protocol.read_text())
        if protocol["status"] != "frozen":
            report = dict(
                status=protocol["status"],
                passed=False,
                reason=protocol.get("missing", ["protocol is not frozen"]),
            )
        else:
            require(args.observations and args.predictions, "data paths required")
            report = evaluate(protocol, args.observations, args.predictions)
    except (ValueError, KeyError, OSError) as e:
        report = dict(status="invalid", passed=False, error=str(e))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
