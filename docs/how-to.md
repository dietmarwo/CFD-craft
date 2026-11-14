# How do I …?

Tasks in plain words. Each link goes to the section of the
[guide](guide/README.md) or the reference that does it; the section starts from
the setup of its chapter.

## Install and first run

| How do I … | Section |
|---|---|
| install CFD-craft for Python? | 1 [Setup](guide/01-first-run.md#setup) |
| install the `cfd-craft` command? | 3 [Setup](guide/03-cli-and-archive.md#setup) |
| build from source? | 3 [Setup](guide/03-cli-and-archive.md#setup) |
| choose between Python, the command line and Rust? | Guide [Which interface](guide/README.md#which-interface) |
| run my first case? | 1 [Run it](guide/01-first-run.md#run-it) |
| run a case from the shell? | 3 [Check, run, report](guide/03-cli-and-archive.md#check-run-report) |
| check a case before I run it? | 1 [Check the case](guide/01-first-run.md#check-the-case) |

## Cases

| How do I … | Section |
|---|---|
| find out which fields a case may have? | 2 [Find the allowed fields](guide/02-case-file.md#find-the-allowed-fields); [case schema](reference/case-schema.md) |
| change a parameter without editing the original case? | 2 [Change a case without touching the original](guide/02-case-file.md#change-a-case-without-touching-the-original) |
| understand an "unknown field" error? | 2 [A wrong field is an error](guide/02-case-file.md#a-wrong-field-is-an-error) |
| know which unit a field has? | 2 [Units and coordinates](guide/02-case-file.md#units-and-coordinates); [units and conventions](reference/units-and-conventions.md) |
| know what the groups of a case mean? | 2 [The groups of a case](guide/02-case-file.md#the-groups-of-a-case) |

## Results

| How do I … | Section |
|---|---|
| read a concentration in micrograms/m3? | 1 [Read a receptor](guide/01-first-run.md#read-a-receptor) |
| tell whether a run converged? | 4 [Assessment: what the checks support](guide/04-reading-a-result.md#assessment-what-the-checks-support) |
| tell why a run stopped? | 4 [Termination: why the run stopped](guide/04-reading-a-result.md#termination-why-the-run-stopped) |
| make a script fail on a result that is not accepted? | 4 [Require a verdict in a script](guide/04-reading-a-result.md#require-a-verdict-in-a-script) |
| interpret exit code 2? | 3 [Exit codes](guide/03-cli-and-archive.md#exit-codes); 4 [An incomplete run is still a result](guide/04-reading-a-result.md#an-incomplete-run-is-still-a-result) |
| know what each file in a run directory is? | 3 [The files of a run](guide/03-cli-and-archive.md#the-files-of-a-run) |
| verify that a run directory is intact? | 3 [Check, run, report](guide/03-cli-and-archive.md#check-run-report) |
| check the stored fields independently of the solver? | 3 [Check the fields independently](guide/03-cli-and-archive.md#check-the-fields-independently) |
| look at the fields in ParaView? | 3 [Look at the fields in ParaView](guide/03-cli-and-archive.md#look-at-the-fields-in-paraview) |
| know whether a result is experimentally validated? | 4 [Experimental validation is a separate label](guide/04-reading-a-result.md#experimental-validation-is-a-separate-label) |

## Sources, receptors, transport

| How do I … | Section |
|---|---|
| define a point, line or volume source? | 5 [Three kinds of source, three rate units](guide/05-sources-receptors-transport.md#three-kinds-of-source-three-rate-units) |
| convert a line or volume rate to kg/s? | 5 [Three kinds of source, three rate units](guide/05-sources-receptors-transport.md#three-kinds-of-source-three-rate-units) |
| add a sensor? | 5 [Point and volume receptors](guide/05-sources-receptors-transport.md#point-and-volume-receptors) |
| choose between `linear_upwind` and `muscl`? | 5 [MUSCL is sharper and not linear](guide/05-sources-receptors-transport.md#muscl-is-sharper-and-not-linear) |
| fix "steady sources need an open boundary" (`CFD-E020`)? | 5 [A steady source needs a way out](guide/05-sources-receptors-transport.md#a-steady-source-needs-a-way-out) |
| simulate a release that is not steady? | 5 [A release that is not steady](guide/05-sources-receptors-transport.md#a-release-that-is-not-steady) |
| build a source-receptor response matrix? | 12 [Unit responses and superposition](guide/12-studies.md#unit-responses-and-superposition) |

## Flow

| How do I … | Section |
|---|---|
| compute a laminar flow with walls and a moving lid? | 6 [The case: walls, a moving lid, one periodic direction](guide/06-flow-cavity.md#the-case-walls-a-moving-lid-one-periodic-direction) |
| run to a steady state? | 6 [Run to a steady state](guide/06-flow-cavity.md#run-to-a-steady-state) |
| run a two-dimensional case? | 6 [Two-dimensional runs](guide/06-flow-cavity.md#two-dimensional-runs) |
| compare a cavity result with the Ghia reference? | 6 [Compare with a numerical reference](guide/06-flow-cavity.md#compare-with-a-numerical-reference) |
| test the pressure solver on my grid? | 6 [What the pressure step does](guide/06-flow-cavity.md#what-the-pressure-step-does) |

## Budgets, preview, restart

| How do I … | Section |
|---|---|
| estimate memory and output before a run? | 7 [What `check` estimates](guide/07-budgets-preview-cancel.md#what-check-estimates) |
| limit steps, wall time, memory or threads? | 7 [Budgets are part of the case](guide/07-budgets-preview-cancel.md#budgets-are-part-of-the-case) |
| try a case on a coarser grid first? | 7 [Preview on a coarser grid](guide/07-budgets-preview-cancel.md#preview-on-a-coarser-grid) |
| understand why a preview was refused? | 7 [When a preview is refused](guide/07-budgets-preview-cancel.md#when-a-preview-is-refused) |
| stop a run at a wall-time limit? | 7 [Stop on a time limit](guide/07-budgets-preview-cancel.md#stop-on-a-time-limit) |
| cancel a run and keep what it computed? | 7 [Cancel a run](guide/07-budgets-preview-cancel.md#cancel-a-run) |
| resume an interrupted run? | 8 [Stop by work, then resume](guide/08-checkpoint-restart.md#stop-by-work-then-resume) |
| show that a restart reproduces the uninterrupted run? | 8 [Is the resumed run the same run?](guide/08-checkpoint-restart.md#is-the-resumed-run-the-same-run) |
| know which case changes keep a checkpoint usable? | 8 [What a checkpoint fits](guide/08-checkpoint-restart.md#what-a-checkpoint-fits) |

## Opt-in numerics

| How do I … | Section |
|---|---|
| get second-order accuracy for momentum? | 9 [Second-order momentum advection](guide/09-opt-in-numerics.md#second-order-momentum-advection) |
| make a steady run converge in fewer iterations? | 9 [Implicit steady iteration](guide/09-opt-in-numerics.md#implicit-steady-iteration); [The implicit recipe](guide/09-opt-in-numerics.md#the-implicit-recipe) |
| use multigrid for the pressure equation? | 9 [Multigrid for the pressure equation](guide/09-opt-in-numerics.md#multigrid-for-the-pressure-equation) |
| see where the solver spends its time? | 9 [Where the time goes: `profile`](guide/09-opt-in-numerics.md#where-the-time-goes-profile) |

## Buildings and canyons

| How do I … | Section |
|---|---|
| add buildings? | 10 [The case: boxes, open top, wind](guide/10-street-canyon.md#the-case-boxes-open-top-wind) |
| set the wind direction? | 10 [The case: boxes, open top, wind](guide/10-street-canyon.md#the-case-boxes-open-top-wind); [Another wind direction](guide/10-street-canyon.md#another-wind-direction) |
| model a traffic line source in a street? | 10 [The case: boxes, open top, wind](guide/10-street-canyon.md#the-case-boxes-open-top-wind) |
| understand warnings `CFD-W001` to `CFD-W003`? | 10 [Read the warnings before the result](guide/10-street-canyon.md#read-the-warnings-before-the-result) |
| speed up a canyon run? | 10 [The same steady state faster](guide/10-street-canyon.md#the-same-steady-state-faster) |
| know what a coarse canyon result does not show? | 10 [What this result is not](guide/10-street-canyon.md#what-this-result-is-not) |
| run all canyon scenarios as one study? | 10 [All committed scenarios in one study](guide/10-street-canyon.md#all-committed-scenarios-in-one-study) |

## Python and automation

| How do I … | Section |
|---|---|
| catch invalid input in Python? | 11 [Errors carry diagnostics](guide/11-python.md#errors-carry-diagnostics) |
| pass a case as a dictionary, string or bytes? | 11 [Inputs: dictionary, string or bytes](guide/11-python.md#inputs-dictionary-string-or-bytes) |
| cancel a simulation from Python? | 11 [Cancel from Python](guide/11-python.md#cancel-from-python) |
| run several simulations at once from Python? | 11 [Threads, the GIL and concurrent calls](guide/11-python.md#threads-the-gil-and-concurrent-calls) |
| script the command line with `subprocess`? | 11 [Drive the CLI from Python](guide/11-python.md#drive-the-cli-from-python) |
| write an objective function that is allowed to fail? | 12 [A fallible objective](guide/12-studies.md#a-fallible-objective) |
| infer source strengths from sensor readings? | 12 [What sensors identify: the source-inference study](guide/12-studies.md#what-sensors-identify-the-source-inference-study) |
| check transport against an independent solver? | 12 [An independent reference solve](guide/12-studies.md#an-independent-reference-solve) |
| decide between an LP and a black-box optimizer? | 13 [F1: a linear problem hides in the simulator](guide/13-optimization-lessons.md#f1-a-linear-problem-hides-in-the-simulator) |
| choose sensor locations? | 13 [F2: coverage is not identifiability](guide/13-optimization-lessons.md#f2-coverage-is-not-identifiability) |
| optimize a flow setting without exploiting a coarse grid? | 13 [F3: a design must survive a finer grid](guide/13-optimization-lessons.md#f3-a-design-must-survive-a-finer-grid) |
| run CFD-craft as an optimization job? | 14 [Run the four jobs](guide/14-optimization-jobs.md#run-the-four-jobs) |
| build and inspect the fcmaes worker? | 14 [The application worker](guide/14-optimization-jobs.md#the-application-worker) |
| give an agent a bounded task? | [Agent entry point](ai-context.md); A task for an agent in chapters [10](guide/10-street-canyon.md#a-task-for-an-agent), [12](guide/12-studies.md#a-task-for-an-agent), [14](guide/14-optimization-jobs.md#a-task-for-an-agent), [16](guide/16-compare-solvers.md#a-task-for-an-agent), [18](guide/18-backstep-resolution.md#a-task-for-an-agent), [19](guide/19-refinement-campaign.md#a-task-for-an-agent) |

## OpenFOAM backend

| How do I … | Section |
|---|---|
| install the pinned OpenFOAM runtime? | 15 [Install the pinned runtime](guide/15-openfoam-first-run.md#install-the-pinned-runtime) |
| run an OpenFOAM cavity through the adapter? | 15 [Generate, run and inspect](guide/15-openfoam-first-run.md#generate-run-and-inspect) |
| compare the native solver and OpenFOAM on one case? | 16 [Two solvers against a numerical reference](guide/16-compare-solvers.md#two-solvers-against-a-numerical-reference) |
| compare OpenFOAM with backstep measurements? | 16 [One solver against measurements](guide/16-compare-solvers.md#one-solver-against-measurements) |
| time both solvers fairly? | 16 [Time both backends on one host](guide/16-compare-solvers.md#time-both-backends-on-one-host) |
| continue a long steady OpenFOAM solve? | 17 [Continue on the same mesh](guide/17-continuation-and-mapping.md#continue-on-the-same-mesh) |
| start a finer mesh from a coarse result? | 17 [Start a finer mesh](guide/17-continuation-and-mapping.md#start-a-finer-mesh) |
| audit mesh, face flux and y+ of a backstep run? | 18 [Audit mesh, flux and y+](guide/18-backstep-resolution.md#audit-mesh-flux-and-y) |
| run a bounded refinement campaign? | 19 [Run the campaign](guide/19-refinement-campaign.md#run-the-campaign) |

## Rust, help, evidence

| How do I … | Section |
|---|---|
| use the solver as a Rust library? | 20 [Depend on the crate](guide/20-rust-library.md#depend-on-the-crate); [Solve in process](guide/20-rust-library.md#solve-in-process) |
| read a run archive from Rust? | 20 [Read a CLI archive](guide/20-rust-library.md#read-a-cli-archive) |
| find what a diagnostic code means? | [Diagnostics](diagnostics.md); 21 [By symptom](guide/21-troubleshooting.md#by-symptom) |
| find the measurement behind a number? | [Evidence](evidence/README.md); [comparison](comparison.md) |
| run the documentation check myself? | [Run the documentation check](developer/documentation.md#run-the-documentation-check) |
