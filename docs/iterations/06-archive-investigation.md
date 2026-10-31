# Iteration 06 archive investigation

The earlier cloud symptom was an unexpected old time directory appearing in an
archive after sealing. The verifier rejected it. Its original cause remains
unproven. This iteration separates an observed failure mode, controlled probes
and the disposition of real campaign evidence.

## Lifecycle review

The merged backend already launches each child in a fresh process session and
always calls `stop_process` before leaving `execute`, including when the leader
has exited. It sends TERM then KILL to the process group and waits for the
leader. Existing real-OS tests exercise a timed-out group, cancellation and an
exited leader with a TERM-ignoring descendant; they pass in both ordinary and
optimized Python. This is evidence for those controlled lifetimes, not a traced
explanation of the old anomaly. No observed defect justifies changing this
merged process cleanup.

Snapshot purging belongs to the solver while it runs. The backend's disk-budget
scan tolerates files disappearing during `purgeWrite`; numerical assessment and
the final inventory happen after the child returns. Inventories and seals do
not establish who wrote a later file. Run provenance and checksums alone cannot
identify an unrelated host writer.

The real backstep campaign uses a fresh private temporary output path. The
campaign snapshots checked source bytes, verifies both source/copy inventories,
and rechecks every complete parent/run archive after each stage and at final
collection. Selected archives are also checked before and after collection and
from the extracted delivery ZIP. These checks identify *when evidence ceases
to match its seal*. They do not prove exclusive ownership of a filesystem path.

## Controlled tests and retained probe

| Probe | Observed result and what it tests |
|---|---|
| Source bytes changed during copying | CFD-X015 `refinement.source.copy.*`; the copy is not promoted as a valid source |
| New source file after the checked reads | CFD-X015 `refinement.source.inventory`; the inconsistent snapshot is rejected |
| Parent manifest/case/time/runtime/work/field/mesh mismatch | Parent-chain rejection; coarse work cannot be added to fine work |
| Real mapped cavity, host adds `case/123/U` immediately after `backend.run` seals the archive | CFD-X015 `refinement.archives.stage_1_returned` with the underlying CFD-X006; no second stage, removal or reseal |

The last probe is retained in the ZIP under
`evidence/development/archive-late-file-probe`. Its receipt records successful
verification **before** the deliberate host write and the original manifest
hash. The unexpected file remains present and the original manifest is
unchanged. Its `report.json` is a workflow failure, not a numerical or physical
result. The successful test outcome is that this broken archive was rejected.
It is an injected post-seal writer, not a spontaneous reproduction of the
unknown original event.

## Actual recurrence in this iteration

A later attempt to reuse a separately generated cavity source in the working
directory was rejected by `CFD-X006 archive.progress`. At sealing and its first
verified use, the saved times were `0,696`. At the later check they were
`0,500,696`; `case/500/uniform` was empty. Every file still had its original
manifest size and hash, with no added, removed or changed file. The empty
directory affected the progress check rather than the file checksum inventory.

The rejected source was quarantined without deletion or resealing. Its full
archive, the observation receipt, directory timestamps and empty-directory
shape are retained under `evidence/development/archive-anomaly-source` and
`archive-anomaly-observation.json`. The ZIP includes directory entries as well
as files: omitting empty directories would lose this witness and could make a
later verifier accept a different filesystem shape. Reverification of this
quarantined archive must continue to fail with `archive.progress` after transfer
and extraction.

The accepted source snapshot in the earlier cavity campaign still verified.
For the final retained positive proof, the source and all stages were generated
again under a fresh private temporary path and checked there before collection.
This separates valid complete evidence from the rejected working-directory
source; it does not establish a filesystem or process root cause.

A new real-runtime regression deliberately recreates a purged empty
`case/200/uniform` directory after sealing. It requires immediate campaign
rejection, the original unchanged manifest, the preserved empty directory and
no second stage. A retained controlled empty-directory probe accompanies the
late-file probe. The existing strict progress rule is unchanged.

`validation/test_refinement.py` repeats the negative test against the real
Foundation-13 cavity in normal and optimized Python. The smaller source/copy
and lineage tests use explicitly synthetic fixtures; they supply no CFD claim.

## Separate development interruption

Review found a different defect in the new campaign layer: cancellation just
after an accepted solver return could leave the campaign's pass flag true.
Finalization now overrides pass/workflow status and records cancellation. Its
dedicated regression fails on the prototype and passes on the delivered code.
The early fine trial interrupted to deploy this correction had no sealed final
archive. Its partial report/log and exact prototype producer are retained
separately and never used for continuation or accepted work counts. This event
does not explain the original extra-time-directory symptom.

Two later long host sessions also disappeared without returning solver records
or seals, including a heartbeat-monitored repetition. Their last observed
started iterations were 1457 and 1193; the exit statuses and mechanism are
unknown. Their partial logs/reports and producing code are retained separately.
Neither unsealed field is used as a source. The
[plan amendment](06-refinement-campaign-plan.md#local-execution-amendment)
declares a fresh shorter local proof; the larger convergence experiment remains
configured for manual CI. These host interruptions are separate from the
observed empty-directory progress failure.

## Disposition

The [actual campaign results](../../validation/REFINEMENT_RESULTS.md) state
which complete archives survived collection and what scientific gates passed.
The original anomaly remains **unresolved**. Checked copying, complete parent
retention and repeated rejection checks provide tested containment. If it
recurs, retain the changed archive and its first failed checkpoint; inspect
writer/process and filesystem events in a separately instrumented reproduction.
Do not delete the unexpected directory, reseal the run or infer a root cause
from a successful private-path repetition.
