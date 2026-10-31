# Iteration 06: archive anomaly investigation

On a cloud machine, a sealed archive twice acquired an old time directory after
it was sealed, and the verifier rejected it (CFD-X006 `archive.progress`). It
has not happened in any GitHub run. This record states what was observed, what
the tests show and what remains unknown; the cause is not established.

## Observations

- **Staged study (continuation results).** After the workflow sealed a stage,
  its archive contained an additional `case/250` directory.
- **Cavity source.** A level-1 cavity run (2.25 s, converged at 696, saved times
  `0` and `696`) was reused later from the same working directory. The check
  then found saved times `0`, `500` and `696`, with an empty `case/500/uniform`.
  Every file still had its sealed size and hash: the change was an empty
  directory, which the file inventory does not list and the progress check
  does.
- **Timing.** The empty directory's modification time lies within the 2.25 s
  solve, its status-change time about 3.7 s later, after the run had returned.
  This fits something recreating the directory after the solver purged it, with
  its original time (a copy or synchronization step, for example), but it is
  not proof. A long campaign run was executing on the same machine at the time.
- **Repetition.** The same cavity source and campaign, regenerated under a fresh
  private path, verified at every checkpoint.

The rejected archives were kept unchanged, including the empty directory; a
file-only copy would lose this evidence.

## Process lifecycle

The backend starts each child in its own process session and always stops the
process group before `execute` returns, including when the leader has exited
(TERM, then KILL, then a wait). The real-process tests cover a timed-out group,
cancellation and an exited leader with a TERM-ignoring descendant, in normal and
optimized Python. Snapshot purging belongs to the solver while it runs; the
disk-budget scan tolerates files disappearing during `purgeWrite`, and the
numerical assessment and the final inventory happen after the child returns.
No defect was found that would explain the anomaly, and no process cleanup was
changed.

## Containment

The refinement campaign copies its source with checked bytes, verifies both
inventories, and reverifies every archive after each stage and at final
collection, requiring each archive to keep its first checkpoint's manifest. The
real-runtime tests add a late file (`case/123/U`) or an empty purged directory
(`case/200/uniform`) to a sealed cavity stage: the campaign stops at the next
checkpoint with CFD-X015 `refinement.archives.*` and the underlying CFD-X006,
starts no further stage, and leaves the archive, its manifest and the added
entry unchanged. These checks find when evidence stops matching its seal; they
do not prove exclusive ownership of a path.

## Next steps if it recurs

Keep the changed archive and its first failed checkpoint. Record file-system
events and processes for the run directory in a separately instrumented
reproduction. Do not delete the directory, reseal the run or infer a cause from
a clean repetition.
