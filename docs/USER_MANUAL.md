<!-- stub -->
# CFD-craft user manual

This page moved. The manual is now the [guide](guide/README.md): 21 chapters,
ordered by difficulty, each with its own setup. The old sections and the 31
numbered examples are listed below with their new places. The example
programs are listed in [examples/manual](../examples/manual/README.md).

## Choose an interface

Now in [About the guide, Which interface](guide/README.md#which-interface).

## Install and run your first case

Now in [Chapter 1, First run](guide/01-first-run.md); [Chapter 3, Setup](guide/03-cli-and-archive.md#setup).

## Architecture and ownership

Now in [Architecture](developer/architecture.md).

## Numerical concepts

Now in [Chapter 6, What the pressure step does](guide/06-flow-cavity.md#what-the-pressure-step-does); [Chapter 9, Opt-in numerics](guide/09-opt-in-numerics.md); [Chapter 5, Sources, receptors and transport](guide/05-sources-receptors-transport.md); [Units and conventions](reference/units-and-conventions.md).

## Understand and edit a case

Now in [Chapter 2, The case file](guide/02-case-file.md).

## CLI cookbook

Now in [Chapter 3, The command line and the run archive](guide/03-cli-and-archive.md); [Chapter 7, Before you spend compute](guide/07-budgets-preview-cancel.md).

## Read results and provenance

Now in [Chapter 4, Can I trust this result?](guide/04-reading-a-result.md); [Chapter 3, The files of a run](guide/03-cli-and-archive.md#the-files-of-a-run).

## Native checkpoint and restart

Now in [Chapter 8, Checkpoint and restart](guide/08-checkpoint-restart.md).

## Rust library API

Now in [Chapter 20, The Rust library](guide/20-rust-library.md).

## Python automation API

Now in [Chapter 11, Python](guide/11-python.md); [Chapter 12, A fallible objective](guide/12-studies.md#a-fallible-objective).

## OpenFOAM workflows

Now in [Chapter 15, Install OpenFOAM and run a cavity](guide/15-openfoam-first-run.md); [Chapter 16, Compare solvers and measurements](guide/16-compare-solvers.md); [Chapter 17, Continue a solve, start a finer mesh](guide/17-continuation-and-mapping.md).

## Optimization and campaigns

Now in [Chapter 14, Optimization jobs](guide/14-optimization-jobs.md); [Chapter 13, Optimization lessons F1 to F3](guide/13-optimization-lessons.md); [Chapter 19, A bounded refinement campaign](guide/19-refinement-campaign.md).

## Verification and performance

Now in [The documentation check, Run the documentation check](developer/documentation.md#run-the-documentation-check); [Chapter 12, Many runs](guide/12-studies.md); [Chapter 16, Time both backends on one host](guide/16-compare-solvers.md#time-both-backends-on-one-host).

## Troubleshooting

Now in [Chapter 21, Troubleshooting](guide/21-troubleshooting.md).

## Example index and further reading

| Example | Now in |
|---|---|
| 1: build and discover the schemas | [Chapter 2, Find the allowed fields](guide/02-case-file.md#find-the-allowed-fields); [Chapter 3, Setup](guide/03-cli-and-archive.md#setup) |
| 2: a complete point-source calculation | [Chapter 3, Check, run, report](guide/03-cli-and-archive.md#check-run-report) |
| 3: read a receptor in physical units | [Chapter 1, Read a receptor](guide/01-first-run.md#read-a-receptor) |
| 4: inspect the complete input | [Chapter 2, The groups of a case](guide/02-case-file.md#the-groups-of-a-case) |
| 5: modify an input without changing the original | [Chapter 2, Change a case without touching the original](guide/02-case-file.md#change-a-case-without-touching-the-original) |
| 6: alternative source declarations | [Chapter 5, Three kinds of source, three rate units](guide/05-sources-receptors-transport.md#three-kinds-of-source-three-rate-units) |
| 7: validate and handle exit codes | [Chapter 11, Drive the CLI from Python](guide/11-python.md#drive-the-cli-from-python); [Chapter 3, Exit codes](guide/03-cli-and-archive.md#exit-codes) |
| 8: preview with a coarser grid | [Chapter 7, Preview on a coarser grid](guide/07-budgets-preview-cancel.md#preview-on-a-coarser-grid); [Chapter 7, When a preview is refused](guide/07-budgets-preview-cancel.md#when-a-preview-is-refused) |
| 9: export actual returned fields | [Chapter 3, Look at the fields in ParaView](guide/03-cli-and-archive.md#look-at-the-fields-in-paraview) |
| 10: use the pressure fixture | [Chapter 6, What the pressure step does](guide/06-flow-cavity.md#what-the-pressure-step-does) |
| 11: require a numerical verdict explicitly | [Chapter 4, Require a verdict in a script](guide/04-reading-a-result.md#require-a-verdict-in-a-script) |
| 12: interrupt by work, then resume to the same endpoint | [Chapter 8, Stop by work, then resume](guide/08-checkpoint-restart.md#stop-by-work-then-resume) |
| 13: inspect an interrupted calculation safely | [Chapter 4, An incomplete run is still a result](guide/04-reading-a-result.md#an-incomplete-run-is-still-a-result) |
| 14: an in-process typed solve | [Chapter 20, Solve in process](guide/20-rust-library.md#solve-in-process) |
| 15: cancellation and job deadlines | [Chapter 20, Cancellation and deadlines](guide/20-rust-library.md#cancellation-and-deadlines) |
| 16: library checkpoint round trip | [Chapter 20, Checkpoint round trip](guide/20-rust-library.md#checkpoint-round-trip) |
| 17: read a CLI archive from Rust | [Chapter 20, Read a CLI archive](guide/20-rust-library.md#read-a-cli-archive) |
| 18: execute the complete native API cookbook | [Chapter 11, The whole native workflow in one script](guide/11-python.md#the-whole-native-workflow-in-one-script) |
| 19: build a fallible optimization objective | [Chapter 12, A fallible objective](guide/12-studies.md#a-fallible-objective) |
| 20: install the pinned external runtime | [Chapter 15, Install the pinned runtime](guide/15-openfoam-first-run.md#install-the-pinned-runtime) |
| 21: generate, run and inspect a cavity | [Chapter 15, Generate, run and inspect](guide/15-openfoam-first-run.md#generate-run-and-inspect) |
| 22: use the source-checkout Python adapter | [Chapter 15, Use the adapter from Python](guide/15-openfoam-first-run.md#use-the-adapter-from-python) |
| 23: compare two solvers with a numerical reference | [Chapter 16, Two solvers against a numerical reference](guide/16-compare-solvers.md#two-solvers-against-a-numerical-reference) |
| 24: continue on the same external mesh | [Chapter 17, Continue on the same mesh](guide/17-continuation-and-mapping.md#continue-on-the-same-mesh) |
| 25: initialize a finer external mesh | [Chapter 17, Start a finer mesh](guide/17-continuation-and-mapping.md#start-a-finer-mesh) |
| 26: inspect the application worker | [Chapter 14, The application worker](guide/14-optimization-jobs.md#the-application-worker) |
| 27: execute real optimizer jobs | [Chapter 14, Run the four jobs](guide/14-optimization-jobs.md#run-the-four-jobs) |
| 28: prompt an agent with concrete boundaries | [Chapter 14, A task for an agent](guide/14-optimization-jobs.md#a-task-for-an-agent) |
| 29: run the manual's executable example checks | [The documentation check, Run the documentation check](developer/documentation.md#run-the-documentation-check) |
| 30: run scientific workflows | [Chapter 12, What sensors identify: the source-inference study](guide/12-studies.md#what-sensors-identify-the-source-inference-study); [Chapter 12, An independent reference solve](guide/12-studies.md#an-independent-reference-solve); [Chapter 10, All committed scenarios in one study](guide/10-street-canyon.md#all-committed-scenarios-in-one-study) |
| 31: reproduce the backend timing comparison | [Chapter 16, Time both backends on one host](guide/16-compare-solvers.md#time-both-backends-on-one-host); [CFD-craft, OpenFOAM and Ansys Fluent](comparison.md) |
