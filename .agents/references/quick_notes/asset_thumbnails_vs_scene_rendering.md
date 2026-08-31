# Asset Thumbnails vs. Scene Preview Rendering in IsaacLab-Arena & Omniverse

This reference document outlines the distinction between **In-Situ Scene Rendering** and **Standalone Asset Thumbnail Generation**, detailing how Omniverse Nucleus generates and caches asset thumbnails for GUI pickers.

---

## 1. Core Architectural Distinction

| Dimension | In-Situ Scene Rendering (Contextual) | Standalone Asset Thumbnail (Isolated) |
| :--- | :--- | :--- |
| **Scope** | Entire assembled scene (Robot + Table + Objects + Relations) | Single standalone USD asset |
| **Pipeline** | `ArenaEnvBuilder` + `ObservationManager` (`external_camera_rgb`, `wrist_cam`) | Isolated USD stage + `pxr.UsdGeom.BBoxCache` Auto-Framing |
| **Camera View** | Robot workspace perspective (simulates camera sensors during policy execution) | Isometric studio turntable view ($45^\circ$ azimuth, $30^\circ$ elevation) |
| **Background** | Room/Environment/Tabletop background fixture | Neutral 18% grey or transparent alpha |
| **Primary Use Case** | Visual verification of robot reachability, object clearances, and physics stability | Visual asset discovery, GUI object pickers (Omniverse Asset Browser / Nucleus) |

---

## 2. How NVIDIA Omniverse Nucleus Generates Asset Thumbnails

In NVIDIA Omniverse (e.g. `omni.kit.thumbnails`, `omni.services.usd.thumbnail`, Nucleus Server), thumbnail generation for the Asset Browser GUI follows a standardized 4-step pipeline:

### Step 1: Compute Exact USD Bounding Box (AABB)
Nucleus uses Pixar USD's `BBoxCache` to compute the tight bounding box and geometric midpoint across all mesh prims:

```python
from pxr import Usd, UsdGeom, Gf

bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
bbox = bbox_cache.ComputeWorldBound(stage.GetPseudoRoot())
aligned_box = bbox.ComputeAlignedBox()

min_pt = aligned_box.GetMin()
max_pt = aligned_box.GetMax()
center = (min_pt + max_pt) / 2.0
size = max_pt - min_pt
bounding_radius = size.GetLength() / 2.0
```

### Step 2: Auto-Frame Camera with Distance Padding
The camera position is computed dynamically from the bounding radius $r$ and field of view $\theta$ so any asset (from a 3 cm Rubik's cube to a 2 m shelving rack) fills ~80% of the thumbnail frame:

$$\text{distance} = \frac{r}{\sin(\theta / 2)} \times 1.25$$

$$\mathbf{eye} = \mathbf{center} + \text{distance} \cdot \left[ \frac{1}{\sqrt{3}}, -\frac{1}{\sqrt{3}}, \frac{1}{\sqrt{3}} \right]$$

### Step 3: Studio Lighting & Transparent Background
* A 3-point studio lighting setup (Key light, Fill dome light, Rim light) is spawned.
* Background ground planes and room fixtures are omitted to allow transparent PNG alpha or uniform neutral grey (`#1E1E1E`).

### Step 4: Storage & Caching
Omniverse Nucleus stores generated thumbnails alongside the USD asset:
* File Cache: `<asset_name>.usd.thumb.png` or in a hidden `.thumbs/<asset_name>.png` directory.
* USD Metadata: Embedded in `assetInfo["thumbnail"]` asset path on the default prim.

---

## 3. Tool Implementations in IsaacLab-Arena

### A. Standalone Asset Thumbnail Renderer (`render_isolated_thumbnail.py`)
Renders isolated USD assets with automatic AABB auto-framing and studio turntable lighting for asset selection:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/tools/render_isolated_asset_thumbnail.py \
  --asset blue_sorting_bin \
  --out /workspaces/isaaclab_arena/eval_output/thumbnails/blue_sorting_bin_thumb.png
```

### B. In-Situ Scene Preview Renderer (`render_scene_preview.py`)
Renders the complete generated environment (robot embodiment, table, placed objects, lighting) to verify scene layout and camera coverage before running policy evaluations:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/tools/render_scene_preview.py \
  --env_graph_spec_yaml /workspaces/isaaclab_arena/generated_envs/droid_rubiks_small_blue_bin/droid_pick_rubiks_cube_to_blue_bin.yaml \
  --out_dir /workspaces/isaaclab_arena/eval_output/scene_previews
```

---

## 4. Container & Receptacle Asset Quick Reference

When selecting containers without scaling `blue_sorting_bin`, use these registered asset identifiers:

| Asset Name | Default Scale | Visual Classification |
| :--- | :--- | :--- |
| `blue_sorting_bin` | `(4.0, 2.0, 1.0)` | Large blue sorting bin with divider slots |
| `bin_a06_vomp_robolab` | `(1.0, 1.0, 1.0)` | Compact industrial square bin |
| `bin_b03_vomp_robolab` | `(1.0, 1.0, 1.0)` | Shallow rectangular plastic tray/bin |
| `bin_b04_vomp_robolab` | `(1.0, 1.0, 1.0)` | Medium rectangular sorting bin |
| `grey_bin_robolab` | `(0.007, 0.007, 0.007)` | Compact grey RoboLab sorting bin |
| `purple_crate` | `(1.0, 1.0, 1.0)` | European standard KLT small industrial crate |
| `storage_box_hot3d_robolab` | `(1.0, 1.0, 1.0)` | HOT3D clear/grey storage container |
| `wooden_bowl_hot3d_robolab` | `(1.0, 1.0, 1.0)` | Wooden bowl container |
| `bowl_ycb_robolab` | `(1.0, 1.0, 1.0)` | YCB ceramic bowl container |
