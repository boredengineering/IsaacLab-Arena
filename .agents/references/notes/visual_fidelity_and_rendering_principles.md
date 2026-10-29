# Visual Fidelity and Rendering Principles for IsaacLab-Arena

**Document Version:** 1.0.0  
**Context:** Derived from NVIDIA RoboLab architectural analysis and Isaac Sim Omniverse RTX best practices.  
**Target:** Enhancing visual fidelity, photorealism, and camera sensor rendering across IsaacLab-Arena generated scenes and preview thumbnails.

---

## 1. Executive Summary

Synthesized simulation scenes often look artificial, flat, or "CGI-like" due to three common pitfalls:
1. **Uncalibrated ambient lighting** (uniform point/distant lights producing razor-sharp, pitch-black shadows or washed-out surfaces).
2. **Artificial placement** (objects hovering millimeters above surfaces or perfectly aligned without physical micro-settling).
3. **Synthetic asset materials** (procedural flat colors lacking micro-surface roughness, specular reflection, and normal detail).

By analyzing NVIDIA's high-fidelity RoboLab visual pipeline and Omniverse RTX rendering practices, this note establishes the five core pillars required to make Arena scenes and preview renders look photorealistic.

---

## 2. The Five Pillars of Scene Realism

### 2.1 High-Bit-Depth Image-Based Lighting (IBL)
* **High-Dynamic-Range Environment Maps**: Replace generic skyboxes with high-bit-depth `.exr` (32-bit float) or 2K/4K `.hdr` environment maps (e.g., `home_office.exr`, `hotel_room_4k.hdr`, `machine_shop_01_4k.hdr`).
* **$360^\circ$ Ambient Illumination & Reflection**: When loaded into a `DomeLight` with `visible_in_primary_ray = True` and `texture_format = "latlong"`, the environment map acts as an infinite light emitter. It drives realistic environmental reflections on metal/glass/plastic surfaces, soft ambient occlusion, and subtle color bleeding.

### 2.2 Dual-Light Rig with Soft Penumbra Shadows
Realistic indoor lighting is rarely a single harsh source. RoboLab's screenshot generator (`render_utils.py`) employs a calibrated dual-light setup:
* **Key Light (`DistantLight`)**:
  * Set a realistic color temperature (e.g., `7250 K` cool daylight).
  * Configure a non-zero angular spread (`inputs:angle = 30.0`). This blurs shadow boundaries as distance increases, simulating an area light or window with soft penumbral contact shadows instead of razor-sharp edges.
  * Controlled intensity and exposure (`inputs:intensity = 1.0`, `inputs:exposure = 10.0`).
* **Fill Light (`DomeLight`)**:
  * Set a complementary warmer color temperature (`6150 K`).
  * Moderate exposure (`inputs:exposure = 9.0`) to illuminate deep shadow areas naturally without flattening contrast.

### 2.3 Photogrammetric PBR Scans & Surface Imperfections
* **Scanned Asset Foundations**: Assets sourced from optical scans (such as `HOT3D`, `HOPE`, `HANDAL`, `fruits_veggies`, and `SimReady Central`) provide authentic geometry and micro-imperfections.
* **Complete PBR Texture Sets**:
  * **Albedo / Diffuse**: Authentic color variations without baked-in directional lighting.
  * **Tangent-Space Normals**: Micro-textures (e.g., citrus fruit peel, wood grain, brushed metal, stamped text).
  * **Roughness / Metallic**: Fine-grained specular response preventing uniform "plastic gloss".

### 2.4 Preflight Physics Settling (Zero-Floating Invariant)
* **The "Floating Artifact"**: Authoring placement solely through bounding box heuristics or coordinate offsets inevitably results in objects floating 1–5 mm in mid-air or slightly penetrating fixture decks.
* **Settling Loop**: Run 50–100 simulation steps under gravity with PhysX contact dynamics enabled prior to capturing visual inspection frames or beginning episode evaluation. Objects naturally settle with physical micro-tilts, weight distribution, and resting contact.

### 2.5 Physically Grounded Camera Optics
* **Matched Sensor Intrinsics**:
  * Standardize camera sensors to real-world focal lengths (e.g., $24.0\,\text{mm}$ to $28.0\,\text{mm}$ focal length, $20.955\,\text{mm}$ horizontal aperture).
  * Avoid extreme wide-angle field-of-view distortions unless specifically modeling egocentric fisheye cameras.
* **Natural Robotic Perspectives**:
  * Frame scenes from calibrated operator perspectives (e.g., over-the-shoulder at $45^\circ$, eye-level tabletop height) matching physical Franka DROID workcell configurations.

---

## 3. 3D Gaussian Splatting (3DGS) & NVIDIA NuRec Neural Reconstruction

In addition to traditional mesh-based PBR assets and panoramic HDR domes, cutting-edge physical AI research (exemplified by NVIDIA RoboLab and World Labs) achieves near-photographic environment fidelity by incorporating **3D Gaussian Splatting (3DGS)** and **NVIDIA NuRec (Neural Reconstruction)**.

### 3.1 Why 3DGS Backgrounds Outperform Traditional Polygon Meshes
1. **Continuous Radiance & Micro-Detail**: Captures fine view-dependent specularities, subtle ambient inter-reflections, brushed metal sheens, and real-world micro-shadows that are prohibitively expensive or impossible to author manually via polygonal meshes.
2. **Authentic Environment Grounding**: Directly captured from real physical spaces (e.g., actual domestic kitchens, hospital stations, machine shops), eliminating the "sterile CGI" look.
3. **Real-Time RTX Splat Raycasting**: Omniverse Kit's `omni.rtx.spg` (Spatial Particle Grids) extension natively renders Gaussian splats alongside standard PhysX dynamic rigid bodies in the same offscreen viewport.

### 3.2 Omniverse NuRec Schema Architecture
Omniverse encapsulates 3DGS within a standard OpenUSD `Volume` prim using the **OmniNuRecFieldAsset** schema:

```usda
def Volume "Gaussian" (
    prepend apiSchemas = ["OmniNuRecVolumeAPI"]
)
{
    custom bool omni:nurec:isNuRecVolume = 1

    def OmniNuRecFieldAsset "density_field"
    {
        custom token fieldDataType = "float"
        custom token fieldName = "density"
        custom token fieldRole = "density"
        custom asset filePath = @MarbleKitchen.usdz[MarbleKitchen.nurec]@
    }

    def OmniNuRecFieldAsset "emissive_color_field"
    {
        custom token fieldDataType = "float3"
        custom token fieldName = "emissiveColor"
        custom token fieldRole = "emissiveColor"
        custom asset filePath = @MarbleKitchen.usdz[MarbleKitchen.nurec]@
        custom float4 omni:nurec:ccmB = (0, 0, 1, 0)
        custom float4 omni:nurec:ccmG = (0, 1, 0, 0)
        custom float4 omni:nurec:ccmR = (1, 0, 0, 0)
    }
}
```

* **Packaging (`.usdz`)**: Bundles the binary weights (`.nurec`) with USD descriptions (`gauss.usda`, `default.usda`) for portable distribution.
* **Density & Emissive Color Fields**: The density field governs volumetric transmittance and opacity, while the emissive color field maps view-dependent directional radiance (spherical harmonics).

### 3.3 The Hybrid Splat + Collision Proxy Mesh Design Pattern
> [!IMPORTANT]
> **3D Gaussian Splats have zero physical collision bounds.**
> Because 3DGS prims are purely volumetric optical emitters, physical rigid bodies (robots, grippers, cups, fruit) placed on a splat surface will fall straight through countertops into the void unless paired with a physical collision proxy.

RoboLab solves this via a **hybrid dual-layer USD architecture** (`assets/scenes/marble/marblekitchen.usda`):
1. **Visual Layer (`Volume/Gaussian`)**: An `OmniNuRecFieldAsset` displaying the photorealistic 3DGS kitchen.
2. **Physical Layer (`geometry_0`)**: An invisible, co-registered proxy collision mesh authoring PhysX dynamics:
   ```usda
   def Xform "geometry_0"
   {
       token visibility = "invisible"  # Hidden from camera rays
       quatf xformOp:orient = (0.5, -0.5, -0.5, 0.5)
       double3 xformOp:translate = (59.2, -5.19115, 3.87041)

       def Mesh "geometry_0" (
           apiSchemas = ["PhysicsCollisionAPI", "PhysxCollisionAPI", "PhysxTriangleMeshCollisionAPI"]
       )
       {
           # Contact geometry aligned with the splat countertop and sink
       }
   }
   ```
This invariant allows PhysX rigid-body solvers to calculate resting contacts, grasps, and placement dynamics on countertops while cameras observe photorealistic splats.

### 3.4 Public 3DGS Kitchen Datasets & NVIDIA Resources
Teams can leverage several high-fidelity 3DGS and neural reconstruction resources:

1. **RoboLab Marble Kitchen**:
   - Packaged as `MarbleKitchen.usdz` (236 MB) + `marblekitchen.usda`.
   - Captured via World Labs Marble reconstruction platform; includes co-registered invisible PhysX collision proxy mesh.
2. **NVIDIA Hugging Face Physical AI Ecosystem**:
   - `nvidia/PhysicalAI-Robotics-NuRec`: 400+ real-world robotics and manipulation scenes captured as NuRec OpenUSD assets.
   - `nvidia/instant-nurec`: Automated pipeline for converting multi-view camera video into NuRec USDs.
   - `nvidia/Harmonizer`: Diffusion-based image harmonizer tailored to blend synthetic foreground objects into neural background plates.
   - `nvidia/Lyra`: Feed-forward, single-pass 3DGS reconstruction from sparse camera viewpoints.
3. **Open 3DGS Kitchen Benchmarks**:
   - **Mip-NeRF 360 "Kitchen"**: Industry-standard real-world indoor capture benchmark, publicly available converted to 3DGS format.
   - **ScanNet++ Kitchens / Living Spaces**: High-resolution DSLR + sub-millimeter LiDAR scans with full camera trajectories, converted to 3DGS.
   - **DL3DV-10K**: Extensive collection of 10,000 indoor/outdoor camera trajectories including modern kitchen setups.

### 3.5 Omniverse RTX Engine Requirements for 3DGS
To render NuRec / 3DGS in Isaac Sim:
* **Extension**: `omni.rtx.spg` (version $\ge$ 0.2.0, ships natively in Isaac Sim 6.0).
* **Launch Arguments**: Must be passed to `SimulationApp`:
  ```python
  extra_args = ["--enable", "omni.rtx.spg", "--/renderer/multiGpu/enabled=false"]
  simulation_app = SimulationApp({"headless": True, "extra_args": extra_args})
  ```
* **Carb Rendering Overrides**: NuRec uses RTPT warmup accumulation:
  - Warmup steps: 800 ticks for offline frame convergence; 30–60 ticks for interactive evaluation.

---

## 4. Concrete Implementation in IsaacLab-Arena

### 4.1 Defining a Calibrated Studio / Indoor Lighting Config
In Arena or IsaacLab environment configs, define an `AssetBaseCfg` light rig combining HDR dome lighting and soft distant lighting:

```python
import isaaclab.sim as sim_utils
from isaaclab.assets import AssetBaseCfg
from isaaclab.utils import configclass


@configclass
class PhotorealisticStudioLightingCfg:
    """Calibrated dual-light rig with IBL dome and soft penumbra directional light."""

    # 1. 360-degree HDR/EXR dome light for realistic reflections and ambient fill
    dome_light = AssetBaseCfg(
        prim_path="/World/DomeLight",
        spawn=sim_utils.DomeLightCfg(
            intensity=1.0,
            exposure=9.0,
            color=(1.0, 1.0, 1.0),
            visible_in_primary_ray=True,
            texture_format="latlong",
            texture_file="assets/backgrounds/indoors/hotel_room_4k.hdr",
        ),
    )

    # 2. Key directional light with non-zero angular spread for soft contact shadows
    key_light = AssetBaseCfg(
        prim_path="/World/KeyLight",
        spawn=sim_utils.DistantLightCfg(
            intensity=1.0,
            exposure=10.0,
            color=(1.0, 1.0, 1.0),
            angle=30.0,  # 30 deg spread for soft penumbra shadows
        ),
        init_state=AssetBaseCfg.InitialStateCfg(
            pos=(0.0, 0.0, 3.0),
            rot=(0.7071, 0.0, 0.7071, 0.0),  # Angled down onto workspace
        ),
    )
```

### 4.2 Viewport Rendering Pipeline Parameters
When generating screenshots, evaluation videos, or step-0 VLM inspection frames via `SimulationApp`:

```python
def configure_high_fidelity_camera(stage, camera_prim_path="/OmniverseKit_Persp"):
    """Applies physically calibrated camera intrinsics to eliminate distortion."""
    camera_prim = stage.GetPrimAtPath(camera_prim_path)
    camera_prim.GetAttribute("focalLength").Set(24.0)          # 24 mm standard
    camera_prim.GetAttribute("horizontalAperture").Set(20.955) # 35mm equivalent sensor
```

### 4.3 Physics Stabilization Hook
Ensure scene generators execute dynamic settle before saving static USDA stages or rendering thumbnails:

```python
def settle_and_capture(world, camera, settle_steps=60):
    """Steps PhysX simulation until linear and angular velocities settle near zero."""
    for _ in range(settle_steps):
        world.step(render=False)
    world.step(render=True)
    return camera.get_rgba()[:, :, :3]
```

---

## 5. Feasibility & Integration Review: Adding MarbleKitchen to IsaacLab-Arena

Can our current IsaacLab-Arena setup run the necessary components to render and simulate tasks in `MarbleKitchen`?

### 5.1 Verification Checklist & Compatibility Matrix

| Component | Status | Finding / Verification Result |
| :--- | :--- | :--- |
| **Isaac Sim Version** | **Compatible** | Isaac Sim 6.0 (Kit 106.5 / 110.x compatible) runs inside container `isaaclab_arena-latest-isaaclab-arena-private`. |
| **GPU / Hardware** | **Compatible** | Dual Blackwell GPUs (`RTX PRO 6000` 96 GB + `RTX 5090` 32 GB, `sm_120`, driver 13.2, Warp 1.13.0). |
| **3DGS / SPG Extension** | **Verified Active** | Tested live in container: `omni.rtx.spg-0.2.1` loads, initializes, and activates successfully via `SimulationApp(extra_args=["--enable", "omni.rtx.spg", "--/renderer/multiGpu/enabled=false"])`. |
| **NuRec Utilities** | **Present** | `isaacsim.replicator.nurec_utils` and `nurec_render.py` are natively available under `/isaac-sim/exts/` in the simulation container. |
| **USD NuRec Schema** | **Compatible** | Isaac Sim's OpenUSD plug-in registry loads `OmniNuRecFieldAsset` definitions and resolves `@MarbleKitchen.usdz[MarbleKitchen.nurec]@`. |
| **Container Mount Boundary** | **Requires Action** | The asset files (`MarbleKitchen.usdz` 236 MB, `marblekitchen.usda`) currently reside in `/workspaces/RoboLab/assets/scenes/marble/`. The devcontainer (`wizardly_knuth`) mounts RoboLab, but the inner simulation container (`isaaclab_arena`) only mounts `isaaclab-arena-private`. |

### 5.2 Resolution for the Mount Boundary
Because both repositories reside on the exact same host NVMe partition (`/dev/nvme0n1p2 ext4`), staging the assets into `isaaclab-arena-private` does not require re-downloading or significant disk space:
```bash
# From the devcontainer or host:
mkdir -p artifacts/assets/marble
cp -l /workspaces/RoboLab/assets/scenes/marble/MarbleKitchen.usdz artifacts/assets/marble/
cp /workspaces/RoboLab/assets/scenes/marble/marblekitchen.usda artifacts/assets/marble/
```
*(Using `cp -l` creates a hardlink on the same filesystem, taking 0 extra storage bytes and completing instantly.)*

### 5.3 Arena Integration Recipe & Actions Executed
The integration has been executed and verified live:
1. **Staging**: Assets staged under `artifacts/assets/marble/` (`MarbleKitchen.usdz` [226 MB], `marblekitchen.usda` [19 MB]).
2. **Git Invariant Enforcement**: Added `artifacts/assets/marble/` to `.gitignore` to maintain strict repo boundaries (never commit large binary blobs/weights).
3. **Asset Registration**: Implemented `MarbleKitchenBackground` in [`isaaclab_arena/assets/background_library.py`](../../../isaaclab_arena/assets/background_library.py):
   ```python
   _MARBLE_LOCAL_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "assets" / "marble"


   @register_asset
   class MarbleKitchenBackground(LibraryBackground):
       """3DGS Marble Kitchen scene with co-registered PhysX collision proxy."""

       name = "marble_kitchen"
       tags = ["background", "3dgs", "nurec", "kitchen"]
       usd_path = str(_MARBLE_LOCAL_DIR / "marblekitchen.usda")
       initial_pose = Pose.identity()
       object_min_z = -0.5
   ```
4. **Live Container Verification & Simulation Stepping**:
   Created [`artifacts/assets/marble/verify_marble_kitchen.py`](../../../artifacts/assets/marble/verify_marble_kitchen.py) and executed inside the `isaaclab_arena-latest-isaaclab-arena-private` container.
   * **Verification Command**:
     ```bash
     docker exec isaaclab_arena-latest-isaaclab-arena-private \
       /isaac-sim/python.sh /workspaces/isaaclab_arena/artifacts/assets/marble/verify_marble_kitchen.py
     ```
   * **Results**:
     - `omni.rtx.spg-0.2.1` initialized cleanly.
     - `AssetRegistry` resolved `MarbleKitchenBackground` with tags `['background', '3dgs', 'nurec', 'kitchen']`.
     - `SimulationContext` created the PhysX physics scene and spawned the USD stage at `/World/MarbleKitchen`.
     - Validated collision mesh with applied schemas: `['PhysicsCollisionAPI', 'PhysxCollisionAPI', 'PhysxTriangleMeshCollisionAPI', 'PhysicsMeshCollisionAPI']`.
     - Validated NuRec volume prim and density field `@MarbleKitchen.usdz[MarbleKitchen.nurec]@`.
     - Successfully completed 20 simulation steps with PhysX dynamic updates. Zero crashes or divergence.

5. **Interactive GUI Inspection & Closed-Loop Policy Rollout (`pick_banana_to_plate_marble`)**:
   Created the environment specification [`generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml`](../../../generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml) to ground the Franka DROID arm, YCB banana, and plate directly on the 3DGS marble kitchen.
   
   To visually inspect and execute the task live in the Kit GUI window with OpenPI $\pi_{0.5}$:
   ```bash
   xhost +local:docker > /dev/null 2>&1

   docker exec -it \
     -e DISPLAY=$DISPLAY \
     --user $(id -u):$(id -g) \
     isaaclab_arena-latest-isaaclab-arena-private \
     bash -c "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
       --policy_type isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy \
       --policy_variant pi05 \
       --openpi_embodiment_adapter droid \
       --remote_host 127.0.0.1 \
       --remote_port 8008 \
       --open_loop_horizon 8 \
       --num_episodes 1 \
       --enable_cameras \
       --viz kit \
       --kit_args '--enable omni.rtx.spg --/renderer/multiGpu/enabled=false' \
       --env_spec generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml"
   ```

   *(Note: For passive visual inspection without a running policy server, substitute `--policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy`.)*

---

## 6. Architectural Gap & Future Fix: Automated Dynamic Asset Discovery

> [!WARNING]
> **The Manual Registration Bottleneck**:
> Currently, every new asset—whether a SimReady CAD fixture, a photogrammetric PBR scan, or a 3DGS NuRec capture—requires a developer or agent to manually open `background_library.py` or `object_library.py` and write a bespoke Python subclass decorated with `@register_asset`.
> This pattern is fragile, scales poorly across distributed multi-asset pipelines, and tightly couples asset file downloads to library code edits.

### 6.1 Requirements for a Robust Dynamic Discovery System
To eliminate manual library editing, Arena should implement a pluggable, automated asset discovery mechanism:

1. **Manifest-Driven Asset Packages (`asset_manifest.yaml`)**:
   Any asset staged under `artifacts/assets/<asset_name>/` or custom mounted volumes can include a standardized declarative descriptor:
   ```yaml
   name: marble_kitchen
   type: background
   tags: [background, 3dgs, nurec, kitchen]
   usd_file: marblekitchen.usda
   initial_pose:
     position: [0.0, 0.0, 0.0]
     rotation_xyzw: [0.0, 0.0, 0.0, 1.0]
   object_min_z: -0.5
   spg_required: true
   ```

2. **USD Introspection Crawler (`ensure_assets_registered`)**:
   Enhance `ensure_assets_registered()` in [`isaaclab_arena/assets/registries.py`](../../../isaaclab_arena/assets/registries.py) to run an automated directory scan over registered asset paths:
   * **Schema Introspection**: Crawl `.usd`/`.usda` files; if prims contain `OmniNuRecFieldAsset` or `omni:nurec:isNuRecVolume`, auto-tag as `["3dgs", "nurec"]`.
   * **Collision Detection**: Check for `PhysicsCollisionAPI` / `PhysxCollisionAPI` to determine whether the stage includes intrinsic physics proxies or needs procedural table planes.
   * **Dynamic Class Factory**: Use `type("DynamicBackground_" + name, (LibraryBackground,), class_dict)` to register the asset into `AssetRegistry` at runtime without requiring static Python code edits.

3. **External Volume Mounting & Environment Variable Path Resolution**:
   Introduce `ARENA_ASSET_PATHS` (colon-delimited paths, similar to `PXR_USD_PATH_SEARCH` or ROS `CMAKE_PREFIX_PATH`). This allows mounting arbitrary host asset directories (such as `/workspaces/RoboLab/assets` or NAS/S3 shares) directly without copying them into the project repository.

---

## 7. Interactive Omniverse Kit Visualization (`--viz kit`) & Available Environments

### 7.1 Host Command to Launch Interactive Omniverse Kit GUI (`--viz kit`)

When launching `policy_runner.py` inside the simulation container from the host terminal with `--viz kit`, two flags are required on `docker exec` for Omniverse Kit's GLFW windowing plugin (`carb.windowing-glfw.plugin`) to spawn the GUI on the host desktop:

1. **`-e DISPLAY=$DISPLAY`**: Forwards the active host X11 display identifier (e.g., `:1`) into the container. Because the container shares the host network namespace (`--net=host`), `libX11` and GLFW connect directly to the host's abstract X11 Unix socket (`@/tmp/.X11-unix/X*`).
2. **`--user $(id -u):$(id -g)`**: Maps directly by numeric UID/GID (`1000:1000`) rather than `su $(id -un) -c` (which expands `$(id -un)` on the host shell to the host username, e.g., `tarfy`, whereas UID `1000` inside the container is `ubuntu`). Matching numeric UID `1000` satisfies host `xhost` / `SI:localuser` authorization and preserves `-e DISPLAY=$DISPLAY`.

```bash
# 1. Grant local X11 display access on the host
xhost +local:docker > /dev/null 2>&1

# 2. Launch interactive closed-loop evaluation with the Omniverse Kit UI (--viz kit)
docker exec -it \
  -e DISPLAY=$DISPLAY \
  --user $(id -u):$(id -g) \
  isaaclab_arena-latest-isaaclab-arena-private \
  bash -c "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
    --policy_type isaaclab_arena_openpi.policy.pi0_remote_policy.Pi0RemotePolicy \
    --policy_variant pi05 \
    --openpi_embodiment_adapter droid \
    --remote_host 127.0.0.1 \
    --remote_port 8008 \
    --open_loop_horizon 8 \
    --num_episodes 1 \
    --enable_cameras \
    --viz kit \
    --env_spec generated_envs/pick_banana_to_plate/v1/pick_banana_to_plate.yaml"
```

> [!TIP]
> **Enabling 3DGS / NuRec Rendering in `--viz kit` (`ZeroActionPolicy` Scene Inspection)**:
> When loading a 3D Gaussian Splatting (3DGS / NuRec) environment such as `generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml` or [`generated_envs/marble_kitchen_inspection.yaml`](../../../generated_envs/marble_kitchen_inspection.yaml), pass `--kit_args '--enable omni.rtx.spg --/renderer/multiGpu/enabled=false'` so Omniverse Kit loads the Spatial Particle Grids (`omni.rtx.spg`) extension on startup *(note: `pick_banana_to_plate_marble.yaml` is queued for review and alignment)*:
>
> ```bash
> xhost +local:docker > /dev/null 2>&1
>
> docker exec -it \
>   -e DISPLAY=$DISPLAY \
>   --user $(id -u):$(id -g) \
>   isaaclab_arena-latest-isaaclab-arena-private \
>   bash -c "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena/evaluation/policy_runner.py \
>     --policy_type isaaclab_arena.policy.zero_action_policy.ZeroActionPolicy \
>     --num_episodes 1 \
>     --enable_cameras \
>     --viz kit \
>     --kit_args '--enable omni.rtx.spg --/renderer/multiGpu/enabled=false' \
>     --env_spec generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml"
> ```

---

### 7.2 Catalog of Environments, Background Scenes, and HDR Domes

You can swap `--env_spec <path/to/spec.yaml>` in the command above to inspect or evaluate any of the following environment families across the repository:

#### A. Generated & Custom Environment Specs ([`generated_envs/`](../../../generated_envs/))
| Environment YAML Path | Background / Fixture | Description & Notes |
| :--- | :--- | :--- |
| [`generated_envs/pick_banana_to_plate/v1/pick_banana_to_plate.yaml`](../../../generated_envs/pick_banana_to_plate/v1/pick_banana_to_plate.yaml) | `maple_table_robolab` + `home_office_robolab` HDR | Calibrated DROID tabletop banana-to-plate task (`robot_droid` at `[0, 0, 0]`, `light_intensity: 500.0`, `directional_light_on: true`). Verified 100% closed-loop success (`267` steps). |
| `generated_envs/pick_banana_to_plate_marble/v1/pick_banana_to_plate_marble.yaml` | `marble_kitchen` (3DGS / NuRec) | 3DGS Marble Kitchen banana-to-plate variant (pending review & alignment). Requires `--kit_args '--enable omni.rtx.spg --/renderer/multiGpu/enabled=false'`. |
| [`generated_envs/marble_kitchen_inspection.yaml`](../../../generated_envs/marble_kitchen_inspection.yaml) | `marble_kitchen` (3DGS / NuRec) | Hybrid 3D Gaussian Splatting kitchen (`MarbleKitchen.usdz`) with co-registered invisible PhysX collision proxy mesh. Pass `--kit_args '--enable omni.rtx.spg --/renderer/multiGpu/enabled=false'`. |

#### B. SRL RoboLab Tabletop & Clutter Benchmarks ([`isaaclab_arena_environments/robolab/`](../../../isaaclab_arena_environments/robolab/) & [`maple_table_top/`](../../../isaaclab_arena_environments/maple_table_top/))
- **Standalone Maple Tabletop Specs ([`isaaclab_arena_environments/maple_table_top/`](../../../isaaclab_arena_environments/maple_table_top/))**:
  - [`droid_banana_on_plate_maple_table.yaml`](../../../isaaclab_arena_environments/maple_table_top/droid_banana_on_plate_maple_table.yaml): Banana, plate, two bagels, and bowl on `maple_table_robolab`.
  - [`droid_pick_fruit_into_bowl_maple_table.yaml`](../../../isaaclab_arena_environments/maple_table_top/droid_pick_fruit_into_bowl_maple_table.yaml): Multi-fruit tabletop sorting into a bowl.
  - [`droid_pick_fruit_and_bottle_into_bin_maple_table.yaml`](../../../isaaclab_arena_environments/maple_table_top/droid_pick_fruit_and_bottle_into_bin_maple_table.yaml): Cluttered tabletop fruit and bottle bin-packing.
  - [`simready_droid_pick_place_cans_hammer_maple_table.yaml`](../../../isaaclab_arena_environments/maple_table_top/simready_droid_pick_place_cans_hammer_maple_table.yaml): SimReady industrial tools and cans on `maple_table_robolab`.
- **RoboLab Tasks ([`isaaclab_arena_environments/robolab/tasks/`](../../../isaaclab_arena_environments/robolab/tasks/)) — 38 Task Overlays**:
  - **Tableware & Fruit**: [`banana_on_plate.yaml`](../../../isaaclab_arena_environments/robolab/tasks/banana_on_plate.yaml), [`banana_in_bowl.yaml`](../../../isaaclab_arena_environments/robolab/tasks/banana_in_bowl.yaml), [`bagels_on_plate.yaml`](../../../isaaclab_arena_environments/robolab/tasks/bagels_on_plate.yaml), [`apple_and_yogurt_in_bowl.yaml`](../../../isaaclab_arena_environments/robolab/tasks/apple_and_yogurt_in_bowl.yaml), [`clear_organic_objects.yaml`](../../../isaaclab_arena_environments/robolab/tasks/clear_organic_objects.yaml).
  - **Multi-Step & Precision**: [`rubiks_cube.yaml`](../../../isaaclab_arena_environments/robolab/tasks/rubiks_cube.yaml), [`rubiks_cube_and_banana.yaml`](../../../isaaclab_arena_environments/robolab/tasks/rubiks_cube_and_banana.yaml), [`rubiks_cube_then_banana.yaml`](../../../isaaclab_arena_environments/robolab/tasks/rubiks_cube_then_banana.yaml), [`banana_then_rubiks_cube.yaml`](../../../isaaclab_arena_environments/robolab/tasks/banana_then_rubiks_cube.yaml), [`marker_in_mug.yaml`](../../../isaaclab_arena_environments/robolab/tasks/marker_in_mug.yaml), [`mouse_on_keyboard.yaml`](../../../isaaclab_arena_environments/robolab/tasks/mouse_on_keyboard.yaml).
  - **Spatial / Semantic Bin Sorting**: [`canned_food_in_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/canned_food_in_bin.yaml), [`condiments_in_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/condiments_in_bin.yaml), [`mustard_in_left_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/mustard_in_left_bin.yaml), [`mustard_in_right_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/mustard_in_right_bin.yaml), [`hammers_in_left_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/hammers_in_left_bin.yaml), [`clamp_in_right_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/clamp_in_right_bin.yaml), [`non_hammer_tools_in_right_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/non_hammer_tools_in_right_bin.yaml), [`electronics_in_bin.yaml`](../../../isaaclab_arena_environments/robolab/tasks/electronics_in_bin.yaml), [`food_packing_1_boxes.yaml`](../../../isaaclab_arena_environments/robolab/tasks/food_packing_1_boxes.yaml), [`food_packing_1_cans.yaml`](../../../isaaclab_arena_environments/robolab/tasks/food_packing_1_cans.yaml).
- **RoboLab Base Scenes ([`isaaclab_arena_environments/robolab/scenes/`](../../../isaaclab_arena_environments/robolab/scenes/)) — 17 Composable Scene Graphs**:
  - Includes `bagel_plate_banana_bowl.yaml`, `banana_bowl.yaml`, `bin_condiments.yaml`, `bin_mug_mustard_marker_bowl.yaml`, `bottles_crate.yaml`, `butter_raisin_box.yaml`, `clutter_fruit_bottle_bluebin.yaml`, `foodpacking_1bin_1box_1can.yaml`, `mustard_raisin_box.yaml`, `rubiks_cube_banana_bowl.yaml`, `tools_container.yaml`, `two_bin.yaml`, `workdesk.yaml`, `workdesk_bin.yaml`, and `workdesk_snacks.yaml`.

#### C. Full-Scale Kitchen Benchmarks ([`isaaclab_arena_environments/kitchen_bench/`](../../../isaaclab_arena_environments/kitchen_bench/))
- **Lightwheel RoboCasa Kitchens (`kitchen_bench_lightwheel_*.yaml` — 17 Specs)**:
  - Full-room articulated kitchens across `g_shaped_large`, `u_shaped_with_island`, and `l_shaped` floorplans in `scandinavian` and `farmhouse2` styles.
  - Covers articulated appliance manipulation ([`kitchen_bench_lightwheel_open_fridge.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_fridge.yaml), [`kitchen_bench_lightwheel_open_microwave.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_microwave.yaml), [`kitchen_bench_lightwheel_open_oven_g_shaped_large_scandinavian.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_oven_g_shaped_large_scandinavian.yaml), [`kitchen_bench_lightwheel_open_cabinet_u_shaped_with_island_farmhouse2.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_cabinet_u_shaped_with_island_farmhouse2.yaml), toaster buttons, oven knobs) and counter pick-and-place ([`kitchen_bench_lightwheel_place_bananas_in_wooden_bowl_u_shaped_with_island_farmhouse2.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_place_bananas_in_wooden_bowl_u_shaped_with_island_farmhouse2.yaml)).
- **Omniverse Replicator Kitchens (`kitchen_bench_replicator_*.yaml` — 14 Specs)**:
  - PBR architectural kitchens in five layouts (`g_shape`, `l_island`, `l_shape`, `peninsula`, `u_shape`) with `banana_bowl`, `bowl_sink`, and `mustard_bowl` manipulation tasks (e.g., [`kitchen_bench_replicator_g_shape_banana_bowl.yaml`](../../../isaaclab_arena_environments/kitchen_bench/kitchen_bench_replicator_g_shape_banana_bowl.yaml)).

#### D. Registered Background Assets ([`background_library.py`](../../../isaaclab_arena/assets/background_library.py)) & HDR Lighting Domes ([`hdr_image_library.py`](../../../isaaclab_arena/assets/hdr_image_library.py))
When authoring or modifying an environment YAML spec under `background:`, you can combine any registered `registry_name` with any registered `hdr` dome:

- **Background `registry_name` Options**:
  - **3DGS / NuRec**: `marble_kitchen`
  - **SRL RoboLab Tables**: `maple_table_robolab`, `table_oak_robolab`
  - **SimReady Articulated Fixtures**: `kitchen_base_cabinet`, `fixture_counter_a01` (`sm_fixture_counter_a01_01`), `cart_medical_utility` (`sm_cart_medical_utility_a03_01`), `beverage_fridge` (`facilityEquipment_beverageFridge_display_a01`)
  - **Replicator Kitchens**: `replicator_kitchen_g_shape`, `replicator_kitchen_l_island`, `replicator_kitchen_l_shape`, `replicator_kitchen_peninsula`, `replicator_kitchen_u_shape`
  - **Full Rooms & Workcells**: `kitchen`, `kitchen_with_open_drawer`, `packing_table`, `galileo`, `galileo_locomanip`, `table`, `office_table_background`, `lightwheel_robocasa_kitchen`
- **HDR / EXR Dome Options (`background.params.hdr`)**:
  - **Default / Indoor**: `home_office_robolab` (32-bit `.exr` used in RoboLab DROID training), `billiard_hall_robolab`, `garage_robolab`, `wooden_lounge_robolab`
  - **Kitchen / Residential**: `blinds_robolab`, `kiara_interior_robolab`
  - **Studio**: `brown_photostudio_robolab`, `photo_studio_robolab`
  - **Industrial / Workshop**: `empty_warehouse_robolab`, `aerodynamics_workshop_robolab`, `carpentry_shop_robolab`

---

## 8. Cross-References

- **RoboLab Backgrounds**: Refer to backgrounds catalog in [`../../../RoboLab/docs/background.md`](../../../RoboLab/docs/background.md).
- **RoboLab Marble Kitchen Scene**: See [`../../../RoboLab/assets/scenes/marble/marblekitchen.usda`](../../../RoboLab/assets/scenes/marble/marblekitchen.usda) and task definition [`../../../RoboLab/robolab/tasks/test_tasks/marble.py`](../../../RoboLab/robolab/tasks/test_tasks/marble.py).
- **RoboLab Lighting Presets**: See [`../../../RoboLab/docs/lighting.md`](../../../RoboLab/docs/lighting.md) and [`../../../RoboLab/robolab/variations/lighting.py`](../../../RoboLab/robolab/variations/lighting.py).
- **Asset Grounding Standards**: See [`.agent/skills/arena-digital-twin-grounding/SKILL.md`](../../../.agent/skills/arena-digital-twin-grounding/SKILL.md).
