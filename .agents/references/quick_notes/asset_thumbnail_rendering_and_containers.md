# Asset Thumbnail Rendering & Container Catalog Reference

This quick note explains how to render registered IsaacLab-Arena assets into high-resolution PNG thumbnails using parallel GPU rendering, and lists all available container/bin/box assets in the library.

---

## 1. How to Render Assets into PNG Thumbnails

Use the parallel batch rendering utility [`isaaclab_arena_examples/tools/render_asset_thumbnails.py`](../../../isaaclab_arena_examples/tools/render_asset_thumbnails.py) to generate studio-lit PNG previews of any assets registered in `AssetRegistry`:

```bash
docker exec -it \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/tools/render_asset_thumbnails.py \
  --assets blue_sorting_bin bin_a06_vomp_robolab bin_b03_vomp_robolab bin_b04_vomp_robolab grey_bin_robolab purple_crate storage_box_hot3d_robolab container_f24_vomp_robolab green_container red_container wooden_bowl_hot3d_robolab bowl_ycb_robolab \
  --out_dir /workspaces/isaaclab_arena/eval_output/asset_thumbnails \
  --image_size 512
```

### Generated Thumbnail Outputs:
All thumbnails are stored in [`eval_output/asset_thumbnails/`](../../../eval_output/asset_thumbnails/):
* `blue_sorting_bin.png` (*large blue plastic sorting bin*)
* `bin_a06_vomp_robolab.png` (*compact industrial bin*)
* `bin_b03_vomp_robolab.png` (*shallow plastic bin*)
* `bin_b04_vomp_robolab.png` (*medium sorting bin*)
* `grey_bin_robolab.png` (*compact grey plastic bin*)
* `purple_crate.png` (*KLT small industrial crate*)
* `storage_box_hot3d_robolab.png` (*HOT3D clear/grey storage box*)
* `container_f24_vomp_robolab.png` (*compact rectangular container*)
* `green_container.png` (*green stacking container*)
* `red_container.png` (*red stacking container*)
* `wooden_bowl_hot3d_robolab.png` (*wooden bowl receptacle*)
* `bowl_ycb_robolab.png` (*YCB ceramic bowl receptacle*)

---

## 2. All Registered Container & Bin Assets

| Asset Registry Name | Default Scale | Asset Type | Description / USD Origin |
| :--- | :--- | :--- | :--- |
| `blue_sorting_bin` | `(4.0, 2.0, 1.0)` | Rigid Object | Large blue plastic sorting bin (`Mimic/exhaust_pipe_task`) |
| `bin_a06_vomp_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | Compact square VOMP bin (`objects/vomp/bin_a06`) |
| `bin_b03_vomp_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | Shallow rectangular VOMP bin (`objects/vomp/bin_b03`) |
| `bin_b04_vomp_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | Medium VOMP bin (`objects/vomp/bin_b04`) |
| `grey_bin_robolab` | `(0.007, 0.007, 0.007)` | Fixture / Object | Compact grey RoboLab sorting bin (`fixtures/grey_bin`) |
| `purple_crate` | `(1.0, 1.0, 1.0)` | Rigid Object | Small European standard KLT bin (`KLT_Bin/small_KLT`) |
| `storage_box_hot3d_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | HOT3D dataset storage container (`objects/hot3d/storage_box`) |
| `container_f24_vomp_robolab` | `(0.25, 0.25, 0.25)` | Rigid Object | Compact container (`objects/vomp/container_f24`) |
| `green_container` | `(0.5, 0.5, 0.5)` | Rigid Object | Isaac Lab green container (`isaac_container/container_h20_green`) |
| `red_container` | `(0.5, 0.5, 0.5)` | Rigid Object | Isaac Lab red container (`isaac_container/container_h20_red`) |
| `wooden_bowl_hot3d_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | HOT3D wooden bowl (`objects/hot3d/wooden_bowl`) |
| `bowl_ycb_robolab` | `(1.0, 1.0, 1.0)` | Rigid Object | YCB ceramic bowl (`objects/ycb/bowl`) |

---

## 3. Swapping to a Naturally Smaller Container without Manual Scaling

Instead of manually scaling `blue_sorting_bin`, you can instruct the Active Inference agent to swap to one of the naturally compact registered containers (e.g. `bin_a06_vomp_robolab`, `bin_b03_vomp_robolab`, `grey_bin_robolab`, or `purple_crate`):

```bash
docker exec -it \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  isaaclab_arena-latest /isaac-sim/python.sh \
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \
  --mode resolve \
  --model "anthropic/claude-sonnet-4.5" \
  --base_spec /workspaces/isaaclab_arena/generated_envs/droid_rubiks_blue_bin/droid_pick_rubiks_cube_to_blue_bin.yaml \
  --feedback "Replace the large blue_sorting_bin with the compact bin_a06_vomp_robolab." \
  --out_dir /workspaces/isaaclab_arena/generated_envs/droid_rubiks_compact_bin
```
