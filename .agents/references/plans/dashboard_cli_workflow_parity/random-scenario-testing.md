# Scenario-driven acceptance testing

## Current implementation

`python3 scripts/select_env_gen_scenario.py --print`

All ten scenarios and their original prompts are directly embedded in `SCENARIOS`
inside the Python script. The default command works without the Markdown notes.
`--print` emits readable JSON with the selected prompt, assets, sectors,
embodiment, background choices and selection provenance for an agent such as
Hermes. It does not import Arena, contact services or launch any workload.

The previous ID persists in `outputs/workflow/scenario-selection-state.json`.
Each invocation selects uniformly from the other nine scenarios; the first draw
has ten choices if no previous ID is known. Read/draw/save is file-locked across
processes. `--state PATH` creates a separate selection stream; `--previous B1`
can bootstrap a fresh stream from an earlier selection, but cannot override
conflicting saved history. Corrupt history is rejected rather than reset.

Manifests are automatically saved under `outputs/workflow/scenario-selections/`,
or at an explicit `--output PATH` (never overwritten). `--seed` makes a draw
repeatable only with the same catalogue and previous ID, both recorded alongside
the seed. The embedded catalogue is hash-bound; `--expected-source-sha256` can
pin that hash. An explicit `--catalogue PATH` remains available for legacy
Markdown input, whose hash covers the file bytes instead.

Keep the original `scenario.prompt` intact when refining it. Record the improved
prompt separately and preserve the intended object, target and embodiment.
Re-read the saved manifest to work on the same prompt: rerunning the command
selects a new scenario. B2 retains the notes' purple-crate target. Historical
geometry and policy identifiers still require runtime validation.

Checks: `python3 scripts/test_select_env_gen_scenario.py` (stdlib-only). Tests cover
exact membership/prompt preservation, replay, all-ID reachability, invalid seeds,
source drift, incomplete/duplicate pools, non-overwriting output, standalone
printing and persistent no-repeat behavior. Reachability is not a statistical
fairness or robotics acceptance claim. Excluding the previous ID prevents
immediate repeats, not all repeats or unequal finite-sample coverage. A shuffled
full-suite pass remains preferable when every scenario must be covered.

## Historical first draw (before persistent history)

- Scenario: B1, Tomato Soup to Blue Bin.
- Source object: `tomato_soup_can_ycb_robolab`.
- Target: `bin_b03_vomp_robolab`.
- Exact instruction: "Pick up the red tomato soup can from the front right of the counter and deposit it into the blue sorting bin."
- Manifest: `outputs/workflow/random-ab-selection/selection.json`.
- Status: `outputs/workflow/random-ab-selection/execution-status.json`.
- Execution: **not started**, not failed manipulation and not successful acceptance.

Reproduce that original scenario draw with the explicit legacy source and a
fresh, separate history (the newer manifest schema has additional provenance):

```sh
python3 scripts/select_env_gen_scenario.py \
  --catalogue .agents/references/agentic_env_generation/env_gen_test.md \
  --state outputs/workflow/random-ab-selection/legacy-replay-state.json \
  --seed 283762861765714602005983826927969950907 \
  --expected-source-sha256 bef7f3ea34c2d227679e7e07e3486d7e61fa2638997ed8f4e1c7804e0cbf1f80 \
  --output outputs/workflow/random-ab-selection/legacy-replay-v2.json
```

The updated selector was exercised with the earlier B1 as its bootstrap:
two successive fresh CLI calls selected **B1 → A1 → A2** with no consecutive
repeat. Those calls selected/printed metadata only; they were not robotics trials.

The live-scope clarification timed out. Native/live/research access therefore
remains unconfirmed, and the default application factory is isolated-only.
Selection is implemented; a native campaign driver/monitor is **not** implemented
by this selector. Do not feed the chosen name to the fixed synthetic fixture and
call that execution of B1. Do not reroll blocked selections to hide coverage gaps.

## Real acceptance composition and monitoring contract

Before dispatch, explicitly authorize effects and bind the real runtime/provider
adapters through the shared application. Freeze model identities, per-call
accounting bounds, total time/call/spend limits, allowed repair scope, source
catalogue identity, assets, embodiment, background and criterion definitions.
Discover actual runtime endpoints rather than using the notes' historical port.
Use an isolated operational workflow database; research reads require explicit
scope and research publication remains off. No service restart or install is
implied by selecting a scenario.

The application must own generation, realization/capture, assessment, any allowed
repair, fresh reassessment and the final decision. A monitor observes retained
run/attempt identities and available actions; it must not interpret VLM prose and
issue the next repair itself. Retain:

- Selection seed/source hash, immutable request and early admitted run handle.
- Stage transitions, original deadlines and conservative budget allocations.
- Original/revised specifications and parent-child lineage.
- Camera frames/video and measured predicates bound to each fresh cohort.
- Selected criterion verdicts, unknowns and stop reasons.
- Cleanup, cancellation delivery/durable disposition and resume outcome.

Keep three outcome fields separate: orchestration correctness, native scene
validity, and robot manipulation success. A scene accepted from images does not
prove pick-and-place success. Testing that final task outcome additionally needs
a supported policy-evaluation adapter, frozen GR00T identity, explicit episode
count/seeds and measured completion criteria; do not silently extend a scene-only
contract. Preserve every failed/blocked attempt and do not count incomplete
rollouts as successful episodes.

## Recommended complementary tests (not executed here)

1. **Seeded shuffled coverage:** one randomly ordered pass over all ten scenarios
   before repetition. This avoids gaps and repeated easy cases from independent
   draws. Persist the full order before any effects.
2. **Historical controls:** A1, B1 and B4 have prior completed runs. Use their
   retained artifacts for diagnosis, but compare rates only when scene, policy,
   seeds and success definitions are compatible.
3. **Repeated-seed robustness:** repeat a fixed scenario over declared placement/
   simulation seeds, with policy randomness separately recorded. Report successes
   and total completed episodes, not just a percentage from one trial.
4. **Metamorphic cases:** mirror source/target sectors or vary one allowed pose
   within the declared envelope. Keep prompt/geometry transformations explicit
   and check that unrelated constraints remain unchanged.
5. **Failure/recovery campaigns:** missing assets/prior/model, interruption at
   known-pending versus released stages, cancellation, budget exhaustion and stale
   evidence. Verify zero forbidden model calls, no uncertain redispatch and exact
   cleanup. Existing isolated tests are a baseline, not native fault evidence.
6. **Paired regression runs:** replay the same immutable inputs before/after a
   change, distinguishing stochastic model differences from deterministic
   orchestration regressions. Include stopped/blocked outcomes in the ledger.

Start with the retained B1 draw after authorization and real-adapter readiness;
then use a shuffled full-suite pass rather than an unbounded random loop.
