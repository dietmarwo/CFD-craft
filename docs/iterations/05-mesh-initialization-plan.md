# Iteration 05: explicit coarse-to-fine field initialization

Date: 30 October 2026. Base: PR #5,
`e6134cd2e74d675819b8acd696af7d813c06809b`.

## Review and decision

PR #5 binds continuation receipts to source controls, metadata and snapshot
times, reads copied files once, requires runtime/mesh checks, reports every
stop reason and rejects pathological write cadences. It adds reproducible
comparison tools and qualifies the full 18412-iteration staged coarse backstep.
Keep these fixes and the existing source-flux gate. The review's early SIMPLEC
restart fails its fixed-work equivalence target; this is not evidence for
weakening eligibility or final acceptance.

The next prerequisite for a fine-grid campaign is a different operation:
initialize a newly generated finer case from accepted coarse volume fields.
It is not same-mesh continuation. The new mesh has no transferable face flux;
the normal solver initializes phi from its new U and corrects it. No initial
conservation or accepted fine-solution claim is made by preparation.

## Bounded implementation

1. Add `prepare-mapped`: current, cold-generated, numerically accepted source
   only, with a passing independent audit; same case, wall and solver package,
   exactly one finer supported level. Initial release excludes sources whose
   initial fields were already restarted or mapped. The recorded cold coarse
   control is a supported source; extending chain-source eligibility is later.
2. Invoke the separately licensed Foundation-13 `mapFields` utility with
   `-consistent -mapMethod mapNearest` on isolated checked copies. This is a
   bounded nearest-cell initialization, not conservative interpolation or an
   accuracy method. Do not copy OpenFOAM implementation code into the repo.
3. Import only mapped internal U/p and SST k/omega/nut. Keep target generated
   boundary definitions, dimensions, geometry, inlet and numerical controls
   byte-identical. Do not map phi or wall stress. Check finite field counts and
   turbulence signs. Preserve raw mapper outputs/templates/logs as inputs.
4. Seal a distinct initialization receipt: source case/manifest/fields, target
   metadata, cold templates, mapped fields, actual target mesh and exact runtime
   and mapper identities. Recheck derivation and input/receipt consistency before
   solving and during archive verification. Solved cases require the recorded
   runtime and successful mesh check. Failed preparation stays non-runnable and
   retains its diagnostic/log evidence.
5. Keep same-mesh restart schema/gate unchanged. After a mapped case completes,
   a same-mesh continuation binds to that parent and its actual final phi; remove
   the old mapping receipt from the new stage, whose own receipt identifies the
   parent. Work on the source grid is not counted as fine-grid iterations.
6. Test boundary preservation, exact nearest mapping on known fields, source
   eligibility, source-copy races, provenance, missing/altered evidence,
   runtime/mesh mismatch, limits, occupied outputs and optimized Python. Real
   Foundation-13 tests cover cavity 1->2 and an SST field-format fixture, clearly
   distinguished from an accepted turbulent flow.
7. Compare actual mapped and cold level-2 cavities with identical final
   settings. Require both nonlinear/local gates, U and anchored p maximum
   differences <=1e-4, and both Ghia centerline errors <=0.06. Predeclare these
   before the runs. Report all work including source/mapping overhead; make no
   speed claim from one run. Run required Rust/Ruff and native verification.

## Limits and delivery

No new accepted fine backstep, GCI or physical validation is promised by this
software iteration. A real fine SST campaign requires an accepted complete
coarse archive and bounded continuation after initialization. No source gate,
final residual, wall-y+ or measurement threshold changes. Native physics,
owner-machine benchmarks, GPU and MPI remain outside scope. All development
uses cloud CPU. Deliver the plan, patch ZIP, log and selected sealed evidence;
verify the patch on a pristine base checkout.

## Primary source

[Foundation 13 mapFields](https://cpp.openfoam.org/v13/mapFields_8C_source.html)
supports mapNearest/interpolate/cellPointInterpolate. This iteration deliberately
uses only mapNearest and original generated target boundary dictionaries.
