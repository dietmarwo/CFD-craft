# Tutorials

The first release has three executable workflows. Every run uses canonical inputs and preserves its evidence.

| Workflow | Command | Learning outcome |
|---|---|---|
| Source inference | python tutorials/source_inference.py --output runs/inference | Unit-source responses, nonnegative rates, held-out sensors, rank deficiency and model mismatch. |
| Finite canyon | python tutorials/canyon_study.py --preset smoke --output runs/canyons | Wind direction/aspect ratio, coupled flow/gas checks and limits of coarse scenarios. |
| Native optimization | python integrations/run_jobs.py --runner RUNNER --output runs/jobs | Hashed CFD inputs, fallible simulation evaluation, equal counted BiteOpt/GP budgets and honest result semantics. |

Use fresh output paths. The source-inference study preset uses altered-grid observations. The canyon sensitivity preset adds two Schmidt values and a longer outlet domain; the full study also attempts a three-grid series and may reach its resource limits.

The planned vegetation/PM and neighborhood/annual tutorials belong to later milestones. This release's gas cases do not implement those models.

## Source inference

Three volume sources are observed by six receptors in fixed uniform flow. Separate source solves define a response matrix only in linear_upwind mode. The combined solve checks superposition. Four receptors fit three nonnegative rate multipliers; two receptors test prediction.

The exact same-model example should recover the rates. A second observation set changes inflow and, in study mode, grid resolution. The resulting source-rate bias illustrates that a good inverse fit does not prove the physical emission rates. A repeated matrix column supplies an explicitly unidentifiable example. A small exhaustive sensor search is the baseline before any optimizer.

## Canyon

The finite boxes have height 1 m, length 10 m and W/H of 1 or 2. Winds from 270 and 225 degrees produce perpendicular and oblique scenarios. The source is a fixed total line emission; receptors stay in fluid cells.

Coarse smoke results answer a numerical workflow question. They are intentionally under-resolved for general near-wall physical interpretation. Read the geometry warnings, independent audit, equation residuals and model card. The data inventory records why an empirical CODASC comparison is currently blocked.

## Optimization

The native worker varies two of three positive source multipliers and sets the third to 3 minus their sum. The box guarantees positivity and preserves the canonical equal-base total emission. The scalar objective is the maximum receptor concentration divided by 1e-8 kg/m3.

This is a small deterministic allocation example on prescribed flow. It demonstrates real simulator calls, not a surrogate of a known analytic objective. A 24-evaluation BiteOpt hard budget and a 24-evaluation GP budget are both followed by counted rechecks. One seed and small budgets are not an optimizer ranking.

Agent prompts: [source inference](source-inference-prompt.md), [canyon](canyon-prompt.md), [optimization](optimization-prompt.md).
