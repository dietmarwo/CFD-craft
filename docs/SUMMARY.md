# Summary

[CFD-craft](index.md)
[How do I …?](how-to.md)
[CFD-craft, OpenFOAM and Ansys Fluent](comparison.md)
[Agent entry point](ai-context.md)

# Guide

- [About the guide](guide/README.md)

# Part I: First steps

- [1. First run](guide/01-first-run.md)
- [2. The case file](guide/02-case-file.md)
- [3. The command line and the run archive](guide/03-cli-and-archive.md)
- [4. Can I trust this result?](guide/04-reading-a-result.md)
- [5. Sources, receptors and transport](guide/05-sources-receptors-transport.md)

# Part II: Flow

- [6. Compute a flow](guide/06-flow-cavity.md)
- [7. Before you spend compute](guide/07-budgets-preview-cancel.md)
- [8. Checkpoint and restart](guide/08-checkpoint-restart.md)
- [9. Opt-in numerics](guide/09-opt-in-numerics.md)
- [10. Buildings and a street canyon](guide/10-street-canyon.md)

# Part III: Automation

- [11. Python](guide/11-python.md)
- [12. Many runs](guide/12-studies.md)
- [13. Optimization lessons F1 to F3](guide/13-optimization-lessons.md)
- [14. Optimization jobs](guide/14-optimization-jobs.md)

# Part IV: OpenFOAM backend

- [15. Install OpenFOAM and run a cavity](guide/15-openfoam-first-run.md)
- [16. Compare solvers and measurements](guide/16-compare-solvers.md)
- [17. Continue a solve, start a finer mesh](guide/17-continuation-and-mapping.md)
- [18. Audit a wall-resolved backstep](guide/18-backstep-resolution.md)
- [19. A bounded refinement campaign](guide/19-refinement-campaign.md)

# Part V: Embedding and help

- [20. The Rust library](guide/20-rust-library.md)
- [21. Troubleshooting](guide/21-troubleshooting.md)

# Reference

- [Reference](reference/README.md)
- [Case schema](reference/case-schema.md)
- [Result schema](reference/result-schema.md)
- [Case, result and provenance](result-contract.md)
- [Command line reference](reference/cli.md)
- [Python API](reference/python-api.md)
- [Diagnostics](diagnostics.md)
- [Units and conventions](reference/units-and-conventions.md)
- [Scripts](reference/scripts.md)
- [Model cards](model-cards/README.md)
  - [Flow model 0.1](model-cards/flow.md)
  - [Passive transport 0.1](model-cards/transport.md)
  - [External backend: OpenFOAM Foundation 13](model-cards/openfoam-backend.md)

# Evidence

- [About the evidence](evidence/README.md)
  - [Recorded verification results](evidence/native-verification.md)
  - [Native CPU performance: results](evidence/native-cpu-performance.md)
  - [Pressure multigrid results](evidence/pressure-multigrid.md)
  - [Anisotropic pressure multigrid results](evidence/anisotropic-pressure.md)
  - [Stage V: momentum verification and donor-cell baseline](evidence/momentum-verification.md)
  - [Second-order momentum advection (stage P3a): results](evidence/second-order-momentum.md)
  - [Implicit steady pseudo-time (stages P4 and P5a): results](evidence/implicit-steady.md)
  - [Implicit steady iteration with RANS and constituents (stages P5c and P5d): results](evidence/implicit-rans.md)
  - [Ten performance iterations after P5d: results](evidence/performance-iterations.md)
  - [Native solver and OpenFOAM on the lid-driven cavity: measured cost](evidence/backend-comparison.md)
  - [Native/OpenFOAM gap-closing baseline](evidence/gap-baseline.md)
  - [Matched-accuracy measurement against OpenFOAM (stage M)](evidence/matched-accuracy.md)
  - [Performance gap: current state and remaining stages](evidence/performance-gap-status.md)
  - [Recorded external-backend results](evidence/external-backend.md)
  - [Recorded wall-resolved backstep results](evidence/backstep-resolution.md)
  - [Recorded steady-continuation results](evidence/steady-continuation.md)
  - [Recorded coarse-to-fine initialization results](evidence/mesh-initialization.md)
  - [Bounded mapped refinement: results](evidence/refinement-campaign.md)
  - [Validation record](evidence/optimization-lessons.md)

# Developer

- [Working on CFD-craft](developer/README.md)
- [Architecture](developer/architecture.md)
- [Native phase profiling and cavity accuracy sweeps](developer/profiling.md)
- [Symmetric pressure multigrid](developer/pressure-multigrid.md)
- [Numerical decisions for 0.1](developer/decisions.md)
- [Roadmap](developer/roadmap.md)
- [The documentation check](developer/documentation.md)
- [Releasing](developer/releasing.md)

# History

- [About these pages](history/README.md)
  - [CFD-craft: native accuracy and steady-solver plan (P3–P5)](history/accuracy-steady-plan.md)
  - [Iteration 02: established-solver execution and experimental evidence](history/02-external-validation-plan.md)
  - [Iteration 03: resolve the backstep convergence gate](history/03-wall-resolution-plan.md)
  - [Iteration 04: verified bounded steady continuation](history/04-steady-continuation-plan.md)
  - [Iteration 05: explicit coarse-to-fine field initialization](history/05-mesh-initialization-plan.md)
  - [Iteration 06: archive anomaly investigation](history/06-archive-investigation.md)
  - [Iteration 06: bounded mapped refinement campaign](history/06-refinement-campaign-plan.md)
  - [Iterations 07–14: native CPU throughput](history/07-14-performance-plan.md)
  - [Detailed user manual and project banner](history/16-user-manual-plan.md)
  - [Iteration 17: measure the native/OpenFOAM performance gap (P0)](history/17-gap-measurement-plan.md)
  - [Symmetric pressure multigrid plan](history/18-pressure-multigrid-plan.md)
  - [Anisotropic pressure acceleration plan](history/19-anisotropic-pressure-plan.md)
  - [Stage V: momentum verification and donor-cell baseline](history/20-momentum-verification-plan.md)
