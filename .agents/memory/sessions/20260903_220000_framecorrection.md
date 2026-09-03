# Architectural Session Checkpoint: Frame Measurement Invalidates the C1 Vertical-OOD Diagnosis

- **Date / Timestamp**: 2026-09-03 22:00:00 UTC
- **Session UUID**: `framecorrection`
- **Topic**: Phase 0 frame measurement; relational support-invariant implementation; sweep generator
- **Status**: Correction landed / Active

---

## 1. The Headline: the 80 cm Vertical Gap Does Not Exist

`isaaclab_arena_examples/tools/measure_embodiment_frames.py` was run against both scenes. Measured, in one convention:

| | galileo (corpus) | maple table v9 (failing) | Δ |
| :--- | ---: | ---: | ---: |
| robot root / pelvis world z | −0.0445 | +0.0954 | |
| left shoulder world z | +0.2476 | +0.3865 | |
| **apple relative to pelvis** | **+0.0399** | **−0.0251** | **0.065 m** |
| apple → shoulder distance | 0.4315 | 0.4744 | 0.043 m |

**The two scenes differ by 6.5 cm in manipulation height, not 80 cm.** Both shoulder-to-target distances (0.43 m, 0.47 m) sit inside the documented 0.35–0.48 m comfortable band.

### Root cause of the error

The G1's articulation root **is** its pelvis (`G1SupplementalInfo.root_frame_name == 'pelvis'`, confirmed in the sim log). The `−0.8015 m` invariant came from comparing a world-frame shelf z (−0.03) against an assumed *foot-level* base frame with a +0.75 m pelvis offset. That offset does not exist: a spec's `initial_pose.z` already **is** the pelvis height. Every height comparison built on it was inflated by three quarters of a metre.

The assumed 0.75 appeared independently in two places — `policy_capability_graph` and `spatial_geometric_oracle:423` — which is how it survived review.

Measured replacements, reproducible to ~1 mm across both scenes:

```python
FRAME_HEIGHT_ABOVE_BASE_M = {"base": 0.0, "pelvis": 0.0, "shoulder": 0.292}
```

Note also that whole-body control settles the pose after reset: declared root z and realised pelvis z differ by up to ~0.1 m (galileo declared 0.0 → realised −0.0445; maple declared 0.0007 → realised +0.0954). Spec-only analysis is inherently approximate at that scale.

## 2. What C1 Is Actually Out of Distribution On

Re-running `diagnose_transfer_readiness` with measured frames:

```
  ok  surface_height_rel_pelvis   sigma=0.20   +0.0696 m  vs corpus +0.0400 m
 OOD  lateral_offset_rel_base     sigma=1.17   +0.0587 m  vs corpus +0.1990 m
  ok  arm_laterality              sigma=0.00   left       vs corpus left
 OOD  prompt_template             sigma=1.00   C1 wording vs corpus wording
 OOD  visual_domain               sigma=1.00   maple_table_robolab vs galileo shelf
  ok  controller_binding          sigma=0.00   g1_wbc_agile_joint (correct)

dominant_failure_mode: vision_domain_ood
scene-preserving remediation: visual_domain_randomization_finetune
```

Two claims from the C1 autopsy are now **retracted**:

1. **The 80 cm vertical OOD gap** — off by an order of magnitude; height is within tolerance.
2. **The right-arm/left-arm contradiction** — the *measured* layout puts the apple slightly **left** of the base centreline, matching the corpus. "Right arm" appears only in the C1 task *description text*, not in the built scene. The v9 spec assigns `red_apple` to `front_left`.

What survives: **prompt wording** and **visual domain**, plus a mild lateral offset (1.17× tolerance). The dominant mode is now `vision_domain_ood`, and the scene-preserving remediation the planner selects is `visual_domain_randomization_finetune` — which is exactly the direction chosen in session `transferplan`. The plan was right; the reasoning offered for it was not.

## 3. Implementation Landed

- **Relational invariants.** `TrainingInvariant` gained `constrains_relation` / `relative_to_frame`; the height and lateral invariants are now relational. `resolve_support_relation()` traverses the graph — `nominal_height` > `surface_sector` deck > explicit pose, mirroring `object_placer._sample_on_surface` — and returns the `height_source` so evidence strength is auditable. It works on specs whose objects carry **no** pose, which is the normal case for generated scenes and which the old pose-indexing code could not handle at all.
- **`KinematicManifold` as a class.** All 8 free-text `kinematic_manifold` strings found in `generated_envs/` are now registered, split into `support_envelope` vs `trajectory`, with two marked non-canonical aliases so the canonical envelopes remain a partition. A test scans the specs so an unregistered value fails CI rather than resolving to nothing.
- **`support_relation_sweep.py`.** One relational edit, three realisations (`anchor` / `fixture` / `platform`), and it **refuses** rather than emitting a variant whose offset no surface supports. Ties in deck height resolve toward the base spec's sector family — `galileo_locomanip` declares `front_center`/`front_left`/`front_right`/`shelf_tier_1` all at −0.03 with *different lateral bounds*, so picking arbitrarily would change laterality as a side effect of a height sweep.
- **Wiring.** `--policy_ref` on the runner (falling back to `checkpoint_uri` in the policy config, now added to the v9 config), a warn-only pre-flight gate on `build`/`full`, and planner reporting plus `policy_diagnostics.ttl` emission in `auto_heal`.
- **Probe.** Accepts numpy and un-batched action output, i.e. the `Gr00tPolicy` path.

## 4. Consequence for the Phase 1 Sweep Design

In the corrected frame, `galileo_locomanip`'s declared decks sit at −0.03, **+0.50**, and **+0.90** relative to the pelvis. Tiers 2 and 3 are therefore *overhead* reaches — 0.21 m and 0.61 m above the shoulder. `resolve_manifold_for_offset(0.90)` returns `None`, i.e. outside every registered envelope, and the graph now reports that as `kinematic_unreachable` rather than `vertical_reach_ood`.

So **the three-tier sweep is not a gentle height ladder**; tier 3 is likely beyond the arm, and a failure there would confound "the policy cannot" with "the robot cannot reach". A useful sweep needs offsets between roughly −0.20 m and +0.20 m, which on this fixture means `fixture` or `platform` realisation rather than anchor re-selection.

## 5. Also Found

- `num_rerenders_on_reset = 0` in the generated maple env, versus `1` in the reference factory (`galileo_g1_static_pick_and_place_environment.py:290`). The reference sets it so the policy does not condition on the previous episode's final rendered frame. **A live defect for a vision-conditioned policy**, and concrete evidence for implementation-plan risk §9.7 — the generated env silently lacks a guarantee the hand-tuned one provides.
- The v9 apple carries `scale: 0.01` against the reference factory's tuned `0.009`.

---

## 6. References

- `.agents/references/plans/g1_policy_transfer_implementation_plan.md`
- `.agents/memory/sessions/20260903_190000_transferplan.md`, `20260903_043800_c1blockers.md`
- Measurements: `eval_output/frames/galileo_static.json`, `eval_output/frames/maple_v9.json`
