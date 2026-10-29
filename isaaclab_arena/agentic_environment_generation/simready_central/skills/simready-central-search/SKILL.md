---
name: simready-central
description: Search, inspect, download, and register NVIDIA SimReady Central OpenUSD assets into IsaacLab-Arena. Use when resolving ungrounded assets (office desks, drawers, appliances, industrial robots, grippers) or executing Epistemic Resolution workflows.
license: Apache-2.0
metadata:
  author: IsaacLab-Arena Project Developers
  version: "1.0.0"
---

<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# SimReady Central Asset Integration

## Purpose
Enables autonomous agents to query, inspect, download, and register production OpenUSD simulation-ready assets from NVIDIA SimReady Central (`https://nvidia-simready-central.hf.space` and `https://github.com/NVIDIA-Omniverse/simready-central`) into IsaacLab-Arena.

## Prerequisites
- Network connectivity to `https://nvidia-simready-central.hf.space` and `https://huggingface.co/datasets/nvidia/simready-assets`.
- Python client `isaaclab_arena.agentic_environment_generation.simready_central.SimReadyCentralClient`.
- OpenUSD environment (`pxr.Usd`, `pxr.UsdGeom`) inside the simulation container.

## Inputs
- Natural language query (e.g. `"office desk drawer"`, `"microwave"`, `"franka fr3"`, `"robotiq gripper"`).
- Optional category filter (e.g. `furniture`, `appliance`, `tool`, `robot`).
- Optional 3D bounding box constraints `[min_x, min_y, min_z]` and `[max_x, max_y, max_z]`.

## Tool Interfaces
Agents can interact with SimReady Central via either:
1. **MCP Lazy Tool**:
   - `simready_search(query="...", category="...", limit=5)`
   - `simready_get_manifest(manifest_url="...")`
   - `simready_download(asset_url="...", target_dir="...")`
   - `simready_list_oem_submissions(oem="nvidia"|"frankarobotics"|"Robotiq-Official")`
2. **Python Client API**:
   ```python
   from isaaclab_arena.agentic_environment_generation.simready_central import SimReadyCentralClient

   client = SimReadyCentralClient()
   hits = client.search_hybrid("office desk drawer", limit=5)
   for hit in hits:
       print(hit.name, hit.download_url)
   ```
3. **CLI Interface**:
   ```bash
   python3 -m isaaclab_arena.agentic_environment_generation.simready_central.mcp_server --search "desk drawer"
   ```

## Instructions

### Step 1: Hybrid Search & Asset Discovery
Execute `simready_search` with the target object description. SimReady Central evaluates:
- BM25 full-text scoring over prim paths, asset names, and package metadata.
- SigLIP2 1536-dimensional multimodal embedding cosine similarity.
- Bounding box dimensional filtering to match physical scene scale.

### Step 2: Semantic Fidelity & Refusal Gating
Compute the semantic domain similarity $\text{Sim}_{\text{semantic}}(\text{Prompt Domain}, \text{Hit Domain})$:
- If similarity $< 0.70$ (e.g. kitchen cabinetry proposed for an office room prompt), **reject the candidate** (`DEFECT_SEMANTIC_DOMAIN_MISMATCH`).
- Only proceed if the candidate fits both the semantic intent and physical affordance contracts.

### Step 3: Package Manifest Inspection
Retrieve `com.nvidia.simready.packaging.json` using `simready_get_manifest`:
- Verify license compliance (`CC-BY-4.0` or compatible).
- Confirm Bill of Materials (BOM) contains expected LOD meshes, colliders, and physics components (`PhysicsRigidBodyAPI`, `PhysicsJointAPI`).

### Step 4: Asset Download & Local Caching
Download the target `.usd` stage into `artifacts/assets/simready/`:
```bash
python3 -c "
from isaaclab_arena.agentic_environment_generation.simready_central import SimReadyCentralClient
client = SimReadyCentralClient()
client.download_asset('<download_url>', target_dir='artifacts/assets/simready')
"
```

### Step 5: Digital Twin Grounding & OpenUSD Introspection
Run OpenUSD introspection via `introspect_usd_fixture`:
1. Verify ground contact: $|Z_{\min}| \le 0.005\text{ m}$.
2. Measure physical deck height: $Z_{\text{deck}} = Z_{\max}$.
3. Measure surface bounding polygon: $[X_{\min}, X_{\max}] \times [Y_{\min}, Y_{\max}]$.
4. For articulated assets, extract the joint type (`Prismatic` vs. `Revolute`), axis $\hat{\mathbf{u}}$, and limit $q_{\max}$.

### Step 6: Registration & Knowledge Sync
Register the certified asset in `AssetRegistry`:
- Transition the Orchestrator proposition from $\text{Unknown} \to \text{True}$.
- Synchronize the asset node and affordance anchors to the Neo4j LPG and RDF-star graph.

## Limitations
- Only download assets required by active scenario specs to conserve local storage.
- Always check that downloaded stages do not violate the Digital Twin Grounding Invariant ($Z_{\text{base}} = 0.0\text{ m}$).
