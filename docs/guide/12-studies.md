# Many runs
<!-- check: rel=1e-4 -->

At the end of this chapter you have turned one run into a function that can
fail, built a response matrix and run two study scripts. You need `cfd-craft`,
a checkout with its Python requirements, and the Python binding.

## Setup

Commands run from the root of a checkout with `cfd-craft` on `PATH`. All runs
use `source-response.json`: three volume sources, six receptors, `linear_upwind`.

```bash
mkdir -p runs
```

Outputs on this page are real. The documentation check compares floating-point
numbers with a relative tolerance of 1e-4; everything else must match exactly.

## A fallible objective

An optimizer or a parameter study calls the solver as a function. It writes a
new case, runs it into a new directory, returns a named receptor of a
numerically accepted result, and raises an exception for everything else.

```python
import json
import subprocess
from pathlib import Path
ACCEPTED = {"steady_discrete_solution", "transient_interval_completed"}
BASE = json.loads(Path("cases/verification/source-response.json").read_text())

def objective(name, multipliers, max_steps=6000):
    """R1 in kg/m3 for three source-rate multipliers; raises unless accepted."""
    case = json.loads(json.dumps(BASE))
    case["name"] = name
    case["run"].update(threads=1, max_steps=max_steps)
    for source, factor in zip(case["sources"], multipliers, strict=True):
        source["rate_kg_s_m3"] *= factor
    Path(f"runs/{name}.json").write_text(json.dumps(case, indent=2))
    command = ["cfd-craft", "run", f"runs/{name}.json", "--output", f"runs/{name}"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if done.returncode == 1:
        raise RuntimeError("rejected input or execution error")
    summary = json.loads(done.stdout)
    if summary["assessment"] not in ACCEPTED:
        raise RuntimeError(f'{summary["termination"]} / {summary["assessment"]}')
    return summary["constituents"][0]["receptors_kg_m3"]["R1"]

trials = [("equal", (1, 1, 1), 6000), ("shifted", (0.7, 1.3, 1.0), 6000)]
trials += [("cut-short", (1, 1, 1), 5), ("negative", (1, -1, 1), 6000)]
for name, multipliers, steps in trials:
    try:
        print(name, f"{objective(name, multipliers, steps) * 1e9:.6g} micrograms/m3")
    except RuntimeError as error:
        print(name, "failed:", error)
```

```text
equal 18.6825 micrograms/m3
shifted 21.5709 micrograms/m3
cut-short failed: iteration_limit / incomplete
negative failed: rejected input or execution error
```

Two trials return a value. The run that hit its step limit and the case with
a negative rate are recorded as failures. Never turn a failure into a large
finite number: an optimizer would count it as a solved point.

## Unit responses and superposition

With `linear_upwind` and a fixed flow, receptor values are linear in the source
rates ([chapter 5](05-sources-receptors-transport.md)). One run per source
gives one column of a response matrix G; any rates q then give G q. The runs
are short, so this block uses the binding:

```python
import json
import cfd_craft as cfd
base = json.load(open("cases/verification/source-response.json"))

def receptors(sources):
    result = cfd.simulate(dict(base, sources=sources))
    if result["assessment"] != "steady_discrete_solution":
        raise RuntimeError(result["assessment"])
    values = result["constituents"][0]["receptors_kg_m3"]
    return [values[receptor["id"]] for receptor in base["receptors"]]

columns = [receptors([source]) for source in base["sources"]]
rates = [0.7, 1.3, 0.9]
pairs = zip(base["sources"], rates, strict=True)
computed = receptors([dict(s, rate_kg_s_m3=s["rate_kg_s_m3"] * q) for s, q in pairs])
predicted = [sum(q * c[row] for q, c in zip(rates, columns, strict=True)) for row in range(6)]
print(f"R1 predicted {predicted[1] * 1e9:.5g}, computed {computed[1] * 1e9:.5g} micrograms/m3")
print(max(abs(p - c) / c for p, c in zip(predicted, computed, strict=True)) < 1e-4)
```

```text
R1 predicted 21.269, computed 21.269 micrograms/m3
True
```

Three unit runs predict the combined run at all six receptors. The matrix
holds for this flow, grid and scheme only; with `muscl` the sum does not hold.

## What sensors identify: the source-inference study

`tutorials/source_inference.py` builds the same matrix and then works
backward, from receptor values to source rates.

```bash
python tutorials/source_inference.py --output runs/inference > /dev/null
```

```python
import json
report = json.load(open("runs/inference/report.json"))
print(report["passed"], [f"{q:.4g}" for q in report["fitted_rate_multipliers"]])
print(report["heldout_relative_error"] < 1e-9, report["ambiguous_rank"])
errors = [report[key]["relative_rate_error"] for key in ("bounded_noise", "model_mismatch")]
print(f"rate error: {errors[0]:.3g} with 2 % noise, {errors[1]:.3g} with another inflow")
```

```text
True ['0.7', '1.3', '0.9']
True 2
rate error: 0.0201 with 2 % noise, 0.059 with another inflow
```

- Four receptors fit three non-negative rate multipliers. With observations
  from the same model the fit recovers 0.7, 1.3 and 0.9 and predicts the two
  held-out receptors.
- If two sources have the same column, the matrix has rank 2: their rates
  cannot be separated, however well the fit matches.
- A bounded 2 percent observation error moves the rates by 2 percent.
- Observations from a run with 15 percent more wind give a 6 percent rate
  error: a good fit does not prove the rates when the forward model is wrong.

These are synthetic rates at known locations, not a posterior. Another preset:

```sh
python tutorials/source_inference.py --preset study --output runs/inference-study
```

## An independent reference solve

`validation/scipy_reference.py` assembles the steady transport equations of
the same case as a sparse matrix and solves them with SciPy.

```bash
python validation/scipy_reference.py --output runs/scipy-reference \
  | python -c "import json, sys; r = json.load(sys.stdin); print(r['passed'], r['relative_field_difference'] < 5e-5)"
```

```text
True True
```

The two fields agree within 5e-5 ([record](../evidence/native-verification.md)).
This is numerical verification, not validation: both solve the same equations.

## Compare settings fairly

- Compare runs only under the same sources, geometry, receptors and numerical
  settings. A lower value from a moved sensor or a coarser grid is no gain.
- Keep failed rows and real work counts (`steps`, `pressure_iterations`).
- Reserve held-out observations before you select anything.
- An inverse fit or an optimizer returns numbers that fit this model, not a
  calibrated posterior and not a measured emission.

## A task for an agent

Give this to a coding agent that has the checkout:

> Read `docs/ai-context.md` and the transport model card. Build the locked
> workspace and inspect the actual schemas. Run the source-inference smoke
> tutorial within its declared budgets and a fresh output directory. Check
> every unit-source and combined result with the archived-field auditor.
> Verify that the response matrix uses linear transport. Explain the recovered
> rate multipliers, held-out prediction error, singular values and the
> deliberately ambiguous case. Then run the study preset and explain how a
> changed forward model affects fitted rates. Return the report and figure,
> actual run identities, failed checks if any, and one useful next
> investigation. Do not describe alternative optimizer outputs as a calibrated
> posterior.

## Next

Chapter 13 builds optimization lessons on this chapter. The
[transport model card](../model-cards/transport.md) states the model's limits.
