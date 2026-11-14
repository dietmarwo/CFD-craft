# CFD-craft, OpenFOAM and Ansys Fluent

Version 0.1.0 is a research prototype. A numerically accepted run is not an experimentally validated prediction.

This page compares CFD-craft 0.1.0 with OpenFOAM (Foundation version 13, package `20260407`; version 14 was released in July 2026 [O13], but the bounded backend pins 13) and, for features only, with Ansys Fluent (public documentation of Release 2026 R1). It was checked on 14 November 2026.

The short answer: OpenFOAM and Fluent cover far more physics, far more mesh and geometry types and far larger problems. CFD-craft covers one narrow task, neutral passive-gas dispersion on uniform grids around boxes, and puts its effort into checked input, stated stopping reasons and recomputed evidence.

**Every speed and accuracy number on this page comes from one case: the laminar, two-dimensional Re = 100 lid-driven cavity. None of it says anything about urban flows.** There is no OpenFOAM canyon recipe, so no canyon comparison exists.

## What CFD-craft is for

These properties can be checked in this repository:

- **One strict JSON case.** A run is defined by one file. Unknown fields, unsupported variants and duplicate keys are rejected ([case schema](reference/case-schema.md), [result contract](result-contract.md)).
- **Coded diagnostics with field paths.** `cfd-craft check` reports every problem with a code and the path of the field, for example `CFD-E008` at `run.threads` and `CFD-E010` at `numerics.advective_cfl_max`, and exits 1 ([diagnostics](diagnostics.md), [command line](reference/cli.md)).
- **Budgets and a stated stopping reason.** The case sets step, wall-time, memory and output budgets. SIGINT or SIGTERM ends a CLI run as `cancelled`; it still writes its archive and exits 2. The result names why the run stopped (`termination`) ([case schema, Run](reference/case-schema.md#run)).
- **Three separate verdicts.** Termination (did the run complete?), numerical assessment (is the result accepted?) and experimental validation (`describe` reports `not_validated`) are separate fields ([result contract, Status](result-contract.md#status)).
- **Provenance hashes.** Every archive has a manifest with file hashes, the input case hash, the initial-state hash and source, executable and build identity, plus a completion marker written last ([result contract, Files](result-contract.md#files)).
- **An independent field checker.** [`validation/check_fields.py`](https://github.com/dietmarwo/CFD-craft/blob/main/validation/check_fields.py) recomputes continuity, mass accounting and receptor values from the stored fields.
- **A bounded OpenFOAM backend as a cross-check.** The same cavity runs through OpenFOAM Foundation 13 with recorded executable hashes ([OpenFOAM backend model card](model-cards/openfoam-backend.md)).

## Features

Cells about other tools are facts from their current public documentation (sources at the end). "None documented" names the pages read that do not describe the feature; it says nothing about features those pages do not cover. The Fluent column is features only: this repository has no Fluent measurement.

| Feature | CFD-craft 0.1.0 | OpenFOAM Foundation 13 | Ansys Fluent 2026 R1 |
|---|---|---|---|
| License and source | MIT, source on GitHub ([LICENSE](https://github.com/dietmarwo/CFD-craft/blob/main/LICENSE)) | GNU GPL version 3, source pack published [O1] | Licensed product; PyFluent needs a licensed local Fluent installation [F8] |
| Install | `pip install cfd-craft` (Python binding) or `cargo install cfd-craft-cli` | Packages for Ubuntu 22.04, 24.04 and 25.04; Windows through WSL; macOS through Multipass; source pack [O1] | Installers for Linux x64 (Red Hat, SUSE, Ubuntu 22.04 and 24.04, Rocky) and Windows 11 or Server 2022 and 2025 [F13, F14]; a license is required [F8] |
| Case definition | One strict JSON file ([case schema](reference/case-schema.md)) | A case directory of text dictionaries: `system`, `constant`, time directories [O5] | GUI, text console in Scheme, journal files [F1, F6]; Python through PyFluent [F8] |
| Input check before a run | `check`: coded diagnostics with field paths, memory and output estimates ([diagnostics](diagnostics.md)) | `checkMesh` checks a mesh [O6]; a whole-case check is not documented in [O5, O6, O7, O11] | Mesh check (topology, face handedness, volumes) and a case check of models, boundaries and solver settings with recommendations [F18, F19] |
| Mesh | Uniform Cartesian only ([flow model card](model-cards/flow.md#scope)) | Arbitrary polyhedral cells; `blockMesh`, `snappyHexMesh` [O2, O6] | Triangle to polyhedral cells; structured, unstructured, hybrid, non-conformal and overset meshes [F2] |
| Geometry | Axis-aligned boxes only | `snappyHexMesh` refines and snaps to surface geometry [O6] | CAD and STL import in meshing mode; watertight-geometry and fault-tolerant meshing workflows [F15, F16] |
| Flow models | Constant-density incompressible: prescribed uniform, laminar, neutral RANS | Incompressible, compressible, density-based, multiphase (VoF, Euler), films [O3] | Pressure-based and density-based solvers [F4]; hypersonic, moving frames, dynamic meshes [F1] |
| Turbulence | One neutral k-epsilon package with wall functions; no LES ([flow model card](model-cards/flow.md#neutral-turbulence-package)) | RAS (k-epsilon, k-omega SST, Reynolds stress and others), LES, DES [O4] | Spalart-Allmaras, k-epsilon, k-omega, transition, Reynolds stress, SAS, DES, LES [F3] |
| Scalar transport | Passive gas; point, line and volume sources; point and volume receptors; audited mass budget ([transport model card](model-cards/transport.md)) | `scalarTransport` function object; multicomponent flow module [O3, O8] | Species transport [F1] |
| Other physics | None: no buoyancy, heat transfer, particles, chemistry, multiphase or compressibility | Heat transfer, combustion, Lagrangian particles, multiphase, solids [O1, O3] | Heat transfer, combustion, pollutants, discrete phase, multiphase, FSI, batteries and more [F1] |
| Steady algorithm | Explicit pseudo-time (default); SIMPLEC-type `implicit_projection` (opt-in) ([flow model card](model-cards/flow.md#steady-pseudo-time-algorithms)) | SIMPLE for steady cases, PIMPLE, local pseudo-time stepping [O7, O9] | SIMPLE, SIMPLEC, PISO, Fractional Step, Coupled [F4]; pseudo time method [F4] |
| Momentum advection | First-order donor-cell (default); second-order upwind, limited with van Albada, van Leer or monotonized central (opt-in) | Upwind, linear, linearUpwind, LUST, limitedLinear and other schemes [O9] | First- and second-order upwind, QUICK, third-order MUSCL, bounded central [F5] |
| Pressure solver | IC(0)-preconditioned CG (default); geometric multigrid on grids without solids (opt-in) ([pressure multigrid](developer/pressure-multigrid.md)) | PCG or PBiCGStab with DIC, FDIC or GAMG preconditioning; GAMG solver [O7] | Algebraic multigrid in the pressure-based and density-based implicit solvers [F17] |
| Parallelism | Threads on one machine (1 to 64); no MPI, no GPU | MPI domain decomposition (`decomposePar`, Open MPI by default) [O10] | MPI across compute nodes [F9]; native GPU solver on one or several GPUs [F10] |
| Budgets and cancellation | Steps, wall time, memory and output in the case; signal or cancel file stops cleanly | End time; `stopAtClockTime` and `stopAtFile` function objects [O8, O11] | Number of iterations and convergence conditions; the Stop button or Ctrl+C interrupts after the current iteration [F20, F21]; a wall-time budget is not documented there |
| What a result reports | Termination, assessment, recomputed checks, validation label ([result contract](result-contract.md)) | Logs and function-object output such as residuals and probes [O8] | Convergence monitors and conditions [F4]; simulation reports [F1] |
| Restart | Checksummed checkpoint bound to a physics hash | Start from the latest written time directory [O11] | Case and data files together restart a solution [F7] |
| Provenance | Case, physics, initial-state, source and executable hashes in a manifest | Each data file has a header naming format, class and file; no hash or build record is documented in [O17]; output goes to a log by redirection [O16] | Transcript files record a session [F6]; file hashes are not documented in [F6, F7] |
| Scripting and machine-readable interface | In-process Python, JSON command line, Rust library ([Python API](reference/python-api.md)); `describe` prints the case and result schemas and exit codes as JSON ([agent entry page](ai-context.md)) | Command-line utilities; `foamDictionary` reads and edits dictionary entries [O6]; a Python interface is not documented in [O6, O12, O16] | PyFluent Python library [F8]; Scheme text commands and journals [F6] |
| Post-processing | VTK export for ParaView; no built-in viewer | ParaView reader, `foamToVTK`, `writeVTK` [O6, O8, O12] | Built-in graphics and reports; export to EnSight and CFD-Post [F1, F6] |
| Experimental validation | None: `not_validated`; canyon data not available ([data inventory](https://github.com/dietmarwo/CFD-craft/blob/main/validation/data-inventory.json)) | Comparison with measurements is not documented in the tutorial pages [O14, O15] | Verification manual: 78 Fluent and CFX cases against theory or published experiments [F11] |
| Maturity | First version 0.1.0, 4 November 2026 ([changelog](https://github.com/dietmarwo/CFD-craft/blob/main/CHANGELOG.md)) | Major versions every July since at least 2017; 13 in July 2025, 14 in July 2026 [O1, O13] | Releases 2024 R2, 2025 R1, 2025 R2 and 2026 R1 are supported by PyFluent [F8] |
| Optimization | Optimization-job worker and fcmaes adapter ([README](https://github.com/dietmarwo/CFD-craft/blob/main/README.md)) | Not documented in the v13 user guide [O12] | Adjoint solver, gradient-based optimizer, mesh morphing [F12] |

## Measured against OpenFOAM: the Re = 100 cavity

All measurements below are committed records under [`evidence/`](evidence/backend-comparison.md). No new measurement was made for this page. Accuracy is the largest centerline-velocity difference from the Ghia et al. numerical reference, in units of the lid speed; it is a numerical reference, not an experiment. "Solver time" and "workflow time" are defined in each record. Both backends use one solver thread.

**Default numerics (donor-cell momentum, explicit pseudo-time).**

- The [backend comparison](evidence/backend-comparison.md#result) found OpenFOAM's whole workflow 5.502 times faster than native steady mode on an AMD EPYC 9V74 virtual machine (Python 3.12) and 4.692 times faster on a GitHub runner (AMD EPYC 9V45, 4 CPUs, ubuntu-24.04, Python 3.12, run 41195406078); its solver process was 8.895 and 8.88 times faster. The record gives no date and no OpenFOAM version; it ran the adapter's pinned runtime.
- In the same [backend comparison](evidence/backend-comparison.md#result) OpenFOAM was closer to the reference at 24×24 cells: 0.0090 against 0.0276 for native steady mode.
- In [Stage V](evidence/momentum-verification.md#paired-backend-sweep) (1 November 2026; AMD EPYC 9V74, Rust 1.88.0, Python 3.12.14, pinned OpenFOAM Foundation 13 package) OpenFOAM reached 0.01 at 24² and native missed it on all four shared grids (16² to 48²). A separate native 96² run reached 0.00920541; among the tested grids that is the first native grid under 0.01. Its solver work was about 1076.02 s on the recording host; a cold run on a GitHub runner was accepted after 825.9 s.
- The [pressure multigrid results](evidence/pressure-multigrid.md#accepted-coupled-cavity) (31 October 2026; AMD EPYC 9V74, Rust 1.88.0) show that the opt-in multigrid preconditioner cut the accepted native 48² solver time from 180.665 s to 74.108 s with the default momentum scheme and explicit pseudo-time; the accuracy (0.01695144) did not change.
- With default numerics the pressure projection took 77.92 % of native solver time on the 24² cavity and 88.34 % in one profiled 48² run ([gap baseline](evidence/gap-baseline.md#actual-phase-attribution), 31 October 2026; AMD EPYC 9V74, rustc 1.99.1, OpenFOAM Foundation 13 package 20260407).

**Opt-in numerics.** None of these settings is the default.

- Opt-in second-order momentum advection brought the native 24² difference to between 0.00494 and 0.00589, depending on the limiter, and van Leer to 0.00544 ([second-order momentum](evidence/second-order-momentum.md#7-cavity-sweep), 1 November 2026; native only, a 2-vCPU Intel Xeon virtual machine).
- With second-order momentum but the default explicit pseudo-time, native took 13.25 times OpenFOAM's solver time at 24² (11.19 s against 0.844 s) ([matched accuracy](evidence/matched-accuracy.md#how-the-gap-closed), 1 November 2026, run 41346827479, AMD EPYC 7763, 4 CPUs).
- With second-order momentum and the opt-in `implicit_projection` steady algorithm both backends first reached 0.01 at 24²; native took 0.74 times OpenFOAM's solver time and 0.45 times its workflow time, at 0.0054 against 0.0090 ([matched accuracy](evidence/matched-accuracy.md#hosted-run), 1 November 2026, run 41345659321, Intel Xeon Platinum 8370C, 4 CPUs).
- With the final implicit recipe (pressure tolerance 0.1, a non-binding time-step cap, one span cell), native took 0.111 times OpenFOAM's solver time (0.0698 s against 0.628 s) and 0.119 times its workflow time at 24², at 0.00543 against 0.00897 ([performance iterations](evidence/performance-iterations.md#hosted-reproduction), 1 November 2026, run 41361132558, AMD EPYC 9V74, 4 CPUs; also in [matched accuracy](evidence/matched-accuracy.md#after-the-performance-iterations)).

**Memory.** Native peak memory was 851.7 MiB for one million cells in a three-step canyon run on a 2-core Intel Xeon virtual machine with rustc 1.97.0 ([native verification](evidence/native-verification.md#measured-resources); the record gives no date). There is no OpenFOAM memory measurement beside it.

**Limits of these comparisons.**

- The two configurations differ: the stopping rules differ (native `assess` gates, OpenFOAM `residualControl` 1e-7), and in run 41345659321 native computed two span cells and OpenFOAM one ([matched accuracy, Scope](evidence/matched-accuracy.md#scope)). The ratios describe these recipes on these runners.
- Every ratio is one thread against one thread. OpenFOAM supports MPI decomposition; the CFD-craft adapter runs it serially. Nothing about multi-core scaling follows ([backend comparison](evidence/backend-comparison.md#consequences)).
- Native canyon timings exist only for native: with the implicit recipe a 27k-cell canyon with its tracer took 57.6 s and a 93k-cell canyon 615 s on a 2-vCPU Intel Xeon virtual machine, and the canyon is not grid-converged ([performance iterations](evidence/performance-iterations.md#before-and-after), [implicit RANS](evidence/implicit-rans.md)).
- The backstep runs compare OpenFOAM with measurements, not one solver with another, and they were not numerically accepted ([external backend](evidence/external-backend.md)).

## Ansys Fluent

Fluent is a licensed commercial CFD code [F8]. Its public 2026 R1 user's guide covers pressure-based and density-based solvers, structured, unstructured, hybrid, polyhedral, non-conformal and overset meshes, a wide range of turbulence models from Spalart-Allmaras to LES, and many physics modules (heat transfer, species transport and combustion, discrete particles, multiphase, fluid-structure interaction). It runs in parallel with MPI and has a native GPU solver. It is scripted with Scheme text commands, journal files and the PyFluent Python library, and it includes an adjoint solver for shape optimization.

This repository has no Fluent run. The page therefore makes no speed or accuracy statement about Fluent. Every Fluent cell rests on the public 2026 R1 documentation; the Ansys product pages redirected to a domain that could not be fetched.

## Urban-dispersion tools

Practitioners in urban air quality also use dedicated tools. PALM is a large-eddy simulation model for atmospheric and oceanic boundary layers, built for massively parallel computers; its PALM-4U components add urban features such as radiation, land surface and chemistry, it is free software under the GPL version 3, and release 25.10 was presented in April 2026 [U1, U2, U3]. ENVI-met is commercial three-dimensional microclimate software that simulates wind, heat, humidity, radiation, vegetation and pollutant dispersion in cities [U4]. CFD-craft has neither LES nor thermal physics and is not a substitute for either.

## Where the others are ahead

- **Physics.** OpenFOAM and Fluent model heat transfer, compressible and multiphase flow, particles and combustion [O3, F1]. CFD-craft has none of these.
- **Turbulence.** They offer many RANS models plus LES and DES [O4, F3]. CFD-craft has one neutral k-epsilon package.
- **Geometry and meshing.** They use unstructured and polyhedral meshes fitted to surface geometry [O2, O6, F2]. CFD-craft has uniform Cartesian grids and boxes.
- **Validation.** Fluent publishes a verification manual with cases against published experiments [F11]; the OpenFOAM v13 tutorial pages do not document a comparison with measurements [O14, O15]. CFD-craft 0.1.0 has no experimental validation.
- **Community and maturity.** OpenFOAM has released a major version every year since at least 2017 [O13], and Fluent names an R1 and an R2 release in each of 2025 and 2026 [F8]. CFD-craft had its first release on 4 November 2026.
- **Parallel scaling.** Both run in parallel with MPI [O10, F9]; Fluent also on GPUs [F10]. CFD-craft uses threads on one machine.

Version 0.1.0 is a research prototype. A numerically accepted run is not an experimentally validated prediction.

## When to use which

- A real geometry, real physics or a result for a decision: OpenFOAM or Fluent.
- Urban microclimate, heat or LES of a city quarter: PALM or ENVI-met.
- Many small, scripted, checkable passive-gas runs on a box geometry, for example inside an optimizer: CFD-craft.
- Testing what an agent or a script does with a CFD tool, with coded errors and stated stopping reasons: CFD-craft.
- Checking a CFD-craft cavity result against an established code: the bounded OpenFOAM backend.

## Sources

All checked on 14 November 2026.

| Id | Tool | Claims | URL |
|---|---|---|---|
| O1 | OpenFOAM | Version 13 release: license, platforms, physics | https://openfoam.org/release/13/ |
| O2 | OpenFOAM | Polyhedral cells (v13 user guide) | https://doc.cfd.direct/openfoam/user-guide-v13/mesh-description |
| O3 | OpenFOAM | Solver modules (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/solvers-modules |
| O4 | OpenFOAM | Turbulence models (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/turbulence |
| O5 | OpenFOAM | Case file structure (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/case-file-structure |
| O6 | OpenFOAM | Utilities: checkMesh, snappyHexMesh, foamDictionary, foamToVTK (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/standard-utilities |
| O7 | OpenFOAM | Linear solvers, SIMPLE and PIMPLE (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/fvsolution |
| O8 | OpenFOAM | Function objects: scalarTransport, stop, residuals, probes, writeVTK (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/post-processing-functionality |
| O9 | OpenFOAM | Discretization schemes (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/fvschemes |
| O10 | OpenFOAM | Parallel running (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/running-applications-parallel |
| O11 | OpenFOAM | Run control and restart (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/controldict |
| O12 | OpenFOAM | ParaView chapter (v13 contents) | https://doc.cfd.direct/openfoam/user-guide-v13 |
| O13 | OpenFOAM | Release dates of versions 13 and 14 | https://openfoam.org/category/release |
| O14 | OpenFOAM | Tutorials (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/tutorials |
| O15 | OpenFOAM | Backward-facing step tutorial (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/backwardstep |
| O16 | OpenFOAM | Running applications, log files (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/running-applications |
| O17 | OpenFOAM | File header format (v13) | https://doc.cfd.direct/openfoam/user-guide-v13/basic-file-format |
| F1 | Fluent | User's guide 2026 R1, chapter list | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/pt03.html |
| F2 | Fluent | Cell shapes and mesh topologies | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_GridTypes.html and https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_chp_grid.html |
| F3 | Fluent | Turbulence models | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_chap_turbulence.html |
| F4 | Fluent | Solver types, coupling, pseudo time, convergence | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_chp_solve.html and https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_sec_uns_solve_pvel_1.html |
| F5 | Fluent | Convection schemes | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_sec_solve_choose_disc.html |
| F6 | Fluent | Text interface, journal files, export | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_chp_tui.html and https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_chp_files.html |
| F7 | Fluent | Case and data files, restart | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_CaseDataFiles.html |
| F8 | Fluent | PyFluent, license requirement, supported releases | https://pypi.org/project/ansys-fluent-core |
| F9 | Fluent | Parallel processing | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_parallel_intro.html |
| F10 | Fluent | Native GPU solver | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_sec_gpu_solver_intro.html |
| F11 | Fluent | Verification manual 2026 R1 | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/fbu_vm/vmflintrochp.html |
| F12 | Fluent | Adjoint solver and optimizer | https://ansyshelp.ansys.com/public/views/secured/corp/v261/en/flu_ug/flu_adj_usage.html |
| F13 | Fluent | Linux installation prerequisites, 2026 R1 | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/installation/unix_sysprereqs.html |
| F14 | Fluent | Windows installation prerequisites, 2026 R1 | https://ansyshelp.ansys.com/public/views/secured/corp/v261/en/installation/win_sysprereqs.html |
| F15 | Fluent | Meshing mode, CAD formats | https://ansyshelp.ansys.com/public/views/secured/corp/v261/en/flu_ug/ch09s01.html and https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/pt02.html |
| F16 | Fluent | Watertight and fault-tolerant workflows | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/tgd_user_workflow_guided_watertight.html and https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/tgd_user_workflow_guided_fault.html |
| F17 | Fluent | Multigrid methods (theory guide) | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_th/flu_th_MultigridMethod.html |
| F18 | Fluent | Mesh check | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_GridCheck.html |
| F19 | Fluent | Case check | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_sec_solve_check.html |
| F20 | Fluent | Steady calculation, interrupting | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_sec_solve_calc.html |
| F21 | Fluent | Convergence conditions | https://ansyshelp.ansys.com/public/Views/Secured/corp/v261/en/flu_ug/flu_ug_convergence_conditions.html |
| U1 | PALM | Model overview and PALM-4U (GMD, 2020) | https://gmd.copernicus.org/articles/13/1335/2020/ |
| U2 | PALM | Description and license | https://docs.csc.fi/apps/palm |
| U3 | PALM | Release 25.10 talk, April 2026 | https://tu-dresden.de/tu-dresden/veranstaltungen/veranstaltungskalender/zih-kolloqium/zih-kolloquium-the-palm-model-system-release-25-10-an-les-code-for-basic-and-environmental-research-capabilities-and-recent-applications |
| U4 | ENVI-met | Product description and licenses | https://www.envi-met.com/software |

Not fetched: the Ansys Fluent product pages (`ansys.com/products/fluids/ansys-fluent`, product updates and capabilities) redirect to a domain this check could not reach. The OpenFOAM v13 documentation pages are hosted by CFD Direct and linked from the Foundation site.
