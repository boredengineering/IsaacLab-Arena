# IsaacLab-Arena Operational & Verification Tools (`scripts/tools/`)

This directory contains standalone CLI tools, deterministic verification oracles, OpenUSD affordance introspectors, and model weight management utilities for IsaacLab-Arena.

---

## 1. Specification Verification & Kinematic Oracles

### `verify_articulated_spec.py`
Deterministic physical, geometric, and kinematic tooling oracle for validating autonomously generated `ArenaEnvGraphSpec` YAML specifications before running PhysX simulation.

**Capabilities:**
- **Pass 1 (Schema & Integrity)**: Validates required top-level keys, entity registrations, and composite task definitions.
- **Pass 2 (USD Stage Kinematics)**: Inspects live OpenUSD prims to confirm joint types (revolute vs prismatic), joint names, and valid limits.
- **Pass 3a (2D Footprint Overlap)**: Uses 2D Separating Axis Theorem (SAT) on oriented bounding boxes to verify min $\ge 0.05\,\text{m}$ clearance between manipulands and props.
- **Pass 3b (Support Surface & Sector Containment)**: Verifies that placed objects lie strictly within the physical support bounds and designated sector of the parent fixture deck.
- **Pass 3c (Swept Volume Clearance)**: Analytically computes 3D swept volumes for revolute door swing arcs ($\mathcal{W}_{\text{revolute}}$) and prismatic slide corridors ($\mathcal{V}_{\text{prismatic}}$), ensuring staged objects do not collide with moving parts.
- **Pass 4 (Sequential Handoff Invariants)**: Enforces completion criteria thresholds ($\ge 0.75$), standoff retract margins ($\ge 0.10\,\text{m}$), and proper multi-subtask transitions.
- **Pass 5 (Affordance Facing)**: Verifies that the aperture/handle normal of the articulated fixture faces the robot base ($\pm 45^\circ$).
- **Pass 6 (Standoff & Grounding Invariants)**: Validates robot-to-fixture horizontal standoff ($0.50\,\text{m} - 1.20\,\text{m}$), physical ground contact ($Z_{\text{base}} = 0.0\,\text{m}$), and tabletop elevation alignment with the robot stand.

**Usage:**
```bash
/isaac-sim/python.sh scripts/tools/verify_articulated_spec.py \
  --spec path/to/environment_spec.yaml \
  --json-report output_report.json
```

**Unit Tests:**
```bash
/isaac-sim/python.sh -m pytest isaaclab_arena/tests/test_verify_articulated_spec.py -v
```

---

### `audit_kinematic_articulation_clearance.py`
Standalone kinematic analyzer that calculates swept volume boundaries and verifies clearance between props and moving parts.

**Usage:**
```bash
/isaac-sim/python.sh scripts/tools/audit_kinematic_articulation_clearance.py \
  --spec path/to/spec.yaml
```

---

## 2. OpenUSD Affordance & Fixture Introspection

### `introspect_fixture_affordance.py`
Introspects static scene fixtures (tables, workbenches, counters, cabinets) using Pixar USD (`pxr.Usd`, `UsdGeom.BBoxCache`).
- Confirms physical ground contact ($Z_{\text{min}} = 0.0\,\text{m}$).
- Measures true physical deck height ($Z_{\text{deck}} = Z_{\text{max}}$) and surface bounding polygon.
- Discovers intrinsic sub-prims and optionally synchronizes affordance metadata to Neo4j.

**Usage:**
```bash
/isaac-sim/python.sh scripts/tools/introspect_fixture_affordance.py \
  --fixture office_table_background
```

### `introspect_usd_affordance.py`
Dynamic OpenUSD affordance extractor that introspects USD assets directly to extract articulation roots, joint kinematics, outward aperture normals, and swing geometry.

**Usage:**
```bash
/isaac-sim/python.sh scripts/tools/introspect_usd_affordance.py \
  --asset path/to/asset.usd
```

### `probe_asset_bboxes.py` & `probe_world_poses.py`
Quick Kit/USD inspection utilities to output bounding box extents and world transformation matrices.

**Usage:**
```bash
/isaac-sim/python.sh scripts/tools/probe_asset_bboxes.py
/isaac-sim/python.sh scripts/tools/probe_world_poses.py --usd path/to/stage.usd
```

---

## 3. Model Weight Management & Preflight Tools

### `download_openpi_weights.py`
Downloads and verifies OpenPI $\pi_0$ and $\pi_{0.5}$ checkpoints from HuggingFace to the local workstation cache (`artifacts/openpi_cache/`).

**Usage:**
```bash
python3 scripts/tools/download_openpi_weights.py \
  --model openpi-0.5 \
  --dest artifacts/openpi_cache/
```

### `download_and_verify.py`
Generic SHA256 and size-verified downloader for robotics policy checkpoints and foundation model weights.

**Usage:**
```bash
python3 scripts/tools/download_and_verify.py \
  --repo-id <hf-repo-id> \
  --dest-dir <target-directory>
```
