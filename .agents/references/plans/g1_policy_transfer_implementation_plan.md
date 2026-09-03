# Implementation Plan: G1 Policy Transfer Diagnosis (Code-Level)

> [!IMPORTANT]
> **Status**: ACTIVE — the code-level companion to `g1_policy_transfer_and_height_invariance_plan.md`, which holds the strategy and the falsification criteria. This document holds the diffs, commands, and acceptance criteria.
> **Two findings from reviewing the repository changed the implementation**:
> 1. The height sweep is **not** a YAML change. The corpus-aligned scene is a Python factory with a hardcoded shelf constant and an invisible collision patch (§2.1). The sweep becomes a ~20-line change to one file plus a shell loop — cheaper and far more controlled than authoring graph specs.
> 2. The `−0.8015 m` corpus invariant **may be frame-confused**, not merely un-toleranced (§1). If so, the height axis is mis-parameterised at its root, and the sweep must start by measuring frames rather than success rates.

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
