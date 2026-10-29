---
name: arena-digital-twin-grounding
description: Mandates physical Digital Twin grounding invariants (Z_base = 0.0m), generalized OpenUSD fixture affordance introspection, and prevents the 'procedural shortcut' anti-pattern across IsaacLab-Arena environment generation, oracles, and repairs.
---

# Arena Digital Twin Grounding Skill

This skill enforces physical Digital Twin grounding invariants across all IsaacLab-Arena environment generation, oracle validation, and self-healing repair workflows. It establishes strict rules to ensure simulation assets mirror real-world physics, mandates generalized OpenUSD affordance introspection for fixtures, and prevents the **"procedural shortcut"** anti-pattern that led to the Run 03 rollback.

---

## 1. The "Procedural Shortcut" Trap: Run 03 Retrospective

During autonomous environment generation and repair iterations (Run 02 and Run 03 in [`.agents/references/plans/local-inference/exp03_rollback_recovery_plan.md`](../../references/plans/local-inference/exp03_rollback_recovery_plan.md)), autonomous agents encountered a vertical height discrepancy:
- The Franka DROID robot base was mounted on its default pedestal at $Z = 0.75\text{ m}$.
- The selected table fixture (`office_table_background`, representing `table.usd` scaled by `[1.0, 1.0, 0.7]`) had an unshifted physical tabletop deck at $Z \approx 0.531\text{ m}$.

### The Anti-Pattern Shortcut
Rather than harmonizing the kinematics architecturally, an agent applied a **procedural shortcut**: it set the table's initial pose in the YAML specification to `z: 0.219m`.

```yaml
# ANTI-PATTERN: The Procedural Shortcut Trap
background:
  id: office_table
  registry_name: office_table_background
  params:
    initial_pose:
      position_xyz: [0.0, 0.0, 0.219]   # <-- VIOLATION: Floating in mid-air!
```

### Why This Caused the Rollback
1. **Decoupling from Reconciled Architecture**: Elevating the table lifted all four legs $21.9\text{ cm}$ off the floor. In a physical simulation, floor-standing furniture cannot hover in mid-air.
2. **Broken Contact & Support Mechanics**: When Step-0 PhysX simulation engaged or objects were placed via contact solvers, the unanchored floating fixture produced unpredictable settling dynamics, penetrating contact normal vectors, and catastrophic placement failures where objects spawned overlapping or unanchored.
3. **Knowledge Base Corruption**: The arbitrary coordinate offset bypasses the Neo4j Labeled Property Graph (LPG) and RDF-star ontology, poisoning downstream active inference cycles and prior receipts with ungrounded spatial assumptions.

> [!CAUTION]
> **Procedural Trap Warning**: Never apply isolated coordinate offsets in specs or oracles without architectural grounding in USD geometry and the Neo4j knowledge base. Every temporary or superficial shortcut that bypasses physical invariants inevitably produces catastrophic placement regressions.

---

## 2. Core Grounding Invariants

Every IsaacLab-Arena environment must strictly respect the following physical invariants:

### Invariant 1: Ground Contact ($Z_{\text{base}} = 0.0\text{ m}$)
Every floor-standing fixture (tables, workbenches, desks, kitchen counters, storage cabinets, appliances resting on the floor, and robot stand bases) **MUST** rest directly on the ground plane:
$$\left| Z_{\min}(\text{fixture}) - 0.0\text{ m} \right| \le 0.005\text{ m}$$

- **Floating fixtures** ($Z_{\min} > 0.005\text{ m}$) are strictly prohibited.
- **Ground penetration** ($Z_{\min} < -0.005\text{ m}$) is strictly prohibited.

### Invariant 2: Support Surface Continuity
Every object placed via an `on` relation or `PLACED_ON_SUB_SURFACE` graph relation must be supported by a contiguous physical chain terminating at the ground plane ($Z = 0.0\text{ m}$):
$$\text{Manipuland} \xrightarrow{\text{on}} \text{SurfaceAnchor} \xrightarrow{\text{has\_sub\_surface}} \text{Fixture} \xrightarrow{\text{rests\_on}} \text{Ground} (Z=0.0)$$

Arbitrary delta-Z shifts that do not trace back to the verified physical surface deck ($Z_{\text{deck}}$) of a grounded fixture violate this invariant.

---

## 3. Tooling Parity: OpenUSD Fixture Affordance Introspection

In early iterations, articulated assets (like `Microwave039.usd`) were equipped with dedicated OpenUSD introspection tooling ([`introspect_usd_affordance.py`](../../../scripts/tools/introspect_usd_affordance.py)) to discover joint kinematics and aperture normals, while static fixtures (tables, desks) were treated as passive, unmeasured entities.

**We enforce complete Tooling Parity**: static fixtures and backgrounds require the exact same depth of OpenUSD geometric introspection before establishing `on` relations or setting coordinates.

### The Fixture Introspection Tool
Run [`scripts/tools/introspect_fixture_affordance.py`](../../../scripts/tools/introspect_fixture_affordance.py):

```bash
docker exec isaaclab_arena-latest-isaaclab-arena-private /isaac-sim/python.sh \
  /workspaces/isaaclab_arena/scripts/tools/introspect_fixture_affordance.py \
  --usd office_table_background \
  --sync-neo4j \
  --check-grounding
```

### Extracted Affordance Properties
The introspection tool traverses the USD stage hierarchy with `pxr.UsdGeom.BBoxCache` to extract:
1. **$Z_{\min}$ (Ground Contact)**: Verifies whether the asset's lowest bounding vertex touches $0.0\text{ m}$.
2. **$Z_{\text{deck}}$ (True Physical Deck Height)**: The exact top surface coordinate $Z_{\max}$ of the fixture in its grounded pose.
3. **Surface Bounding Polygon**: Usable support bounds $[X_{\min}, X_{\max}] \times [Y_{\min}, Y_{\max}]$, preventing objects from spawning on table edges or in thin air.
4. **Surface Sectors**: Canonical division into `center`, `front_center`, `front_left`, `front_right`, `back_left`, `back_right`.

### Materializing Fixtures in Neo4j LPG
The script synchronizes the verified affordance directly to Neo4j:

```cypher
MERGE (f:Fixture {name: $fixture_name})
SET f.usd_path = $usd_path,
    f.scale = $scale,
    f.dimensions_m = $dimensions_m,
    f.z_min = $z_min,
    f.z_deck = $z_deck,
    f.is_grounded = $is_grounded,
    f.last_introspected = datetime()
MERGE (s:SurfaceAnchor {id: $fixture_name + '_surface_top'})
SET s.anchor_name = 'table_top',
    s.deck_height_m = $z_deck,
    s.bounds_x = [$xmin, $xmax],
    s.bounds_y = [$ymin, $ymax],
    s.usable_area_m2 = ($xmax - $xmin) * ($ymax - $ymin)
MERGE (f)-[:HAS_SUB_SURFACE {is_primary: true}]->(s)
```

Now, generative agents and query engines fetch the grounded deck height ($Z_{\text{deck}}$) directly from the knowledge graph rather than hallucinating coordinates.

---

## 4. Kinematic Harmonization Patterns

When the robot manipulator's operating height and the fixture's deck height do not match, coding agents must employ one of two **Kinematic Harmonization Patterns**. Floating the fixture is never an option.

### Pattern A: Realistic Workbench Selection (Recommended for Workbenches)
Match the robot embodiment to an asset inherently designed for standard manipulation tasks:
- **Standard DROID Franka Stand**: Designed for a standard $0.75\text{ m}$ laboratory workbench.
- **Asset Choice**: Use `table_oak_robolab`, `packing_table`, or `table_maple_robolab`.
- **Properties**: At $Z_{\text{base}} = 0.0\text{ m}$, the physical tabletop deck is naturally at $Z_{\text{deck}} = 0.75\text{ m}$.
- **Result**: The table sits on the floor, the robot stand sits on the floor, and manipulation kinematics align naturally.

```yaml
# PATTERN A: Grounded Fixture Selection
background:
  id: robolab_table
  registry_name: table_oak_robolab   # Natural deck at Z = 0.75m
  params:
    initial_pose:
      position_xyz: [0.0, 0.0, 0.0]   # Rests on ground!
```

### Pattern B: Stand Parameterization (For Low Tables or Custom Heights)
When the task domain specifically requires a low table (e.g. coffee table, $Z_{\text{deck}} \approx 0.53\text{ m}$) or custom surface:
- **Preserve Grounding**: Keep the table grounded at $Z_{\text{base}} = 0.0\text{ m}$.
- **Harmonize Embodiment Stand**: In `isaaclab_arena/embodiments/droid/droid.py`, the DROID embodiment supports `stand_height_m`:
  ```python
  # In droid.py:
  class DroidEmbodimentBase(EmbodimentBase, ABC):
      def __init__(
          self,
          ...,
          stand_height_m: float = _DROID_STAND_PRIM.stand_default_height,
      ):
  ```
- **Adjust the Stand**: Pass the lower `stand_height_m` and corresponding robot mount height in the embodiment configuration, lowering the robot mount so the manipulator workspace aligns with the low table while the stand base remains firmly on the ground.

---

## 5. Pre-Flight Grounding Verification Checklist

Before accepting any YAML spec, passing a self-healing repair step, or running Step-0 simulation, execute this checklist:

1. **Fixture Grounding Check**:
   $$\forall \text{ fixture } f \in \text{Scene}, \quad Z_{\text{base}}(f) = 0.0\text{ m}$$
   Confirm no fixture has a non-zero Z coordinate in its `initial_pose.position_xyz`.
2. **OpenUSD Introspection Preflight**:
   Has the asset USD been introspected with `introspect_fixture_affordance.py`?
   Does $Z_{\min} == 0.0\text{ m}$ in the asset's bounding box?
3. **Deck Height Continuity**:
   Do objects placed on the fixture specify `delta_z.nominal` equal to the introspected $Z_{\text{deck}}$ (plus object center-of-mass half-height)?
4. **Oracle Pass 6 Standoff & Elevation Gate**:
   Execute `verify_articulated_spec.py` and ensure Pass 6 verifies standoff ($0.50\text{ m} \le d \le 1.20\text{ m}$) and surface elevation without floating fixture defects.
5. **Knowledge Graph Sync**:
   Verify that `(:Fixture)-[:HAS_SUB_SURFACE]->(:SurfaceAnchor)` is registered in `neo4j-arena` (Port 7688).

---

## 6. Related Tools & References

- Tool: [`scripts/tools/introspect_fixture_affordance.py`](../../../scripts/tools/introspect_fixture_affordance.py)
- Oracle: [`scripts/tools/verify_articulated_spec.py`](../../../scripts/tools/verify_articulated_spec.py)
- MCP Server: `arena-grounding-guard` (`/root/.gemini/antigravity-cli/mcp/arena-grounding-guard/`)
- Startup Skill: [`.agent/skills/arena-session-startup/SKILL.md`](../arena-session-startup/SKILL.md)
