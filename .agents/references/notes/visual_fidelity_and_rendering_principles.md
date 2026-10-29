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

## 3. Concrete Implementation in IsaacLab-Arena

### 3.1 Defining a Calibrated Studio / Indoor Lighting Config
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

### 3.2 Viewport Rendering Pipeline Parameters
When generating screenshots, evaluation videos, or step-0 VLM inspection frames via `SimulationApp`:

```python
def configure_high_fidelity_camera(stage, camera_prim_path="/OmniverseKit_Persp"):
    """Applies physically calibrated camera intrinsics to eliminate distortion."""
    camera_prim = stage.GetPrimAtPath(camera_prim_path)
    camera_prim.GetAttribute("focalLength").Set(24.0)          # 24 mm standard
    camera_prim.GetAttribute("horizontalAperture").Set(20.955) # 35mm equivalent sensor
```

### 3.3 Physics Stabilization Hook
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

## 4. Cross-References

- **RoboLab Backgrounds**: Refer to backgrounds catalog in [`../../../RoboLab/docs/background.md`](../../../RoboLab/docs/background.md).
- **RoboLab Lighting Presets**: See [`../../../RoboLab/docs/lighting.md`](../../../RoboLab/docs/lighting.md) and [`../../../RoboLab/robolab/variations/lighting.py`](../../../RoboLab/robolab/variations/lighting.py).
- **Asset Grounding Standards**: See [`.agent/skills/arena-digital-twin-grounding/SKILL.md`](../../../.agent/skills/arena-digital-twin-grounding/SKILL.md).
