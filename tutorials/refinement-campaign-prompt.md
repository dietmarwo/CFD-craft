# Tutorial: a fine-grid result must earn acceptance

Goal: start from an accepted coarse calculation, initialize the next mesh once,
then run bounded same-mesh stages until the unchanged gates pass or the declared
limits stop the trial. Read the [campaign guide](../integrations/REFINEMENT_CAMPAIGN.md)
and [model card](../docs/model-cards/openfoam-backend.md).

Ask the agent to carry out the following task:

> Inspect a complete accepted cold level-1 wall-resolved SIMPLEC backstep
> archive. Verify its seals, actual returned fields, independent local-flux and
> all-wall y+ audit, measurement screen and exact runtime. Freeze a new trial
> before execution: target level 2, at most three stages of 4000 iterations,
> 3500 seconds per execution, preparation deadline 900 seconds, 1024 MiB output
> per stage and 4096 MiB child address space. Use the campaign driver in a fresh
> directory. Map once and continue only eligible completed fine stages.
>
> Keep every returned stage and the complete source. Report the final stage's
> iterations, cumulative completed fine iterations and the coarse source's
> historical work separately. Preserve numerical failures, stopped executions,
> source rejection and archive mismatches. Never loosen a gate, reseal changed
> output or use a pre-failure snapshot. Explain the actual stopping reason.
>
> If both grids pass the numerical and independent gates, compare their
> observables at the same physical sample identities. State their original
> measurement verdicts and the size of the grid changes. If either grid is not
> accepted, state that mesh sensitivity was not assessed. Two grids provide
> neither a GCI nor physical qualification. Describe the remaining inlet,
> refinement and model-form work. GPU and MPI work is out of scope.

The guide supplies the exact commands and limits. For a quick smoke exercise,
use an accepted cold cavity source and 400-iteration stages (up to four); its
Ghia reference is numerical, not experimental. The real-solver regression uses
that smaller exercise and checks both a converged chain and an intentionally
bounded, unconverged chain.

Questions the finished report must answer:

1. Which source bytes, producer code and runtime were actually consumed?
2. Which stage first met each gate, and what work was performed on each mesh?
3. Did the final source/parent/archive checks still pass at collection?
4. Which comparisons are assessed, and what does each `passed` field mean?
5. Which remaining scientific question can the next bounded trial resolve?
