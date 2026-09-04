# Implementation Plan: G1 Policy Transfer Diagnosis (Code-Level)

> [!IMPORTANT]
> **Status**: ACTIVE — the code-level companion to `g1_policy_transfer_and_height_invariance_plan.md`, which holds the strategy and the falsification criteria. This document holds the diffs, commands, and acceptance criteria.
> **Two findings from reviewing the repository changed the implementation**:
> 1. The height sweep is **not** a YAML change. The corpus-aligned scene is a Python factory with a hardcoded shelf constant and an invisible collision patch (§2.1). The sweep becomes a ~20-line change to one file plus a shell loop — cheaper and far more controlled than authoring graph specs.
> 2. The `−0.8015 m` corpus invariant **may be frame-confused**, not merely un-toleranced (§1). If so, the height axis is mis-parameterised at its root, and the sweep must start by measuring frames rather than success rates.

> [!NOTE]
> **Phase numbering in this document is superseded by [`g1_pick_success_phases.md`](g1_pick_success_phases.md)** (canonical `P0`-`P6` tracker, 2026-09-04). The sections here remain valid as detail; cite phases from the tracker.

---

## 1. Phase 0 — Resolve the Frame Ambiguity First — **DONE 2026-09-03, and it changed the diagnosis**

> [!IMPORTANT]
> **Measured. The 80 cm vertical gap does not exist.** `measure_embodiment_frames.py` against both scenes:
>
> | | galileo (corpus) | maple v9 (failing) | Δ |
> | :--- | ---: | ---: | ---: |
> | pelvis world z | −0.0445 | +0.0954 | |
> | **apple rel. pelvis** | **+0.0399** | **−0.0251** | **0.065 m** |
> | apple → shoulder | 0.4315 | 0.4744 | 0.043 m |
>
> The G1's articulation root **is** its pelvis, so the assumed +0.75 m base-to-pelvis offset does not exist and inflated every height comparison by that amount. Measured constants, reproducible to ~1 mm across both scenes: `{"base": 0.0, "pelvis": 0.0, "shoulder": 0.292}`.
>
> **Two C1 claims are retracted**: the 80 cm vertical OOD gap (height is *within* tolerance at 0.20×), and the right-arm contradiction (the measured layout is **left**, matching the corpus — "right arm" appears only in the task description text). What survives is prompt wording, visual domain, and a mild 1.17× lateral offset. Dominant mode is now `vision_domain_ood`, and the scene-preserving remediation the planner selects is `visual_domain_randomization_finetune` — the direction already chosen, though for the wrong stated reason.
>
> Full detail: `.agents/memory/sessions/20260903_220000_framecorrection.md`.
>
> **Consequence for §2.7**: in the corrected frame galileo's decks sit at −0.03, **+0.50**, **+0.90** relative to the pelvis, so tiers 2 and 3 are *overhead* reaches (0.21 m and 0.61 m above the shoulder). Tier 3 resolves outside every registered envelope and is likely beyond the arm — a failure there would confound "the policy cannot" with "the robot cannot reach". A usable sweep needs offsets in roughly [−0.20, +0.20] m, which on this fixture means `fixture` or `platform` realisation, not anchor re-selection. **The condition table in §2.7 is superseded by this.**

### The problem found during review (retained for the record)

The `surface_height_rel_pelvis = −0.8015 m` invariant is contradicted by the reference environment's own constants:

| Source | Value |
| :--- | :--- |
| `galileo_g1_static_pick_and_place_environment.py:45` | `SHELF_SURFACE_Z = -0.030` (env-local) |
| `:241` robot initial pose | `position_xyz=(0.25, 0.08, 0.0)` |
| `:239-240` comment | "The controller dynamically lifts the pelvis to ~z=0.74 at runtime" |
| `:56` apple spawn XY | `(0.5785, 0.27)` → ~0.33 m forward of the robot base |
| `g1_humanoid_vlm_agentic_debugging_and_remediation.md` §7 | Left shoulder at `Z = 1.050`; max arm reach `0.65 m`; comfortable band `0.35–0.48 m` |

Taking those at face value: the apple sits `−0.03 − 0.74 ≈ −0.77 m` below the pelvis and `≈ −1.08 m` below the shoulder, at `0.33 m` forward — a shoulder-to-target distance near `1.13 m`, against a stated maximum reach of `0.65 m`. **That is kinematically impossible, yet this environment is documented at `success_rate: 1.0`.**

So at least one of these is wrong: the pelvis height, the shoulder height, the reach limit, or the frame that `SHELF_SURFACE_Z` is expressed in. Every quantitative claim about the height axis — the invariant's value, its tolerance, and `vertical_reach_ood`'s rank — inherits the error.

### Action: instrument the reference environment

New file `isaaclab_arena_examples/tools/measure_embodiment_frames.py`. It builds a registered environment, steps it to a settled standing pose, and prints world-frame positions of the pelvis, both shoulders, both wrists, the manipuland, and the support surface, plus the derived relative offsets.

```python
# Sketch. Follows the inner/outer sim-app pattern used across isaaclab_arena_examples/tools/.
def _measure(simulation_app) -> bool:
    env = _build_registered_env(env_name="galileo_g1_static_pick_and_place",
                               embodiment="g1_wbc_agile_joint")
    env.reset()
    _step_standing(env, num_steps=60)          # let WBC settle the pose

    robot = env.unwrapped.scene["robot"]
    body_names = robot.body_names               # discover, do not assume
    idx = {n: body_names.index(n) for n in body_names
           if any(k in n for k in ("pelvis", "shoulder", "wrist", "torso"))}
    pos_w = wp.to_torch(robot.data.body_pos_w)[0]        # (num_bodies, 3)
    origin = env.unwrapped.scene.env_origins[0]

    for name, i in sorted(idx.items()):
        print(f"{name:32s} world={pos_w[i].tolist()}  env_local={(pos_w[i]-origin).tolist()}")

    apple = wp.to_torch(env.unwrapped.scene["apple_01_objaverse_robolab"].data.root_pos_w)[0]
    pelvis_z = float(pos_w[idx["pelvis"]][2])
    print(f"apple_rel_pelvis_z = {float(apple[2]) - pelvis_z:+.4f}")
    print(f"shoulder_to_apple  = {torch.linalg.vector_norm(apple - pos_w[idx['left_shoulder_...']]):.4f}")
    return True
```

Run against **both** scenes so the two are measured in one comparable frame:

```bash
# reference (corpus) scene
docker exec "$ARENA_CONTAINER" su $(id -un) -c "cd /workspaces/isaaclab_arena && \
  /isaac-sim/python.sh isaaclab_arena_examples/tools/measure_embodiment_frames.py \
  --headless galileo_g1_static_pick_and_place --embodiment g1_wbc_agile_joint"

# the failing generated scene
docker exec "$ARENA_CONTAINER" su $(id -un) -c "cd /workspaces/isaaclab_arena && \
  /isaac-sim/python.sh isaaclab_arena_examples/tools/measure_embodiment_frames.py \
  --headless --env_graph_spec_yaml generated_envs/g1_tabletop_apple_to_plate/v9/g1_tabletop_apple_to_plate.yaml"
```

### Code changes that follow from the measurement

1. `policy_capability_graph.py` — replace the assumed constants with measured ones:
   - `_PELVIS_HEIGHT_ABOVE_BASE_M = 0.75` → the measured standing pelvis height. Currently mirrors `spatial_geometric_oracle.py:423`, which uses the same unverified `0.75`.
   - `POLICY_PROFILES[...].invariants` → `surface_height_rel_pelvis.numeric_value` from the measured apple-to-pelvis offset.
2. If the pelvis frame turns out to be the wrong reference, change the **axis** rather than patching the number. A `surface_height_rel_shoulder` axis is the better parameterisation, because reach feasibility is a shoulder-relative property and the invariant exists to predict reach feasibility.
3. `spatial_geometric_oracle.py:423` carries the same `+ 0.75` assumption inside the kinematic-oracle warning path; fix both or neither, and add a shared constant so they cannot drift.

### Acceptance criteria

- Measured `apple_rel_pelvis_z` for the reference scene either confirms `−0.8015 ± 0.05 m` or replaces it.
- Measured shoulder-to-apple distance is inside the arm's actual reach envelope — if it is not, the reach figures in the notes are wrong and get corrected there too.
- `python -m pytest isaaclab_arena/tests/test_policy_capability_graph.py` still passes; `test_tabletop_scene_is_out_of_distribution_on_the_documented_axes` asserts `magnitude ≈ 0.833` and will need updating with the measured value. **Expect that test to change — it currently encodes the assumption.**

---

## 2. Phase 1 — The Support-Relation Sweep

> [!IMPORTANT]
> **Revised after review feedback.** An earlier draft of this phase proposed adding a `shelf_surface_z` float to one environment factory. That was wrong in kind, not just in scope: it treats the problem as being about *shelves and tables* when the invariant is actually about a **relation** — an object must rest on a support surface, and that surface must stand in a particular geometric relation to the robot. Both halves are relations the graph already models. A float on one Python class expresses neither, generalises to nothing, and bypasses the very representation this project exists to build.
> The design below expresses the invariant relationally and makes the sweep a graph operation. §2.7 retains the factory parameterisation as a fallback only.

### 2.0 The invariant is a property of a relation triple

What the policy actually depends on is not "the table height". It is the composite:

```
(embodiment)  --arena:standsAtAffordance-->  (support_fixture)
(manipuland)  --arena:placedOnSubSurface-->  (anchor of support_fixture)
```

together with the vertical offset between the anchor and a named frame on the embodiment. Reaching is a relative act; only the relation is invariant across scenes. Two scenes with identical absolute heights but different robot stances are *not* equivalent for the policy, and two scenes with different absolute heights but the same relation *are*.

Everything needed to say this already exists in the graph and is unused for the purpose:

| Existing construct | Where | Currently |
| :--- | :--- | :--- |
| `arena:standsAtAffordance` + `arena:standoffDistance` | `rdf_lowering.py:477-478` | Emitted with a **hardcoded 0.85** standoff, never read back |
| `arena:placedOnSubSurface`, `arena:SurfaceAnchor` | `arena_schema.ttl:99`, `rdf_lowering.py:441` | Emitted, never constrained |
| `arena:nominalHeight` | `rdf_lowering.py:452`, `object_placer.py:556` | **Overrides placement surface height outright** — asset-agnostic |
| `ReifiedRelationSpec.kinematic_manifold` | `arena_env_graph_types.py:367` | Free text (`tabletop_stationary_reach`, `countertop_stationary_reach`, `unitree_g1_bimanual_chest_height`) that nothing validates |
| `ReifiedRelationSpec.delta_z` interval | `arena_env_graph_types.py` | Carries a min/max/nominal interval already |

So the work is not to invent a mechanism. It is to **give these an invariant to be checked against**, and to make the sweep a traversal of them.

### 2.1 Ontology change: relational invariants and manifolds as classes

Add to `ontology/arena_policy_diagnostics.ttl`:

```turtle
arena:SupportRelationInvariant a owl:Class ;
    rdfs:comment "A training invariant over a relation triple rather than a scalar attribute. "
                 "Constrains the vertical and lateral offset between a support anchor and a named "
                 "embodiment frame, for the relation pattern a policy was trained on." ;
    rdfs:subClassOf arena:TrainingInvariant .

arena:KinematicManifold a owl:Class ;
    rdfs:comment "A named region of the embodiment's reach space, e.g. low_shelf_reach_down vs "
                 "tabletop_stationary_reach. Promoted from the free-text kinematic_manifold field "
                 "so a corpus can declare which manifolds it covers and a scene can be checked "
                 "against them." ;
    rdfs:subClassOf prov:Entity .

arena:coversManifold    a owl:ObjectProperty ;   # DemonstrationCorpus -> KinematicManifold
arena:instantiatesManifold a owl:ObjectProperty ;# ReifiedRelation    -> KinematicManifold
arena:constrainsRelation   a owl:DatatypeProperty ; # e.g. "PLACED_ON"
arena:relativeToFrame      a owl:DatatypeProperty ; # "pelvis" | "shoulder" | "base"
arena:supportAnchorRole    a owl:DatatypeProperty ; # which role in the triple carries the height
arena:manifoldZMin, arena:manifoldZMax, arena:manifoldReachMin, arena:manifoldReachMax
                           a owl:DatatypeProperty .
```

The C1 diagnosis then reads as a **manifold mismatch with a continuous parameterisation** — the scene's support relation instantiates `tabletop_stationary_reach` while the corpus covers only `low_shelf_reach_down` — which is a far more actionable statement than "a scalar is 5.6x off a tolerance". It also explains *why* remediation options differ: a manifold mismatch is categorical, so no config patch closes it; only re-training or re-relating does.

### 2.2 Measurement change: traverse the graph, do not index into poses

`compute_distribution_shifts` currently does this (`policy_capability_graph.py`):

```python
target_pos = _position_of(manipuland)          # objects[0].params.initial_pose.position_xyz
observed = target_pos[2] - _pelvis_height(base_pos)   # base_z + hardcoded 0.75
```

Three defects, all of a kind: it assumes the manipuland carries an explicit pose (in the v9 spec **it does not** — the objects have no `initial_pose`; the placer derives it from the relation), it hardcodes the pelvis offset (the source of the frame bug in §1), and it cannot see the support surface at all.

Replace with a resolver that reads the relation:

```python
@dataclass(frozen=True)
class SupportRelation:
    """The resolved (embodiment, support surface, manipuland) triple for one scene."""
    manipuland_id: str
    fixture_id: str
    anchor_name: str | None
    surface_z: float | None       # from nominal_height, else sector deck, else fixture bbox top
    height_source: str            # "nominal_height" | "surface_sector" | "fixture_bbox" | "explicit_pose"
    manifold: str | None          # from the reified relation
    embodiment_frame_z: float | None


def resolve_support_relation(spec, embodiment_frame: str = "pelvis") -> SupportRelation | None:
    """Resolve the support relation by traversing relations, not by indexing object poses.

    Precedence mirrors ``object_placer._sample_on_surface``: an explicit ``nominal_height`` on the
    ``on`` relation wins, then a named ``surface_sector``/``surface_anchor`` deck from
    ``FIXTURE_SECTOR_BOUNDS``, then the fixture's bounding-box top. Returning the source alongside
    the value keeps the provenance auditable -- a shift measured off a bbox estimate is weaker
    evidence than one measured off a declared nominal height.
    """
```

This makes the measurement work for any fixture and any scene, and — importantly — makes it work for specs where the object pose is *derived* rather than declared, which is the normal case for generated environments.

### 2.3 The sweep is a graph generator, not an env flag

One relational intervention — change the support anchor's offset relative to the embodiment frame — with **three admissible physical realisations**. They are equivalent in the graph and differ only in plausibility, so the choice is recorded as provenance rather than hidden:

| Realisation | Graph edit | Physically sound? | Visually sound? |
| :--- | :--- | :--- | :--- |
| **R1 — anchor re-selection** | `relations[on].params.surface_sector: shelf_tier_1 → shelf_tier_3` | Yes, a real deck | Yes |
| **R2 — fixture translation** | `background.params.initial_pose.position_xyz[2] += Δ` | Yes | Legs/base float above the floor |
| **R3 — embodiment platform** | `embodiment.params.initial_pose.position_xyz[2] += Δ` | Yes, robot on a platform | Yes, if a platform is added |

R1 is preferred wherever the fixture declares multiple decks; R2 and R3 cover continuous sweeps on single-surface fixtures. All three are already supported spec edits — R2 is exactly what `EvaluationRemediationEngine` does today for the X axis (`eval_self_healing.py:555-566`).

> [!WARNING]
> `nominal_height` overrides the placement height **without creating a surface there**. Setting it alone makes the object spawn in mid-air and fall — which measures gravity, not reach. Any sweep step must pair the required relation height with a realisation that puts a real support surface at it. This is the concrete form of the user-visible invariant: *the object must exist on a surface, and that surface must relate to the robot.*

New generator `isaaclab_arena/agentic_environment_generation/support_relation_sweep.py`:

```python
def generate_support_height_sweep(
    base_spec: ArenaEnvGraphSpec,
    offsets_m: Sequence[float],
    realization: str = "auto",          # "anchor" | "fixture" | "platform" | "auto"
    embodiment_frame: str = "pelvis",
) -> list[tuple[float, ArenaEnvGraphSpec]]:
    """Emit one spec variant per requested support-relation offset.

    ``auto`` picks anchor re-selection when the fixture declares a deck within tolerance of the
    requested offset, and falls back to fixture translation otherwise. Each variant carries the
    realisation and the requested offset in its reified relation so the sweep is reconstructable
    from the graph alone.
    """
```

Each variant is then materialised through the **existing** versioning path rather than an ad-hoc output tree:

```python
mgr = EnvironmentVersionManager(f"{base_spec.env_name}_height_sweep")
for offset, variant in generate_support_height_sweep(base, [-0.80, -0.55, -0.30, -0.05]):
    mgr.create_version(spec_source=variant, policy_config_source=policy_cfg,
                       trigger="support_relation_sweep",
                       remediations=[f"support offset {offset:+.2f} m via {realization}"])
```

so `lineage.json` / `lineage.ttl` record the sweep as a derivation family, and the eventual success-vs-offset curve attaches to graph nodes instead of living in a spreadsheet.

### 2.4 What this buys over the ad-hoc version

- **Asset-agnostic.** Runs on `galileo_locomanip`, `maple_table_robolab`, `wireshelving_a01`, any future fixture, with no per-environment Python.
- **Reusable for the other axes.** `standoffDistance` (currently hardcoded to 0.85 and never read) and lateral offset are the same kind of relational invariant; once the resolver exists, sweeping them is a parameter change.
- **The measured tolerance lands on the right object.** It becomes a property of a `SupportRelationInvariant` / `KinematicManifold`, queryable by any scene, rather than a scalar bolted to one policy profile.
- **The pre-flight gate gets teeth.** `diagnose_transfer_readiness` can answer "does this scene's support relation instantiate a manifold this corpus covers" for a scene it has never seen.

### 2.5 Legacy factory findings (retained — still true, now supporting detail)

`isaaclab_arena_environments/galileo_g1_static_pick_and_place_environment.py` is a `@register_environment` factory, not a graph spec. The relevant machinery:

| Line | Construct | Role |
| :--- | :--- | :--- |
| 45 | `SHELF_SURFACE_Z = -0.030` | Module constant; the shelf top |
| 46 | `SHELF_AIRGAP = 0.005` | Anti-penetration gap |
| 47–49 | `SHELF_SUPPORT_PATCH_SIZE/CENTER` | An **invisible** `CuboidCfg` support patch |
| 196–218 | `class StaticShelfSupport` | The patch objects actually rest on — the visible shelf mesh has perforated collision |
| 75–78 | `_USD_ORIGIN_ABOVE_BOTTOM_M` | Per-asset origin-to-bottom offset (apple `0.0171`, plate `0.0`) |
| 119–134 | `_shelf_spawn_z()` | `SHELF_SURFACE_Z + SHELF_AIRGAP + origin_offset` |
| 86–89 | `_TUNED_SCALES` | apple `(0.009,)*3`, plate `(0.5,)*3` |

Two consequences:

- **Objects rest on the invisible patch, not the visible shelf.** So height is controlled by two numbers moving together — the patch centre and the spawn Z — and the visible mesh does not constrain it. This is why the sweep is cheap.
- **But the visible mesh does constrain *what the policy sees*.** At an arbitrary height the object floats in mid-air relative to the rendered shelf, which is a visual anomaly that would confound a vision-conditioned measurement. The sweep must therefore prefer heights coinciding with real decks. `FIXTURE_SECTOR_BOUNDS["galileo_locomanip"]` (`spatial_geometric_oracle.py:36`) declares exactly three: `−0.03`, `+0.50`, `+0.90` — and `−0.03` matches `SHELF_SURFACE_Z` exactly, confirming they share the frame.

### 2.6 Fallback only — parameterise the reference factory directly

> [!NOTE]
> Use this **only** if §2.3's generator is blocked, or as a one-off to unblock the Phase 0 frame measurement. It is a per-environment hack: it generalises to nothing, records nothing in the graph, and duplicates in Python a control the spec already expresses as `arena:nominalHeight`. Prefer R1/R2/R3.

Edit `galileo_g1_static_pick_and_place_environment.py`. Add to the cfg dataclass (`:150`):

```python
@dataclass
class GalileoG1StaticPickAndPlaceEnvironmentCfg(ArenaEnvironmentCfg):
    ...
    shelf_surface_z: float = SHELF_SURFACE_Z
    """Env-local Z of the manipulation surface. Defaults to the measured shelf top.

    Exposed so the manipulation height can be swept while every other property of the
    scene is held fixed, which is what isolates the height axis from the visual domain.
    Prefer values coinciding with a real deck in the shelf mesh (see
    ``FIXTURE_SECTOR_BOUNDS['galileo_locomanip']``: -0.03, 0.50, 0.90); at other values
    objects rest on the invisible support patch and appear to float, which is physically
    correct but visually anomalous to a vision-conditioned policy.
    """
```

Then make the three consumers read `cfg.shelf_surface_z` instead of the module constant. `_shelf_spawn_z` and `SHELF_SUPPORT_PATCH_CENTER` are currently module-level, so both must become surface-parameterised:

```python
def _shelf_spawn_z(asset_name: str, shelf_surface_z: float = SHELF_SURFACE_Z) -> float:
    if asset_name in _USD_ORIGIN_ABOVE_BOTTOM_M:
        return shelf_surface_z + SHELF_AIRGAP + _USD_ORIGIN_ABOVE_BOTTOM_M[asset_name]
    warnings.warn(...)
    return shelf_surface_z + SHELF_AIRGAP


def _shelf_support_patch_center(shelf_surface_z: float) -> tuple[float, float, float]:
    """Patch centre such that its top face sits at ``shelf_surface_z``."""
    return (0.62, 0.0, shelf_surface_z - SHELF_SUPPORT_PATCH_SIZE[2] / 2.0)
```

In `build()`: pass `cfg.shelf_surface_z` into `StaticShelfSupport` (which becomes parameterised rather than a zero-arg class) and into both `_shelf_spawn_z` calls at `:245` and `:269`.

**This costs no new CLI plumbing.** `isaaclab_arena_environments/cli.py:168-174` creates an argparse **subparser per registered environment** with flags generated from its cfg dataclass. A new dataclass field becomes `--shelf_surface_z` automatically.

### 2.7 The sweep conditions

Conditions are stated as **support-relation offsets**, not asset heights — the same offsets apply to any fixture. Frame values are pending Phase 0; the rel-pelvis column assumes a 0.74 m standing pelvis and **must be recomputed** from the measurement.

| # | Fixture | Realisation | Support offset rel. frame (provisional) | Visual domain | Isolates |
| :-- | :--- | :--- | ---: | :--- | :--- |
| A | `galileo_locomanip` | R1 `shelf_tier_1` | −0.77 | corpus | **Positive control** |
| B | `galileo_locomanip` | R1 `shelf_tier_2` | −0.24 | corpus | Support relation only |
| C | `galileo_locomanip` | R1 `shelf_tier_3` | +0.16 | corpus | Support relation only, above target |
| D | `maple_table_robolab` | v9 spec as-is | +0.03 | fully novel | Relation + visual (the failing case) |
| E | `wireshelving_a01` | R1 `shelf_tier_1` | +0.01 | shelf-like, non-corpus | Relation at target, visual partly held |

A–C differ in **one graph edit** — the `surface_sector` naming the support anchor — with laterality, prompt, scale, friction, embodiment, and fixture identical. That is what makes the contrast attributable, and it now holds because the *relation* is the variable, not a Python constant.

> [!NOTE]
> Condition E is worth running but is not a clean contrast: different mesh and collision, and no tuned `_USD_ORIGIN_ABOVE_BOTTOM_M` / `_TUNED_SCALES` entries, so the reference factory's fallback warnings (`:128`, `:141`) would fire. Under the relational route those tunings become per-fixture graph data rather than per-env Python — which is the general fix, but out of scope for this phase. Treat E as exploratory, after A–D.

### 2.8 Commands

Generate the variant family once (no simulator), then evaluate each:

```bash
# 1. Emit the sweep as versioned spec variants with lineage.
docker exec "$ARENA_CONTAINER" su $(id -un) -c "cd /workspaces/isaaclab_arena && \
  /isaac-sim/python.sh -m isaaclab_arena.agentic_environment_generation.support_relation_sweep \
    --base_spec generated_envs/g1_tabletop_apple_to_plate/v9/g1_tabletop_apple_to_plate.yaml \
    --fixture galileo_locomanip --realization anchor \
    --anchors shelf_tier_1 shelf_tier_2 shelf_tier_3"

# 2. Evaluate each variant through the normal graph-spec path.
for V in 1 2 3; do
  docker exec "$ARENA_CONTAINER" su $(id -un) -c "cd /workspaces/isaaclab_arena && \
    /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
      --headless --enable_cameras --num_envs 4 --num_episodes 20 \
      --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \
      --policy_config_yaml_path generated_envs/g1_tabletop_apple_to_plate/v9/policy_config.yaml \
      --remote_host 127.0.0.1 --remote_port 5557 \
      --language_instruction 'move the apple to the plate' \
      --check_settling \
      --env_graph_spec_yaml generated_envs/g1_tabletop_apple_to_plate_height_sweep/v${V}/g1_tabletop_apple_to_plate.yaml \
      --output_base_dir eval_output/support_sweep/v${V}"
done
```

The GR00T policy server must be running first (`run_gr00t_server.sh`, port 5557) — the sweep is an **evaluation**, so it goes through the server as usual. Only the Phase 0 frame measurement and the Phase 2 activation probes bypass it, for the reasons in §9.6.

Notes drawn from the code:

- Going through `--env_graph_spec_yaml` means the **relation solver runs**, so the object's pose is derived from the support relation rather than hardcoded. That is the point: it exercises the same path a generated environment uses.
- Under the graph-spec path the example-environment subparsers are **not** registered (`isaaclab_arena_environments/cli.py:161-166`), so `--embodiment` is not available. The embodiment comes from the spec's `embodiment.registry_name`, which the v9 spec already sets to `g1_wbc_agile_joint`. Verify each variant keeps it.

- **The 50-D embodiment is mandatory however it is selected.** `g1_wbc_agile_pink` is the 23-D Pink IK backend and raises `ValueError: Invalid action shape, expected: 23, received: 50` against the GN1x checkpoint. It is the *default* in the reference factory (`galileo_g1_static_pick_and_place_environment.py:155`), so the fallback route of §2.6 needs `--embodiment g1_wbc_agile_joint` explicitly; the graph-spec route inherits it from the spec instead.
- **Two properties of the reference factory have no graph equivalent yet**, and losing them would corrupt the measurement:
  - `env_cfg.num_rerenders_on_reset = 1` (`:290`) forces an RTX sensor refresh so the policy does not see the previous episode's final frame. A stale first frame silently poisons a vision-sensitive comparison.
  - `StaticShelfSupport` (`:196-218`) is an invisible collision patch compensating for the shelf mesh's perforated collision. Without it small objects fall through parts of the visible deck.
  Both must be carried into the generated variants — as an `env_cfg_callback` equivalent and a procedural support object respectively — or conditions A–C will not reproduce the reference behaviour. **This is a prerequisite of the relational route, not an optional extra**, and is the main implementation risk of Phase 1 (see §9.7).
- `episode_length_s=6.0` at `:302` (300 steps) sufficed for the documented 1.0 success. If condition A fails, raise it before concluding anything — `horizon_truncation` is a competing explanation.
- Both `--num_episodes` and `--num_steps` exist (`policy_runner_cli.py:77-88`); use `--num_episodes` so every condition gets the same episode count rather than the same step budget.

### 2.9 Analysis

New file `isaaclab_arena_examples/tools/summarize_height_sweep.py` — no simulator needed, reads only the JSONL:

```python
def summarize(sweep_root: Path) -> list[dict]:
    """Per-condition funnel: settled -> lifted -> placed, plus false-success count."""
    for cond_dir in sorted(sweep_root.iterdir()):
        records = [json.loads(l) for f in cond_dir.glob("**/episode_results_rank*.jsonl")
                   for l in f.read_text().splitlines() if l.strip()]
        lifted = sum(any("object_is_above_height" in e.get("predicate_name", "")
                         for e in r.get("progress", {}).get("events", [])) for r in records)
        placed = sum(bool(r.get("success")) for r in records)
        false_pos = sum(bool(r.get("success"))
                        and float(r.get("progress", {}).get("overall_score", 1.0)) <= 0.0
                        for r in records)
        ...
```

Reuse the funnel and false-success logic already validated in `eval_self_healing.py` rather than reimplementing it — the field names are confirmed correct (§Phase 0 of the strategy plan).

### 2.10 Acceptance criteria and what each outcome means

- **A high, B/C degrading** → height is the blocking axis. Fit the drop-off; the tolerance is the offset at which success crosses ~50% of the condition-A rate. Write it into the profile with provenance.
- **A/B/C all high, D low** → height is **not** the blocker. `vertical_reach_ood` is mis-ranked, and `REMEDIATION_TECHNIQUES` ordering needs revising toward the visual axis. This is a live outcome; the strategy plan commits to it in §10 in advance.
- **A low** → stop. The fault is the stack or the harness, not the distribution. Re-verify against the documented `success_rate: 1.0` baseline before drawing any conclusion.
- Any condition reporting `false_success > 0` invalidates that condition's numbers — Pathway C should prevent this, and its appearance here would mean the gate is not active on this path.

---

## 3. Phase 2 — Probe the Real Checkpoint

### 3.1 Loading path found in review

`submodules/Isaac-GR00T/gr00t/policy/gr00t_policy.py`:

- `Gr00tPolicy(embodiment_tag, model_path, device=...)` (`:83`) loads via `AutoModel.from_pretrained` (`:109`), sets `self.model` (`:112`), and moves to **`torch.bfloat16`**.
- `Gr00tPolicy._get_action` (`:380`) calls `self.model.get_action(**collated_inputs)` (`:417`) after applying processor transforms.

So `Gr00tActivationProbe`'s existing resolution chain (`"action_head"`, `"model.action_head"`, `"policy.model.action_head"`) already finds the head when handed a `Gr00tPolicy`. **Probe at the `Gr00tPolicy` level**, not the raw `Gr00tN1d7`, so the image transforms run normally — a scrambled *raw* frame that then flows through the real preprocessing is the ablation we want; scrambling post-transform tensors would test something else.

### 3.2 Known adaptation needed

`_predict_chunk` (`policy_activation_probe.py`) expects a torch tensor and calls `.float()`. `Gr00tPolicy.get_action` returns **un-transformed actions, likely numpy**. Required change:

```python
    chunk = getattr(output, "action_pred", None)
    if chunk is None and isinstance(output, dict):
        chunk = output.get("action_pred") or output.get("action")
    assert chunk is not None, "Model output carries no 'action_pred'; cannot measure chunk dynamics."
    if not torch.is_tensor(chunk):
        chunk = torch.as_tensor(np.asarray(chunk))   # Gr00tPolicy returns numpy
    return chunk.float()
```

Also verify on first contact:

- `action_head.config.attend_text_every_n_blocks` is present on the loaded config — the probe reads it rather than assuming, and falls back to `2`.
- The backbone hook's output exposes `backbone_features` and `image_mask` with matching leading dims; otherwise the probe pools over all tokens and emits a note (by design, but the note must be read).
- bfloat16 does not degrade the norm ratios — the probe upcasts with `.float()` before every norm, so this should hold, but confirm the block deltas are not all identical (which would indicate saturation).

### 3.3 The probe script

New file `isaaclab_arena_examples/tools/probe_policy_activations.py`:

1. Load `Gr00tPolicy` from `--model_path` and `--embodiment_tag` (the v9 policy config uses `NEW_EMBODIMENT`).
2. Load one recorded observation. Cheapest source: a frame already on disk under `eval_output/g1_tabletop_apple_to_plate/v9_frames/` plus the state vector — or re-run one short rollout with a hook that pickles the first observation dict.
3. Call `probe_policy_inference(policy, obs, corpus_instruction="move the apple to the plate", corpus_image_centroid=...)`.
4. Print `report.to_dict()` and write the `ProbeObservation` list as JSON for the belief state.

Run against a **galileo** observation and a **maple_table** observation. The contrast is the measurement; a single absolute number is close to meaningless because the thresholds (`IMAGE_CONDITIONING_COLLAPSE_RATIO = 0.15` etc.) are themselves unvalidated defaults.

### 3.4 Corpus centroid

New file `isaaclab_arena_examples/tools/measure_corpus_centroid.py`: iterate the 200 demo episodes, run the backbone forward with the probe's hook registered, mean-pool image-masked tokens, and save a `.pt`. Dataset path per `session_memory.md` §3 is `/datasets/isaaclab_arena/static_apple_tutorial/...`, mounted via `./docker/run_docker.sh -d`.

`vl_embedding_ood_distance` is registered but inert until this exists.

### 3.5 Acceptance criteria

- Probe runs against the real checkpoint without hitting the `AssertionError` in `_resolve_action_head`.
- `report.block_conditioning_deltas` has one entry per DiT block with `call_count == num_denoising_steps` (4 by default) per inference call.
- `sampling_noise_floor > 0` — if it is zero, seeding is over-constraining and every ablation ratio is meaningless.
- The galileo-vs-maple contrast on `vision_ablation_ratio` and `cosine_distance_to_corpus_centroid` is reported with both absolute values, so the thresholds can be recalibrated from data rather than trusted.

---

## 4. Phase 3 — Fine-Tune Scope

Gated on Phases 1 and 2. Recorded here so the decision rule is fixed in advance rather than after seeing results.

| Phase 1 + 2 outcome | Scope |
| :--- | :--- |
| Height blocking; centroid distance small | Height-varied data, `tune_visual=False` (default) |
| Height blocking; centroid distance large | Height-varied data **and** `tune_visual=True` — accept the generalization cost |
| Height not blocking; centroid large | Visual only: augmentation via `color_jitter_params` / `random_rotation_angle`, escalate to `tune_visual=True` |
| Height not blocking; centroid small | Neither hypothesis holds. Re-open diagnosis; the probes' causal ablation is then the primary evidence |

Config surface is `submodules/Isaac-GR00T/gr00t/configs/finetune_config.py` — `tune_llm=False`, `tune_visual=False`, `tune_projector=True`, `tune_diffusion_model=True`, `state_dropout_prob=0.2`, plus the augmentation knobs at `:68-83`. Entry point is `examples/finetune.sh` per the submodule's `CLAUDE.md`.

**Data generation, if height-varied demos are needed.** The existing `G1PickAndPlaceMimicEnvCfg` (`pick_and_place_task.py:391`) is locomanip-only: it raises on anything but `ArmMode.DUAL_ARM` and sets `use_navigation_controller = True`. A static variant would be a new `@configclass` with the three-subtask-per-arm shape and no nav phases. Falsify Mimic yield with one 100-trial run at a single non-default height before writing it.

**Post-fine-tune bookkeeping**: add a second entry to `POLICY_PROFILES` rather than editing the existing one — the old profile must stay queryable so `lineage.ttl` derivations continue to resolve.

---

## 5. Phase 4 — Wire the Planner In

### 5.1 Pre-flight gate

`environment_generation_runner.py`. `build_env_from_env_graph_spec` is at `:461`; `main()` dispatches at `:548`. Insert before the simulator launches:

```python
def _check_transfer_readiness(spec_path: Path, args_cli) -> None:
    """Warn when the spec violates the target policy's training invariants."""
    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import diagnose_transfer_readiness
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    policy_ref = getattr(args_cli, "policy_ref", None)
    if not policy_ref:
        return
    report = diagnose_transfer_readiness(ArenaEnvGraphSpec.from_yaml(spec_path), policy_ref)
    if not report["profile_known"]:
        print(f"[preflight] {report['message']}", flush=True)
        return
    if report["transfer_expected"]:
        print("[preflight] scene is within every declared training invariant.", flush=True)
        return
    print(f"[preflight] ⚠ scene violates {report['out_of_tolerance_axes']} "
          f"(worst {report['worst_shift_sigma']}x tolerance); "
          f"dominant mode {report['dominant_failure_mode']}", flush=True)
```

Warn, never block: the check is only as good as its tolerances, and Phase 0 exists because those were wrong once already.

### 5.2 A `--policy_ref` flag is genuinely required

Review found that `generated_envs/g1_tabletop_apple_to_plate/v9/policy_config.yaml` **contains no checkpoint identifier** — only `modality_config_path`, `embodiment_tag`, `action_chunk_length`, `pov_cam_name_sim`, and joint-config paths. The checkpoint lives in the GR00T server's `--model-path`, outside the graph.

So the graph cannot currently tell which policy an environment is being evaluated against. Fix both ends:

1. Add `checkpoint_uri: nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace` to the policy config YAMLs — its natural home, and it makes existing configs self-describing.
2. Add `--policy_ref` to `add_agentic_env_gen_runner_cli_args` (`:51`), defaulting to the policy config's `checkpoint_uri` when present.

Without this the pre-flight gate and `build_policy_diagnostic_state` are both inert, because `get_policy_profile(None)` returns `None`.

### 5.3 Planner-driven healing

Same file, `run_auto_heal`. `oracle.diagnose_eval_run` returns at `:336`; the report prints at `:338-348`. Insert between:

```python
    state, plan = build_policy_diagnostic_state(
        spec=spec,
        policy_ref=policy_ref,
        signatures=signatures,
        probe_report=None,          # populated when Phase 2 runs in-process
    )
    print(f" 🎯 Dominant failure mode: {plan['dominant_failure_mode']} "
          f"(belief {plan['dominant_belief']})", flush=True)
    print(f" 🔬 Next diagnostic: {plan['next_diagnostic']}", flush=True)
    print(f" 🔧 Recommended remediation: {plan['recommended_remediation']}", flush=True)
```

And extend the Neo4j block at `:386-397`, which already swallows exceptions with a bare `except Exception: pass`:

```python
        from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import (
            emit_policy_diagnostics_ttl, sync_policy_diagnostics_to_neo4j,
        )
        profile = get_policy_profile(policy_ref)
        if profile is not None:
            emit_policy_diagnostics_ttl(
                out_path=str(new_v_dir / "policy_diagnostics.ttl"),
                env_name=spec.env_name, profile=profile, state=state,
                eval_run_id=f"{spec.env_name}_v{new_v}",
                next_technique_id=plan["next_diagnostic"],
                remediation_id=plan["recommended_remediation"],
            )
            sync_policy_diagnostics_to_neo4j(...)
```

> [!WARNING]
> Sequencing: do **not** let the planner select remediations until Phase 0 and Phase 1 have replaced the assumed tolerances. Until then it will rank confidently on invented numbers. Landing 5.1 and 5.2 early is fine — both are reporting-only.

### 5.4 A related defect worth fixing here

`run_auto_heal` locates the eval directory by most-recent mtime (`:303-307`) when no versioned dir exists. Combined with the 0-byte-JSONL case found in the strategy plan's Phase 0, the oracle can silently diagnose a run that recorded no episodes. Add a guard: if the resolved eval dir yields zero parsed episode records, fail loudly rather than falling through to `object_moved_rate`.

---

## 5b. Phase 5 — Visual-Axis Diagnosis (DRAFT v1, superseded below by §5c)

> [!NOTE]
> Retained deliberately so the effect of the literature review in §5c is auditable. **Do not
> implement from this section** — implement §5c.

Phase 0's frame measurement moved the visual domain to the front: height and laterality measure
in-tolerance, `vision_domain_ood` is the dominant belief, and `visual_domain_randomization_finetune`
is what the planner selects. Two experiments follow, both cheap.

### 5b.1 Corpus image-token centroid

Mean-pool the backbone's image-masked tokens over the 251 corpus episodes, save a `.pt`, then
report cosine distance from a `maple_table` observation's pooled embedding to that centroid. This
activates `vl_embedding_ood_distance`, which is registered but inert. Decision rule: a small
distance means the frozen encoder represents both scenes similarly, so the projector and DiT have
tractable material and default fine-tune flags suffice; a large distance means `tune_visual=True`
is required.

### 5b.2 The stale-frame defect

The generated maple env sets `num_rerenders_on_reset = 0`; the reference factory sets `1`
(`galileo_g1_static_pick_and_place_environment.py:290`) precisely so the policy does not condition
on the previous episode's final rendered frame. Set it to 1 in the generated env and re-run; if
success changes, this was a harness bug masquerading as a domain-shift failure.

### 5b.3 Acceptance

- Centroid distance reported with both absolute values and the galileo-vs-maple contrast.
- Rerender fix either changes the metric or is ruled out.

---

## 5c. Phase 5 — Visual-Axis Diagnosis (AUTHORITATIVE, literature-reviewed 2026-09-03)

### 5c.0 What the review changed, and why it matters

Four findings, each of which alters the draft in §5b. The first would have produced a **wrong answer**.

| # | Draft assumed | Literature says | Consequence |
| :-- | :--- | :--- | :--- |
| 1 | `num_rerenders_on_reset = 1` fixes stale frames | It reportedly **does not** — [IsaacLab #6394](https://github.com/isaac-sim/IsaacLab/issues/6394) measures ~4.96 with 2 rerenders vs ~4.98 with 0. Root cause is a render/physics ordering problem: with fabric enabled, poses written via the PhysX tensor API only reach the renderer during a *physics step*, and `reset()` never steps physics. | §5b.2's test would have flipped an ineffective flag, seen no change, and **wrongly exonerated stale frames**. Must be replaced by an assertion on pixels. |
| 2 | Cosine distance to a corpus centroid is the OOD score | Expected ranking is kNN (cosine, L2-normalised) ≳ Mahalanobis > cosine-to-centroid > Euclidean-to-centroid; cosine-to-centroid *is* Mahalanobis with an identity covariance and the norm discarded. [Sun et al. 2022](https://arxiv.org/abs/2204.06507) report kNN FPR95 29.15% vs Mahalanobis 37.94%. | Upgrade the score. Mahalanobis is nearly free (one pass, no index). Mitigating nuance: in *transformer* embedding spaces angular and Mahalanobis scores nearly coincide ([OODformer](https://arxiv.org/pdf/2107.08976) finds ±2%), so the draft was suboptimal rather than invalid. |
| 3 | ~20 episodes per condition | 20 trials cannot separate policies differing by <20–30 points. [Robot Learning as an Empirical Science](https://arxiv.org/html/2409.09491) is explicit: 13/20 vs 14/20 supports no claim. | **Underpowered.** See the computed table in §5c.3; this is simulation, so 100+/arm is affordable and 20 is indefensible. |
| 4 | `tune_visual=False` (GR00T default) is the baseline path | Freezing the encoder under a domain gap is the *disfavoured* setting. [Diffusion Policy](https://arxiv.org/pdf/2303.04137) ablations: ViT-CLIP 0.70 frozen → 0.98 fine-tuned; ResNet18 0.58 → 0.92. [OpenVLA](https://arxiv.org/pdf/2406.09246) fine-tuned its SigLIP-DINOv2 backbone after finding frozen encoders produced "unstable, clearly suboptimal" behaviour. | §4's decision table is too conservative. Becomes a **three-arm comparison**, plus a non-training fourth option (§5c.4). |

Two counterweights kept the recommendation from flipping entirely: GR00T N1.5+ freezes the VLM *deliberately* to preserve language grounding, and a driving result found a fine-tuned 14B VLM **worse** than frozen through over-specialisation. So this is a measurement, not a foregone conclusion — which is why §5c.4 is a comparison rather than a switch.

---

### 5c.1 Stale-observation test — assertion, not flag-flipping

**Hypothesis.** The policy's first observation each episode is the *previous* episode's final rendered frame, so a vision-conditioned policy conditions on a scene that no longer exists. This is a harness defect that would masquerade as domain shift, and it is present exactly where our generated env sits: `use_fabric=True` with `num_rerenders_on_reset=0`.

**Why the draft's test was invalid.** Setting the flag to 1 is the documented remedy and is reported not to work, because re-rendering still happens before PhysX has published the new transforms. A no-change result would have been read as "stale frames are not the problem" when it in fact means "the flag does not fix stale frames".

**Protocol.** Measure the defect directly in pixel space; do not infer it from a success rate.

```
For each of K = 10 consecutive episodes:
  1. obs_reset  = env.reset()                      # candidate stale frame
  2. obs_step1  = env.step(hold_action)            # first genuinely post-reset render
  3. record  d_self  = mean |obs_reset - obs_step1|      (should be ~0 if fresh)
  4. record  d_prev  = mean |obs_reset - obs_final_{k-1}| (should be LARGE if fresh)
Report both distributions. Stale frames are confirmed iff d_prev << d_self.
```

Run the matrix `{num_rerenders_on_reset ∈ {0, 1, 2}} x {rerender_on_reset ∈ {False, True}}`, and additionally a variant that forces a physics step before the first sensor read. The last is the remedy the root-cause analysis implies; the flags are the remedies the docs claim.

**Interpretation.** If `d_prev << d_self` in the default config, every vision-derived measurement in this project's history — including the depth audits and the VLM autopsies — was taken on a frame the policy would not actually have seen at that moment. That does not invalidate the *scene* geometry findings, but it does invalidate any claim about what the policy saw on step 0.

**Cost.** One short rollout per config; ~15 minutes total. **Do this before any fine-tuning decision**, because it is the cheapest hypothesis on the table and it can invalidate the others' evidence base.

---

### 5c.2 Representation-space OOD score — Mahalanobis and kNN, not cosine-to-centroid

**Unit of analysis.** One score per *observation*, from the mean over image-masked backbone tokens for that frame. Token-level scoring (one score per patch) is a refinement that answers a different question — "which patches are unfamiliar" — and is deferred.

**Bank construction.** Over the 251 corpus episodes, at a fixed frame stride, collect pooled image-token embeddings `Z ∈ R^{N x D}` with `D = backbone_embedding_dim = 2048`. The dataset holds `total_frames = 35066` (measured 2026-09-04), so at stride 5 `N ≈ 7000`, giving `N > 3D` — comfortably better than the `N ≈ 4000` this section originally assumed, though still close enough to `D` that **Ledoit–Wolf shrinkage** remains the right choice over the raw empirical covariance.

**Three scores, reported together.**

| Score | Definition | Why included |
| :--- | :--- | :--- |
| `cosine_to_centroid` | `1 - cos(z, mean(Z))` | Continuity with the already-registered metric; cheap |
| `mahalanobis` | `sqrt((z-mu)^T S^-1 (z-mu))`, `S` = Ledoit–Wolf | Uses covariance; near-free; the literature's default first choice |
| `knn_cosine` | cosine distance to the k-th nearest L2-normalised row of `Z`, `k=3` | Strongest of the three; no distributional assumption |

**Calibration is mandatory and is the part most easily skipped.** A raw distance is uninterpretable. Hold out 20% of corpus frames as in-distribution positives, then report each score as a **percentile against that held-out ID distribution**, plus AUROC for separating held-out-corpus from maple frames. A maple frame at the 99.9th ID percentile is meaningful; "cosine distance 0.37" is not.

This also retires an unvalidated constant: `VL_EMBEDDING_OOD_DISTANCE = 0.35` in `policy_activation_probe.py` was chosen a priori. Replace the threshold with the measured ID 95th percentile.

**Negative-control requirement.** Also score a **galileo** frame the bank did not see. If it lands at a similar percentile to maple, the score is not measuring domain shift and the whole approach fails — which must be reported, not quietly dropped.

---

### 5c.3 Statistical protocol — computed, not asserted

Two-sided Fisher exact on the success counts, computed for this design:

| n / arm | 0.90 vs 0.50 | 0.90 vs 0.70 | 0.90 vs 0.80 | 0.70 vs 0.50 |
| ---: | :--- | :--- | :--- | :--- |
| 20 | p=0.014 ✓ | p=0.235 ✗ | p=0.661 ✗ | p=0.333 ✗ |
| 50 | p<0.001 ✓ | p=0.023 ✓ | p=0.262 ✗ | p=0.066 ✗ |
| **100** | p<0.001 ✓ | p<0.001 ✓ | p=0.073 ✗ | p=0.006 ✓ |
| 200 | p<0.001 ✓ | p<0.001 ✓ | p=0.007 ✓ | p<0.001 ✓ |

Clopper–Pearson 95% interval at an observed 90%: n=20 → ±15.2 pts; n=50 → ±9.2; n=100 → ±6.4; n=200 → ±4.4; n=1000 → ±1.9.

**Decisions.**

- **n = 100 per arm** is the floor for any comparison this project reports. It resolves a 20-point difference and is affordable in simulation. The earlier "~20 episodes" figure is retired.
- Report **Clopper–Pearson** intervals alongside every success rate.
- Use **direct hypothesis tests**, not interval overlap. Toyota Research Institute's guidance notes the common error explicitly: two intervals can overlap substantially while still being statistically separated. Apply Holm–Bonferroni across the arms of a sweep.
- **A near-fatal design flaw already present**: the reference environment sets `APPLE_SPAWN_XY_RANGE_M = 0.0` (`galileo_g1_static_pick_and_place_environment.py:67`), so every episode has *identical* initial conditions. Under zero randomisation, n episodes of a deterministic-except-for-noise policy give far fewer than n independent samples, and the binomial interval is optimistic. Increasing n does nothing about bias from a narrow initial-condition distribution. **Any powered comparison must first restore spawn randomisation** (the constant's own comment says the jitter exists so a finetuned policy can generalise over the spawn range) and vary the seed per episode.

---

### 5c.4 Phase 3 revision — a four-arm comparison, replacing §4's table

The literature does not support picking `tune_visual` a priori. It supports measuring, with these arms:

| Arm | Configuration | Literature basis | Cost |
| :--- | :--- | :--- | :--- |
| **A. Frozen + augmentation** | GR00T defaults: `tune_visual=False`, `tune_projector=True`, plus `color_jitter_params` / `random_rotation_angle` | The disfavoured setting under a domain gap — but note `tune_projector=True` already supplies the "small tunable module on a frozen backbone" that a generalist-tuning study found "improved considerably over head-only tuning" | Low |
| **B. Encoder fine-tune at reduced LR** | `tune_visual=True`, vision LR 10x below the policy net | Diffusion Policy's best configuration; OpenVLA's deliberate choice | Medium |
| **C. Adapter / LoRA on the vision tower** | Low-rank adaptation, backbone otherwise frozen | Preserves pretrained breadth while recovering plasticity; the answer to the over-specialisation counterexample | Medium |
| **D. Observation canonicalisation (no training)** | Transform maple observations toward the corpus appearance at inference | Narrows the *test* distribution instead of widening the training one; viable precisely because our target scene is fixed | Low |

**Arm D deserves emphasis** because it is the only arm requiring no GPU training and it fits this project's constraint exactly: the target scene is fixed and known, so a fixed appearance transform is admissible where a general solution would not be. It should be added to `REMEDIATION_TECHNIQUES` as `canonicalize_observation_domain` (effort `config`, `preserves_target_scene=True`).

**Domain-randomisation caveats to encode**, all from the review:

- Randomise only what plausibly varies in deployment; heavy lighting randomisation under fixed lighting wastes capacity. Start narrow, widen progressively while monitoring.
- DR has been observed to induce more redundant and entangled representations — a representation-quality cost, not a free lunch.
- Regularisation penalising internal feature divergence under randomisation outperforms naive DR, so `visual_domain_randomization_finetune`'s efficacy of 0.75 should be treated as an upper bound for the naive form.

---

### 5c.5 Implementation checklist

| # | Change | File |
| :-- | :--- | :--- |
| 1 | New failure mode `harness_stale_observation` (layer `harness`), with `success_progress_consistency_check` and a new `stale_frame_assertion` diagnostic discriminating it | `policy_capability_graph.py` |
| 2 | New remediation `force_physics_step_before_sensor_read` (effort `harness`, efficacy high) and `canonicalize_observation_domain` (effort `config`) | `policy_capability_graph.py` |
| 3 | Replace `VL_EMBEDDING_OOD_DISTANCE` with a calibrated percentile; add `mahalanobis` and `knn_cosine` to the probe's reported stats | `policy_activation_probe.py` |
| 4 | `measure_corpus_embedding_bank.py` — build `Z`, Ledoit–Wolf covariance, L2-normalised kNN index, ID held-out calibration | new tool |
| 5 | `test_stale_observation.py` — the `d_prev << d_self` assertion across the flag matrix | new sim test |
| 6 | Restore `APPLE_SPAWN_XY_RANGE_M` > 0 and per-episode seed variation before any powered comparison | reference env / sweep harness |
| 7 | `summarize_support_sweep.py`: add Clopper–Pearson intervals, Fisher exact pairwise tests, Holm–Bonferroni correction | existing tool |

---

### 5c.6 Acceptance criteria and falsification

**Ordered gates.** Each must pass before the next is worth running.

1. **Stale-frame assertion completes** with `d_prev` and `d_self` distributions reported for every config. If stale frames are confirmed *and* fixable, re-run the v9 evaluation before anything else — prior visual evidence is suspect.
2. **OOD score is calibrated and discriminating**: held-out-corpus vs maple AUROC > 0.8, and the negative control (unseen galileo frame) scores near the ID distribution. If AUROC ≈ 0.5, the representation does not distinguish the scenes and the visual hypothesis is **refuted** — at which point neither the height nor the visual axis explains the failure and the diagnosis reopens.
3. **Powered comparison** at n ≥ 100/arm with restored spawn randomisation, Clopper–Pearson intervals, and corrected pairwise tests.
4. Only then, the four-arm training comparison.

**What would falsify this phase:**

- Fresh frames confirmed **and** OOD AUROC ≈ 0.5 → the visual axis is not the blocker either. With height already cleared, this would mean the dominant remaining candidates are the prompt-token axis and the lateral offset, both currently ranked low, and the belief priors in `FAILURE_MODES` need revisiting.
- Arm A matching or beating Arm B → the frozen-encoder counterexamples apply to this checkpoint, and `tune_visual=True` should not be pursued.
- The negative control scoring as OOD as maple → the bank or the pooling is wrong, not the scene.

---

## 5d. v9 Re-run with Fresh Frames (2026-09-04) — the fake success is gone, and a harness defect outranks the visual hypothesis

Re-ran the v9 evaluation after the stale-frame fix, with `num_rerenders_on_reset=1` confirmed in the
composed config. GN1x served locally from `/models/isaaclab_arena/static_apple_tutorial/gn1x_tuned_static_apple`.

| | original `v9_full` | fresh-frame re-run |
| :--- | :--- | :--- |
| episodes | 1 | 11 |
| reported `success_rate` | **1.0** | **0.0** |
| **false successes** | **1/1** | **0/11** |
| settled reached | — | 8/11 |
| lifted reached | 0 | **0/11** |
| shortest episode | 15 steps | 7 steps |

**1. Pathway C works in production.** The v9 result that started this whole investigation — `success_rate: 1.0`
from a 15-frame episode — does not reproduce. Zero false successes in 11 episodes, and the honest
number is 0.0. The sequential lift gate is doing exactly what it was built for.

**2. `unsettled_scene` is confirmed live, and it now outranks the visual hypothesis.** The runtime
settle gate reports the manipuland at **0.22–0.67 m/s** and **5.5–17.0 rad/s** at inference entry,
with the plate also unsettled, and only 8/11 episodes reach the settled predicate at all. This is
the scaled-plate instability already documented in `g1_tabletop_apple_to_plate_remediation_plan`
§5B (`scale: [0.5, 0.5, 0.5]` on a deck with no collision support), still present and unaddressed.

The consequence for gate ordering: **an unsettled scene means the policy never gets a fair trial**,
so no visual-domain measurement taken in this environment is interpretable yet. `unsettled_scene`
is a harness-layer defect, cheaper to fix than anything in the model, and it precedes gate 2.

**3. Lift rate is 0/11**, so the failure is at approach/grasp, not transport. And the 7-step episode
is almost certainly `object_dropped` firing — the manipuland leaving the surface — which is
consistent with the unstable physics rather than with anything the policy did.

### Revised gate order

1. ~~Stale reset frames~~ — **done**, fixed.
2. **`unsettled_scene`** — NEW gate, confirmed by measurement. Remediation `hold_action_settle_warmup`
   is already registered; the likely fix is the plate scale / a collision support patch on
   `maple_table_robolab`, mirroring `StaticShelfSupport`. This is another instance of risk §9.7.
3. Corpus embedding bank / visual OOD — only meaningful once the scene settles.
4. Powered comparison, then the four-arm training study.

### Environment note

`docker/run_gr00t_server.sh` currently fails: a stale `submodules/Isaac-GR00T/.venv` built with
CPython 3.10 (2026-08-27) makes `uv run` resolve a 3.10 environment, and the pinned flash-attn
wheel is cp312-only. Workaround used here, which changes nothing on the host:
`UV_PROJECT_ENVIRONMENT=/opt/gr00t-venv312 uv run --python 3.12 ...`.

Bypassing `uv` entirely does **not** work: the image's system 3.12 `transformers` rejects the
meta-device `from_pretrained` pattern GR00T relies on (`RuntimeError: You are using from_pretrained
with a meta device context manager`), which its own code comments in
`gr00t_n1d7.py:101-111` anticipate. The `uv`-pinned versions are load-bearing. **Fixing this
properly means removing the stale venv or pinning the interpreter in the script — a `docker/`
change, so it needs sign-off.**

---

## 5e. End-to-End Iteration (2026-09-04): settle fixed, two false-success bugs closed, one blocker left

Three iterations against the live GN1x server, each measured.

### Iteration 1 — v10: spawn clearance

**Diagnosis.** All `maple_table*` sectors in `FIXTURE_SECTOR_BOUNDS` declare deck `z = 0.0`, and the
table's USD origin sits at its deck, so the deck resolves to world `z ~= 0`. The placer computes
`z = surface_z + clearance_m - child_bbox.min_z` with `On.clearance_m` defaulting to **1 cm**
(`relations.py:195`). Objects therefore spawn 1 cm above the surface and free-fall onto it:
`sqrt(2 * 9.81 * 0.01) = 0.44 m/s`, against the 0.22-0.67 m/s the settle gate was reporting. A
sphere then *rolls*, which a 10-step settle window cannot damp.

**Fix.** `clearance_m: 0.001` on both `on` relations in a new v10 spec, plus `--settle_steps 60`.

**Result.** Velocities fell roughly 100x and all objects settle:

| | v9 | v10 |
| :--- | :--- | :--- |
| apple linear velocity at entry | 0.22-0.67 m/s | **0.0024-0.053 m/s** |
| apple angular velocity | 5.5-17.0 rad/s | **0.21-0.30 rad/s** |
| runtime settle gate | UNSETTLED | **SETTLED** |

### Iteration 2 — a second false-success mode, in Pathway C itself

v10 reported `success_rate = 0.033` (1/30) -- but the false-success detector flagged that single
success as spurious (`overall_score = 0.0`). **The lift gate had a hole**: `running_min` tracks the
lowest height reached, so an object that spawns above the surface, falls, and *rebounds* clears
`min + 5 cm` with no robot involvement.

Fixed by requiring the object to have rested before a lift can count. The first attempt still
failed, and the test said why: an object is placed with zero velocity, so it reads as at rest for
exactly the step before gravity acts, and a single at-rest sample latched immediately. The working
form requires **sustained** rest -- `rest_steps_required = 3` consecutive at-rest steps -- via a new
`EpisodeScopedState.run_length` primitive. `test_bouncing_object_does_not_count_as_lifted` pins both
artefacts.

### Iteration 3 — v11: verified

| | v9 | v10 | v11 |
| :--- | :--- | :--- | :--- |
| episodes | 11 | 30 | 71 |
| **false successes** | 1 | 1 | **0** |
| genuine lifts | 0 | 0 | **2** |
| settled (progress predicate) | 8/11 | 1/30 | 4/71 |

Two genuine lifts is the first non-zero lift count this project has recorded on `maple_table` with
the gate active. Note the runtime gate and the progress predicate disagree because they use
different thresholds -- gate 0.1 m/s / 1.0 rad/s, predicate 1e-2 / 5e-2 -- so the measured
0.21-0.30 rad/s passes one and fails the other. Worth reconciling.

### The remaining blocker

**Median episode length is 7 steps out of a 1000-step budget** (min 6, max 1000). The policy has no
time to act, so nothing downstream of this is measurable. Under investigation; the candidates are
the `object_dropped` termination (`root_height_below_minimum` against
`background_scene.object_min_z`) and a possible world-versus-env-relative frame mismatch in that
comparison, given the deck sits at world `z ~= 0` here.

### Workflow correction

Evaluations now run through a **persistent** container (`isaaclab_arena-latest`) via `docker exec`,
not a fresh `docker run --rm` per command. The unit-test suite went from minutes to **13 s**, since
the Omniverse asset cache is reused. Note that `docker/run_docker.sh` cannot be used from inside the
devcontainer: it mounts `-v ".:${WORKDIR}"` with a *relative* source, which under
docker-outside-of-docker resolves against the host filesystem rather than the devcontainer's cwd.
It is a host-side script.

---

## 6. Hygiene

| # | Action | Files | Notes |
| :-- | :--- | :--- | :--- |
| 1 | Run `pre-commit` on the **host** | all changed | **Blocks the commit.** Absent from both containers. |
| 2 | Delete the duplicate auditor | `isaaclab_arena_examples/tools/depth_spatial_auditor.py` | Byte-identical 466-line copy of the packaged module, imported by nothing |
| 3 | Guard empty eval runs | `policy_runner.py`, `eval_self_healing.py` | See §5.4; a 0-byte JSONL beside a written `eval_telemetry.ttl` reads as "no data" not "failed" |
| 4 | Unify the pelvis constant | `policy_capability_graph.py`, `spatial_geometric_oracle.py:423` | Both hardcode `0.75` independently |
| 5 | Add `rdflib`/`neo4j` to the sim image | `docker/` | **Ask first** per `AGENTS.md`. Until then `test_eval_self_healing.py`, `test_rdf_lowering.py`, `test_telemetry_to_prov.py` run in neither environment |
| 6 | Branch + PR | — | `AGENTS.md` wants `<username>/<type>/<short-description>` against `main`; recent history commits to `dev/0.3.0-prerelease` directly. Your call |

---

## 7. Test Additions

| Test | Kind | Asserts |
| :--- | :--- | :--- |
| `test_resolve_support_relation` | unit | Height-source precedence (`nominal_height` > sector deck > fixture bbox) matches `object_placer`; returns `None` rather than guessing when no `on` relation exists; works on a spec whose objects carry **no** explicit pose (the v9 case) |
| `test_generate_support_height_sweep` | unit | One variant per offset; variants differ *only* in the support relation; `auto` picks anchor re-selection when a deck is in range and fixture translation otherwise; realisation and offset are recorded on the reified relation |
| `test_kinematic_manifold_registry` | unit | Every `kinematic_manifold` string in `generated_envs/**/*.yaml` resolves to a registered `KinematicManifold`; corpora declare `coversManifold` |
| `test_support_relation_invariant_rdf` | unit | `SupportRelationInvariant` and `instantiatesManifold` round-trip through `spec_to_rdf_graph` / `lower_rdf_graph_to_spec` |
| `test_sweep_variant_preserves_support_and_rerender` | sim | Generated variants retain an equivalent of `StaticShelfSupport` and the reset re-render; objects settle at every swept offset |
| `test_summarize_support_sweep` | unit | Funnel arithmetic and false-success counting over synthetic JSONL |
| `test_measure_embodiment_frames` | sim | Body-name discovery finds pelvis/shoulder/wrist without hardcoding indices |
| `test_probe_accepts_numpy_action_output` | unit | `_predict_chunk` handles a numpy `action` (the `Gr00tPolicy` path) — extend the existing stand-in |
| Update `test_tabletop_scene_is_out_of_distribution...` | unit | Currently asserts `magnitude ≈ 0.833` from the **assumed** pelvis height; must be re-derived from the Phase 0 measurement |

---

## 8. Ordering and Effort

| Phase | Effort | Compute | Blocks |
| :--- | :--- | :--- | :--- |
| 0 — frame measurement | ~half a day | 2 short sim runs | Everything quantitative |
| 1a — relational invariant + resolver + manifold classes | ~1–2 days | none | 1c |
| 1b — port the factory's implicit guarantees (§9.7) | ~1–2 days | a few sim runs | 1c |
| 1c — support-relation sweep | ~half a day | ~100 episodes | Phase 3 scope |
| 2 — probes + centroid | ~1 day | 1 GPU load + 200-episode backbone pass | Phase 3 `tune_visual` decision |
| 5.1 + 5.2 — pre-flight, `--policy_ref` | ~half a day | none | Nothing; do in parallel |
| 3 — fine-tune | days–weeks | training | — |
| 5.3 — planner healing | ~half a day | none | Wait for Phase 0/1 tolerances |
| 6 — hygiene | ~half a day | none | Commit (item 1) |

Critical path: **0 → 1a → 1c → 3**, with 1b running alongside 1a. Everything else parallelises.

If the schedule cannot absorb 1a+1b before a decision is needed, run the §2.6 factory fallback to get the curve, then build the relational machinery afterward and re-measure. That ordering trades a throwaway experiment for an earlier answer — an acceptable trade, provided the fallback's result is recorded as provisional and the relational sweep is not quietly skipped once a number exists.

---

## 9. Risks

1. **Phase 0 invalidates the axis, not just the number.** If height must be shoulder-relative, `compute_distribution_shifts` needs a new axis and the profile needs re-authoring. Contained to `policy_capability_graph.py` plus its test.
2. **Support geometry breaks at higher decks.** The reference patch is `(0.8, 1.5, 0.04)` centred at `x=0.62`; at a higher deck the visible shelf geometry may intersect it, or the deck may have different extents. Mitigation: the settle gate from Pathway C catches this as `UNSETTLED` rather than silently producing bad data — which is a second reason Pathway C had to land first.
3. **A relation height without a surface under it measures gravity, not reach.** `nominal_height` overrides placement without creating support (§2.3). Mitigation: the generator must pair every offset with a realisation, and `auto` must refuse rather than emit an unsupported variant.
4. **Probe thresholds are unvalidated defaults.** `IMAGE_CONDITIONING_COLLAPSE_RATIO`, `ABLATION_INSENSITIVE_RATIO`, `VL_EMBEDDING_OOD_DISTANCE` were chosen a priori — the same mistake as the height tolerance. Mitigation: always report absolute values and the galileo-vs-maple contrast; treat the booleans as provisional.
5. **SM120 on the training path — RESOLVED 2026-09-03, no longer a risk.** Verified with `isaaclab_arena_examples/tools/verify_gr00t_training_kernels.py` in `gr00t-dev:latest`:

   | Check | Result |
   | :--- | :--- |
   | `sm_120` in `torch.cuda.get_arch_list()` | Yes — natively compiled, no PTX JIT needed |
   | flash-attn forward + backward | OK, grads finite (gates `tune_visual`/`tune_llm` only) |
   | SDPA backward at real DiT shapes (32 heads x head_dim 48, kv_dim 2048) | OK for self- and cross-attention; `flash=True mem_efficient=True` |
   | **Real `AlternateVLDiT` forward + backward** (550 M params) | OK — 232 grad tensors, all finite |

   Both the default and the escalated fine-tune configs are kernel-ready on this host.

   **Measured VRAM for a real action-head training step** (forward + backward + AdamW, 3 steps so the optimizer moments are allocated), on 102 GB total:

   | Batch | Peak allocated |
   | ---: | ---: |
   | 1 | 5.57 GB |
   | 8 | 5.59 GB |
   | 32 | 5.68 GB |
   | 64 | 7.84 GB |

   Cost is dominated by the 550 M parameters plus their AdamW moments, not by activations — 41 action tokens against 512 VL tokens is a small attention problem, which is why batch 1 and batch 32 cost nearly the same. Adding the frozen backbone contributes weights (~2 B params in bf16, roughly 4–5 GB) and image-side forward activations, but **no optimizer state**. Headroom is not the constraint at any plausible batch size; data loading and image activation memory will bind first.

   **Scope of this verification — what is *not* covered.** The check exercises a single module's forward+backward in isolation. It does **not** load the real 3 B checkpoint, run the HuggingFace trainer loop, exercise the data pipeline or checkpoint writing, or measure throughput. The definitive test remains a short real run: `examples/finetune.sh` for ~10 steps against a tiny dataset. Treat the result above as "the kernels and the memory envelope are fine", not "the fine-tune will run".

   **Prerequisite found in review — gated backbone repo.** `qwen3_backbone.py:34-44` carries a `_GATED_BACKBONE_HINT`: `nvidia/Cosmos-Reason2-2B` is a gated Hugging Face repo, and *every* GR00T checkpoint loads it — including a locally saved one, because `Gr00tN1d7.__init__` constructs the backbone via `from_pretrained(config.model_name)` before the checkpoint's state dict is applied. So training needs `HF_TOKEN` or `hf auth login` **inside the training container**. The devcontainer mounts `~/.cache/huggingface`, so the running policy server is presumably already authenticated; confirm the same credentials reach whichever container runs the fine-tune, or the run fails at model construction with a 401 rather than anything kernel-related.

   Things worth carrying forward:
   - **The trained path is SDPA; flash-attn is forward-only under the default config.** The DiT action head runs diffusers `Attention` under `_sdpa_context()` (`dit.py:47`). Flash-attn serves only the Qwen3 backbone (`qwen3_backbone.py:168-178`) and is **on by default** (`use_flash_attention: bool = True`, `gr00t_n1d7.py:49`) — so its *forward* is on the default path, but with `tune_llm=False`, `tune_visual=False`, and `tune_top_llm_layers=0` (all defaults) the backbone is fully frozen (`qwen3_backbone.py:254-257`) and nothing backpropagates through it. A flash-attn *backward* probe therefore tests only the escalated configs.
   - **Head dim does not affect SDPA backend dispatch here — measured, not assumed.** On sm120 / torch 2.7, head dims 32/48/64/72/128/256 all report flash, mem-efficient, and math as available, and all three execute. An earlier draft of this plan claimed head_dim 48 might dispatch differently from 64; that was wrong. What the real geometry does buy is memory realism and the correct masking pattern — the DiT's cross-attention is **not causal**, so a `causal=True` probe exercises the backbone's pattern, not the action head's.
   - **The frozen-backbone conclusion is one config line from flipping.** `tune_top_llm_layers` (`qwen3_backbone.py:259-262`) unfreezes the top N LLM layers *independently* of `tune_llm`, and the published N1.6 description mentions unfreezing the top 4 VLM layers during pretraining. It defaults to `0` (`gr00t_n1d7.py:43`), so nothing backpropagates through flash-attn today — but set it non-zero and flash-attn backward joins the critical path. Re-run the check if that value or `tune_visual` changes. Related: `select_layer: int = 12` (`:47`) truncates the language model to 12 layers (`qwen3_backbone.py:194-195`), so the backbone in use is smaller than the full Cosmos-Reason-2B.
   - **`dit.py:33` guards `(12, 1)` — Spark sm121 — only.** This host is `(12, 0)`, so the math-SDPA workaround is inactive and default dispatch applies. If DiT training later misbehaves, `GR00T_DIT_SDPA_MODE=math` (`dit.py:38`) is the documented escape hatch, no patch required.
   - **The `sm120dock` toolchain pins do not describe this image.** `gr00t-dev:latest` ships **torch 2.7.0a0+79aa17489c.nv25.04 / CUDA 12.9 / flash-attn 2.7.3**, not the "PyTorch cu128 + flash-attn 2.8.0.post2" that session recorded (the devcontainer has torch 2.10.0+cu128). Reconcile the note against the image before relying on either.
   - Minor gap: `gr00t-dev:latest` lacks `tyro`, so importing `gr00t.model.*` directly needs `pip install tyro`. It does not affect the server path.

6. **The policy server cannot validate training.** It runs inference under `no_grad`, so no backward pass executes. This is why §9.5's check is a separate tool rather than a server smoke test. The server remains the correct harness for Phase 1 evaluation, and only Phase 0 frame measurement and Phase 2 activation probes bypass it (probes need in-process weights; the server does not expose them).

7. **Porting the reference factory's implicit guarantees into generated variants is the main Phase 1 risk.** `StaticShelfSupport`, `num_rerenders_on_reset`, the deactivated clutter prims (`_BACKGROUND_PRIMS_TO_DEACTIVATE`), the per-asset `_USD_ORIGIN_ABOVE_BOTTOM_M` offsets, and `_TUNED_SCALES` are all Python-side knowledge that the graph does not currently represent. Conditions A–C only reproduce the reference behaviour if the equivalents exist in the generated variants. Two consequences worth stating plainly:
   - This is the real cost of doing Phase 1 relationally rather than ad-hoc, and it is worth paying, because each item is per-fixture data that *belongs* in the graph — but it is more work than a float on a dataclass.
   - It is also a **finding in its own right**: these five items are exactly the kind of scene knowledge the generation pipeline cannot currently express, which is why generated environments diverge from hand-tuned ones. Consider capturing them as fixture-level graph attributes independently of this plan.

---

## 10. References

- `.agents/references/plans/g1_policy_transfer_and_height_invariance_plan.md` — strategy, falsification criteria
- `.agents/references/plans/g1_tabletop_apple_remediation_plan.md` — the C1 autopsy, Pathway C
- `.agents/memory/sessions/20260903_190000_transferplan.md`, `20260903_180000_modelgraph.md`
- `isaaclab_arena_environments/galileo_g1_static_pick_and_place_environment.py` — the parameterisation target
- `isaaclab_arena_environments/cli.py:148-176` — why a cfg field becomes a CLI flag for free

---

## 11. Implementation Status (2026-09-03)

Against the §5c.5 checklist.

| # | Item | Status | Notes |
| :-- | :--- | :--- | :--- |
| 1 | `harness_stale_observation` failure mode + `stale_frame_assertion` diagnostic | **Done** | Registry integrity tests cover it |
| 2 | `force_physics_step_before_sensor_read`, `canonicalize_observation_domain` remediations | **Done** | The planner now selects canonicalisation over retraining for a visual-domain dominant belief, on cost-normalised score |
| 3 | Calibrated OOD scores in the probe | **Done** | `VL_EMBEDDING_OOD_DISTANCE = 0.35` replaced by `VL_EMBEDDING_OOD_PERCENTILE = 95.0`; without a bank the probe now emits a `likelihood_ratio=1.0` observation that explicitly moves no belief |
| 4 | `corpus_embedding_bank.py` | **Done** | Four scores, Ledoit-Wolf shrinkage, held-out percentile calibration, AUROC. 12 tests |
| 5 | `test_stale_observation.py` | **Done, and it found the defect** | See §11.1. Passes as a regression guard |
| 6 | Spawn randomisation | **Done, as opt-in** | `pick_up_object_spawn_xy_range_m` cfg field rather than changing the module default, so existing baselines are untouched |
| 7 | Clopper-Pearson / Fisher / Holm-Bonferroni | **Done** | 11 tests, pinned against the plan's power table |

### A finding from implementing item 4

Building the bank surfaced a limitation of the score the plan had upgraded *to*. **Both cosine scores are blind to a purely radial shift**: scaling every embedding outward along the mean direction leaves the angle unchanged, so `cosine_to_centroid` and the L2-normalised `knn_cosine` both score it at chance (AUROC < 0.7 measured), while Mahalanobis and a Euclidean kNN both catch it (AUROC > 0.9).

This is the concrete form of the "norm removal" weakness the literature named, and it is not hypothetical: an appearance change that alters embedding magnitude rather than direction would be invisible to the score §5c.2 originally specified. Consequences, both implemented:

- A fourth score, `knn_euclidean`, without normalisation.
- `is_ood` takes the **maximum** over the calibrated percentiles rather than trusting one, so a shift visible to any score is reported.
- `test_cosine_scores_are_blind_to_a_purely_radial_shift` pins the limitation so nobody later relies on the cosine scores alone.

### 11.1 GATE 1 RESULT: stale reset frames are real, and the flag *does* fix them

Measured on the light kitchen scene, three episodes per configuration, `d_prev` = distance from the
previous episode's final frame, `d_self` = distance from the frame after one post-reset step:

| Config | Verdict | `d_prev` (ep 1, 2) | `d_self` (ep 1, 2) |
| :--- | :--- | :--- | :--- |
| rerenders=0, fabric on — **Isaac Lab default** | **2/2 STALE** | **0.0, 0.0** | 6.0, 12.0 |
| rerenders=1, fabric on | 0/2 fresh | 5.95, 12.17 | 1.74, 2.58 |
| rerenders=2, fabric on | 0/2 fresh | 6.82, 13.13 | 1.74, 2.22 |
| rerenders=1, fabric **off** | 2/2 stale | 0.52, 0.40 | 0.58, 0.41 |

**The defect is confirmed.** Under the default, `d_prev = 0.0` *exactly* — the observation returned
by `reset()` is bit-identical to the previous episode's final frame, while differing from the
post-step frame by 6–12 intensity levels. A vision-conditioned policy conditions its first action
chunk of every episode on a scene that no longer exists.

**Correction to §5c.0 item 1.** That section asserted, on the strength of
[IsaacLab #6394](https://github.com/isaac-sim/IsaacLab/issues/6394), that `num_rerenders_on_reset`
does *not* fix this. On this Isaac Lab version and scene **it does**: one re-render inverts the
relation cleanly. The issue report may be version- or reset-event-specific. The methodological point
in §5c.0 still stands — the defect had to be measured in pixels rather than inferred from a success
rate, and that is exactly how both the defect *and* the working remedy were established. But the
specific claim "the flag does not work" was wrong, and taking it on trust would have led to
patching the simulator instead of setting a flag.

**Anomaly worth noting**: with `disable_fabric=True` every distance collapses below 1.0 and
`d_prev ≈ d_self`, i.e. the camera barely updates between any pair of frames. Disabling fabric
appears to suppress render updates rather than fix the ordering. Not pursued further; do not treat
it as a remedy.

**Fix applied.** `arena_env_graph_conversion_utils.build_arena_env_from_graph_spec` now installs an
`env_cfg_callback` that forces `num_rerenders_on_reset >= 1`. Generated environments previously had
no equivalent of the guarantee the hand-tuned reference environment sets at
`galileo_g1_static_pick_and_place_environment.py:290` — this was concrete evidence for risk §9.7,
and the maple v9 environment was running in exactly the confirmed-stale configuration.

**Consequence for prior findings**: any measurement this project took from a *first* frame of an
episode in a generated environment was taken on the previous episode's image. That does not affect
scene-geometry results, but it does affect claims about what the policy saw at step 0 — which
includes the depth audits and the VLM keyframe autopsies where those sampled step 0.

### Item 5 history (retained)

The test builds all four flag configurations in the simulator and reaches the per-episode comparison, but fails on an inference-tensor lifetime error rather than on its assertion. Two fixes have been applied (constructing the reset pose fresh instead of mutating `default_root_state`; materialising camera frames as ordinary CPU tensors) and a run is outstanding. **Until it is green, the stale-frame hypothesis is neither confirmed nor refuted** -- and since it is gate 1, nothing downstream should be treated as measured. The mechanism at `manager_based_env.py:425-431` and the flag's reported ineffectiveness are documented facts; whether this project's environments actually exhibit the defect is not yet established here.

### Not started

- `measure_corpus_embedding_bank.py`, the tool that runs the backbone over the corpus episodes to populate a bank. The bank machinery and its calibration are done and tested; only the extraction pass over real data is missing. **The gated-access blocker is stale as of 2026-09-04** -- `nvidia/Cosmos-Reason2-2B` is cached locally (8.4 GB, weights present); see §12.4. Note the corpus is **251** episodes, not 200.
- The four-arm training comparison (§5c.4).

---

## 12. Phase 5f — 2026-09-04: What Landed, and the Four Negative Results

### 12.1 The harness defect that outranked every model hypothesis — **FIXED**

Commit `83dc00658`. `verify_and_settle_scene` used `torch.zeros()` as its hold action. For
`G1DecoupledWBCJointAction` the layout is
`[joint_targets | navigate_cmd(3) | base_height(1) | torso_rpy(3)]` with **absolute** joint targets
and `base_height` default `0.75`
(`isaaclab_arena_g1/g1_env/mdp/actions/g1_decoupled_wbc_joint_action.py:87`), so zeros command a
floor squat plus all-joints-to-zero and discard `initial_joint_pos`.

```python
# isaaclab_arena/evaluation/policy_runner.py
def build_neutral_hold_action(base_env) -> torch.Tensor:
    """Zero is not neutral for every embodiment; hold the posture instead."""
    ...
    is_wbc = any("wbc" in type(t).__name__.lower()
                 for t in getattr(base_env.action_manager, "_terms", {}).values())
    if not is_wbc:
        return hold_action                      # delta spaces: zero *is* the hold
    hold_action[:, :num_joints] = default_joint_pos[:, :num_joints]
    hold_action[:, -num_base_height_cmd - num_torso_rpy_cmd] = 0.75
```

Two supporting fixes in the same commit: per-env `max` instead of `mean` on settle velocities (one
apple in free fall was masked by three still ones), and breaking on `terminated | truncated` so
auto-resets during settling stop being recorded as episodes.

| Metric | before | after |
| :--- | :--- | :--- |
| Median episode length | 7 steps | **1000** (full horizon) |
| Terminations / false successes | continuous / 1 | **0 / 0** |

**Generalise the class of bug, not the instance.** Any harness code that synthesises an action
without consulting the action term's semantics is suspect. Grep for `torch.zeros` used as a
command anywhere in `evaluation/` and `tests/`, and prefer `build_neutral_hold_action`.

### 12.2 Four single-variable experiments — all negative

Against the honest harness, 2 episodes × 1000 steps each:

| Run | Change | `object_moved_rate` |
| :--- | :--- | :--- |
| `v14` | baseline | 0.0 |
| `v15` | `bilateral_mirror: false` | 0.0 |
| `v16` | + `action_chunk_length: 40 → 16` | 0.0 |
| `v17` | + exact corpus prompt | 0.0 |

All three changes are corrections of real violations and are kept. `generated_envs/.../v15|v16|v17`
hold the specs. **Conclusion: the failure is not an inference-config detail**, which is what
authorises the more expensive work below.

### 12.3 The corpus, read rather than recalled

`/datasets/isaaclab_arena/static_apple_tutorial/nvidia/Arena-G1-Static-PickNPlace-Task/meta/`

```
tasks.jsonl   -> exactly 1 task, used by all 208 annotated episodes:
                 "Pick up the apple from the shelf and place it onto the plate
                  on the same shelf next to it."
info.json     -> total_episodes=251  total_frames=35066  fps=50  robot_type=unitree_g1
modality.json -> video: {ego_view}      (single camera)
                 state: left_leg[0:6] right_leg[6:12] waist[12:15]
                        left_arm[15:22] left_hand[22:29]
                        right_arm[29:36] right_hand[36:43]
                        (+ left/right_wrist_pose from observation.eef_pose)
```

Also present: `stats.json`, `relative_stats.json`, and an `observation.img_state_delta` feature.

**Every run `v8`–`v16` fed a prompt absent from this file.** The remediation plan asserted the
opposite. Action: `TrainingInvariant` reference values must be **derived from artefacts at load
time**, not transcribed — see §15.

### 12.4 Blocker cleared: the backbone is cached

`~/.cache/huggingface/hub/models--nvidia--Cosmos-Reason2-2B` — 8.4 GB, `model.safetensors` +
`config.json` present. §11's "Not started" entry for `measure_corpus_embedding_bank.py` and §3's
gated-access blocker are **both stale**; the activation probes and the embedding bank can run.

---

## 13. Phase 0.5 Implementation — Open-Loop Eval and Modality Ablation

This is now the **first** action in the plan. It is the official GR00T validation step and has
never been run in this project.

### 13.1 Open-loop fidelity

`submodules/Isaac-GR00T/gr00t/eval/open_loop_eval.py` exists in the pinned submodule. Flag names
drift between revisions (`--action-horizon` vs `--execution-horizon`) — read the checked-out file
before scripting it.

```bash
# Run in the GR00T env, not the Arena container. Interpreter pin per session `sm120dock`:
UV_PROJECT_ENVIRONMENT=/opt/gr00t-venv312 uv run --python 3.12 \
  python gr00t/eval/open_loop_eval.py \
    --dataset-path /datasets/isaaclab_arena/static_apple_tutorial/nvidia/Arena-G1-Static-PickNPlace-Task \
    --embodiment-tag NEW_EMBODIMENT \
    --model-path nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace \
    --traj-ids 0 1 2 \
    --save-plot-path eval_output/openloop/
```

Record per-dimension MSE, not just the aggregate: the 43-D action splits into
leg/waist/arm/hand groups, and a policy that is fine on legs and wrong on `left_arm[15:22]` is a
different diagnosis from uniform error.

**Also diff the normalisation metadata** — the single most-reported `NEW_EMBODIMENT` failure
([#408](https://github.com/NVIDIA/Isaac-GR00T/issues/408),
[#213](https://github.com/NVIDIA/Isaac-GR00T/issues/213)): confirm the checkpoint's
`experiment_cfg/metadata.json` carries a `new_embodiment` key whose per-dimension stats match
`meta/stats.json`. If inference silently falls back to pretrain stats, un-normalisation is wrong
and every downstream conclusion is void. Check specifically for padded dims where `min == max`.

### 13.2 Modality ablation — the test that actually discriminates

New tool: `isaaclab_arena_examples/tools/probe_policy_conditioning.py`, wrapping the existing
`measure_ablation_sensitivity` / `BlockConditioningDelta` in
`isaaclab_arena/agentic_environment_generation/policy_activation_probe.py`.

For a fixed corpus observation, emit the action chunk under:

| Arm | Image | State | Reads on |
| :--- | :--- | :--- | :--- |
| `baseline` | real | real | reference chunk |
| `vision_scrambled` | pixel-shuffled | real | is vision used at all |
| `vision_blank` | mid-grey | real | ditto, stronger |
| `vision_crossscene` | a `maple_table` frame | real | does the target frame move the chunk |
| `state_perturbed` | real | +noise | proprioceptive reliance |
| `state_zeroed` | real | zeros | ditto, stronger |

Report $\lVert \Delta \text{chunk} \rVert_2$ per arm, normalised by the baseline chunk norm, and
the per-joint-group breakdown.

> [!CAUTION]
> **Do not report a low open-loop MSE as "checkpoint is healthy".** Causally confused policies have
> low open-loop loss *by construction*
> ([de Haan et al.](https://proceedings.neurips.cc/paper_files/paper/9343-causal-confusion-in-imitation-learning.pdf)).
> §13.1 alone cannot clear the checkpoint; only §13.2 separates "learned the task" from "learned
> the proprioceptive shortcut". Both, or neither.

**Acceptance.** `vision_scrambled` and `vision_blank` deltas below ~10% of baseline norm ⇒ the
policy is state-driven, and §16 becomes mandatory. `vision_crossscene` producing a *large* delta
while the closed-loop reach stays fixed would be a contradiction worth chasing separately.

---

## 14. Observation-Framing Metrology (`measure_observation_framing.py`)

The 2.04× / 71× figures came from an ad-hoc script. Formalise it, because it is the metric
Intervention 1 optimises against and it must be reproducible.

`isaaclab_arena_examples/tools/measure_observation_framing.py`:

* Inputs: a corpus dataset path (reads `videos/chunk-*/observation.images.ego_view/*.mp4`) and
  either an eval run's camera mp4 or a live env.
* Per frame: mean/percentile brightness, per-channel histograms, and a **target-separability**
  score — red-dominant pixel count under $r>90 \wedge r>1.45g \wedge r>1.6b$, plus the largest
  connected component's bbox and its share of all red-dominant pixels.
* Output: JSON next to the run, plus a corpus-vs-target delta table.

> [!WARNING]
> The colour predicate is a **hand-tuned heuristic on one frame pair**, the same species of
> unmeasured constant that produced the height error. Before it is used to rank anything:
> compute it over ≥100 corpus frames and ≥100 target frames, report the distribution rather than a
> point value, and verify the corpus blob actually tracks the apple (its bbox should follow the
> hand during the grasp). If separability does not degrade across the corpus as the hand occludes
> the apple, the metric is measuring the background, not the target.

A defensible upgrade, if the heuristic proves fragile: score separability in the **backbone's**
embedding space using `corpus_embedding_bank.py` (Mahalanobis, already calibrated and tested)
rather than in RGB.

---

## 15. Invariant Provenance (the change that prevents a fourth wrong ranking)

Three of four ranked violations were wrong, and every one was **asserted in prose**. The ontology
records tolerances and reference values but not *where they came from*.

Add to `TrainingInvariant` in `policy_capability_graph.py`:

```python
    reference_source: str
    """Artefact the reference value was measured from, e.g.
    "meta/tasks.jsonl" or "measure_embodiment_frames.py:galileo_static.json"."""

    evidence_grade: Literal["measured", "derived", "asserted"]
    """`asserted` values are reported but MUST NOT contribute to ranking."""
```

* `compute_distribution_shifts()` filters `asserted` invariants out of the ranking and lists them
  separately as *unranked, unmeasured*.
* `diagnose_transfer_readiness()` refuses to name a dominant failure mode if any `asserted`
  invariant could outrank the winner had it been measured.
* Re-derive the two known-bad values: `prompt_alignment` from `meta/tasks.jsonl`, and
  `surface_height_rel_pelvis` from `measure_embodiment_frames.py` output.

This is the single highest-leverage ontology change available, because it converts a silent
failure into a loud one.

---

## 16. Appearance as a Nuisance Parameter (schema + remediation split)

### 16.1 The graph spec has no appearance block

`generated_envs/g1_tabletop_apple_to_plate/v17/g1_tabletop_apple_to_plate.yaml` has
`env_name / embodiment / background / objects / relations / reified_relations` and **no** control
over lighting or materials. Intervention 1 is therefore blocked on a schema addition:

```yaml
appearance:                     # optional; absent == today's defaults
  dome_light:
    intensity: 300.0
    color_temperature: 5200.0
  material_overrides:
    - target: background        # or an object id
      albedo_scale: 0.35
      roughness: 0.7
```

Realised through an `_env_cfg_callback` in
`isaaclab_arena/environment_spec/arena_env_graph_conversion_utils.py` — the same hook already used
to force `num_rerenders_on_reset >= 1`.

### 16.2 Split the over-coarse remediation predicate

`RemediationTechnique.preserves_target_scene` currently excludes photometric alignment along with
genuine benchmark rewrites. Replace with two predicates:

| | `preserves_scene_semantics` | `alters_nuisance_parameters` |
| :--- | :--- | :--- |
| `reanchor_surface_to_corpus_height` | **False** | False |
| `mirror_layout_to_corpus_laterality` | **False** | False |
| `align_scene_photometry` | **True** | True |
| `augment_corpus_and_refinetune` | **True** | False |

`select_remediation(preserve_scene_semantics=True)` then admits photometric alignment while still
excluding Pathway A's rewrites. Report `alters_nuisance_parameters` in the plan output so a lift
obtained by re-lighting is never silently presented as a pipeline capability.

---

## 17. Augmented Re-Finetune (the primary remediation)

No new demonstrations; all 251 corpus episodes are local. Targets the frozen-VLM shortcut directly.

| Arm | `--tune-visual` | State dropout | Photometric jitter | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| A (control) | off | off | off | reproduce the current checkpoint |
| B | off | **on** | off | is the shortcut the whole story |
| C | **on** | on | **on** | the recommended recipe |
| D (floor) | on | **inputs removed** | on | vision-only ablation — confirms the shortcut and sets the floor |

Arm D is the diagnostic: if it beats A, the proprioceptive shortcut is confirmed
([Adapt Your Body](https://www.researchgate.net/publication/393184798_Adapt_Your_Body_Mitigating_Proprioception_Shifts_in_Imitation_Learning)).

Kernel readiness is already verified on this host (§9.5): `sm_120` native, real `AlternateVLDiT`
forward+backward finite, 7.84 GB peak at batch 64. `--tune-visual` unfreezes the encoder and will
raise that materially — re-measure before committing to a long run rather than extrapolating from
the action-head-only figures.

**Honest expectation**: dropout-style mitigations land *between* full-state BC and vision-only BC in
the published comparisons. Budget for recovering a fraction of the gap, and state the fraction.

### Bookkeeping

After any successful arm, register a **new** `PolicyProfile` whose invariants describe the widened
distribution, with `evidence_grade="measured"` and `reference_source` pointing at the training
config. Transfer readiness against `maple_table` then becomes a re-measurement rather than a
re-argument — which was §7b's original intent and is only now enforceable.

---

## 18. Revised Risks (2026-09-04)

1. **The colour-separability metric is one hand-tuned predicate on one frame pair.** Mitigated by
   §14's distribution requirement and the embedding-space fallback. Until then it is a hypothesis
   with a number attached, not a measurement.
2. **Photometric alignment could "work" for the wrong reason.** Darkening the scene changes
   brightness, contrast, *and* effective SNR at once. If it produces a lift, ablate the knobs
   separately before claiming the colour-cue mechanism is confirmed.
3. **Nuisance-vs-semantics is a judgement call, and it is ours.** The split in §16.2 is defensible
   but it is not written into the C1 specification. Record it as an explicit decision in the
   benchmark's own output so a reader can disagree with it.
4. **Open-loop eval may pass and teach us nothing.** By construction for a causally confused
   policy. Budget for §13.2 as the real gate and treat §13.1 as a cheap precondition.
5. **`--tune-visual` on 251 episodes risks catastrophic forgetting of the pretrained features**,
   which is the failure mode the LoRA/adapter literature exists to avoid
   ([PriorVLA](https://arxiv.org/html/2605.10925) keeps a frozen prior expert). If arm C degrades
   below arm A on the *corpus* scene, switch to a parameter-efficient variant rather than tuning
   the learning rate.
6. **Four negative config experiments do not prove config is irrelevant** — they prove those four
   settings are not *sufficient*. Denoising steps, `action_horizon`, and the state/action
   convention (absolute joint targets vs. N1.7's relative-EEF pretrain spaces) remain untested and
   are cheap; fold them into §13.1 rather than a fifth closed-loop sweep.
7. **The 6.5 cm height result is a single measurement of a single pair of scenes.** It is enough to
   demote the height sweep, not enough to conclude height never matters. The demoted sweep still
   characterises the manifold and should run once the critical path clears.
