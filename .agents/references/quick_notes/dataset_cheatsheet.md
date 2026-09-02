# Dataset Cheat Sheet: Conversion, LeRobot Format & Visualization

A comprehensive reference for teleoperation datasets in Isaac Lab-Arena: managing host vs. container paths, converting raw HDF5 teleop recordings to LeRobot format, and visualizing data using `rerun` and `lerobot-dataset-viz`.

---

## 1. Storage & Path Conventions (Host vs. Container)

The repository mounts local host NVMe directories directly into Docker containers:

| Environment | Datasets Root (`$DATASET_DIR`) | Models Root (`$MODELS_DIR`) | Repo Root |
| :--- | :--- | :--- | :--- |
| **Local Host** | `$HOME/datasets/isaaclab_arena/<tutorial>` | `$HOME/models/isaaclab_arena/<tutorial>` | `$HOME/.../IsaacLab-Arena` |
| **Sim Container** | `/datasets/isaaclab_arena/<tutorial>` | `/models/isaaclab_arena/<tutorial>` | `/workspaces/isaaclab_arena` |

### Static Apple Tutorial Dataset Hierarchy on Host
```text
$HOME/datasets/isaaclab_arena/static_apple_tutorial/
├── arena_g1_static_apple_dataset_recorded.hdf5            # Raw teleoperation recordings (9.4 GB, 251 demos)
├── episode_000.rrd                                        # Standalone Rerun recording for instant GUI inspection
├── lerobot/                                               # Pre-converted Hugging Face reference dataset (208 episodes)
│   ├── data/chunk-000/episode_*.parquet
│   ├── videos/chunk-000/observation.images.ego_view/episode_*.mp4
│   └── meta/ (info.json, tasks.jsonl, episodes.jsonl)
└── arena_g1_static_apple_dataset_recorded/                # Freshly converted dataset output
    └── lerobot/
        ├── data/chunk-000/episode_*.parquet               (208 files)
        ├── videos/chunk-000/observation.images.ego_view/  (208 mp4 videos)
        └── meta/ (info.json, tasks.jsonl, episodes.jsonl, modality.json)
```

---

## 2. Converting Raw HDF5 to LeRobot Format

### Why Conversion Is Needed
Raw demonstrations recorded via `record_demos.py` are packaged as monolithic HDF5 files containing joint arrays and uncompressed RGB image tensors. The **GR00T Foundation Policy** requires the **LeRobot format** (tabular parquet telemetry + compressed H.264 MP4 videos + task metadata).

### Exact Conversion Command
Run inside the simulation container as host user `tarfy`:

```bash
docker exec isaaclab_arena-latest su tarfy -c \
  "cd /workspaces/isaaclab_arena && /isaac-sim/python.sh isaaclab_arena_gr00t/lerobot/convert_hdf5_to_lerobot.py \
   --yaml_file isaaclab_arena_gr00t/lerobot/config/g1_static_apple_config.yaml"
```

### Configuration Anatomy (`g1_static_apple_config.yaml`)
* `data_root`: `/datasets/isaaclab_arena/static_apple_tutorial`
* `hdf5_name`: `arena_g1_static_apple_dataset_recorded.hdf5`
* `output_dir`: Automatically derived as `data_root / hdf5_name.replace(".hdf5", "") / lerobot/`
* `language_instruction`: `"move the apple to the plate"` (Task ID: `3`)
* `fps`: `50`
* Video encoding: 4 multiprocessing workers writing `h264` codec MP4s.

### Expected Conversion Telemetry
* **Input Raw Trajectories**: 251 sessions.
* **Output Converted Episodes**: **208 successful episodes** (35,066 total frames).
  *(43 teleop demonstrations that were aborted or invalid during human teleop are safely filtered out, matching NVIDIA's published dataset exactly).*
* **Total Conversion Time**: ~3.5 minutes on modern multi-core systems.

---

## 3. Visualizing with Standalone `rerun` (Fastest & Simplest)

### What It Does
* `rerun` is a standalone, compiled Rust visualizer.
* It directly opens pre-packaged **`.rrd`** (Rerun Recording Data) files with zero Python or PyTorch overhead ($< 100\text{ ms}$ launch time).

### Host Commands

#### A. Native Desktop GUI Window (Recommended)
```bash
uvx --from rerun-sdk rerun --port auto $HOME/datasets/isaaclab_arena/static_apple_tutorial/episode_000.rrd
```
> **Tip**: `--port auto` guarantees a fresh window opens instead of streaming into an orphaned background process on port `9876`.

#### B. In Your Web Browser (Chrome / Firefox)
```bash
uvx --from rerun-sdk rerun --web-viewer $HOME/datasets/isaaclab_arena/static_apple_tutorial/episode_000.rrd --renderer webgl
```
> **Tip**: `--renderer webgl` ensures hardware-accelerated canvas fallback if WebGPU is disabled in your browser.

---

## 4. Visualizing Any Episode (`lerobot-dataset-viz` & Custom Loader)

### The LeRobot Version Breaking Change (v2.1 vs. v3.0)
* **LeRobot v0.4+** introduced a breaking schema change to **v3.0** (`episodes.parquet`).
* NVIDIA's GR00T datasets (`nvidia/Arena-G1-Static-PickNPlace-Task`) are authored in **v2.1 format** (`episodes.jsonl` and individual episode videos).
* Direct `lerobot-dataset-viz` with modern packages raises a `BackwardCompatibilityError`.

### Universal Version-Agnostic Host Command
To visualize any episode (`0` through `207`) from either the reference dataset or your newly converted dataset:

#### Inspecting the Freshly Converted Dataset:
```bash
uv run --no-project --python 3.10 --with rerun-sdk --with pandas --with opencv-python --with pyarrow \
  python3 $HOME/Documents/GitHub/BoredEngineer/IsaacLab-Arena/isaaclab_arena_examples/tools/visualize_lerobot_dataset.py \
  --dataset-dir $HOME/datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded/lerobot \
  --episode-index 0
```

#### Inspecting the Hugging Face Downloaded Reference:
```bash
uv run --no-project --python 3.10 --with rerun-sdk --with pandas --with opencv-python --with pyarrow \
  python3 $HOME/Documents/GitHub/BoredEngineer/IsaacLab-Arena/isaaclab_arena_examples/tools/visualize_lerobot_dataset.py \
  --dataset-dir $HOME/datasets/isaaclab_arena/static_apple_tutorial/lerobot \
  --episode-index 0
```
*(Append `--web` if you prefer the browser UI over the native desktop window).*

---

## 5. Architectural Differences: `lerobot-dataset-viz` vs. `rerun`

| Feature | `lerobot-dataset-viz` | `rerun` |
| :--- | :--- | :--- |
| **Role** | **Data Loader / Transcoder** (Python) | **Visual Player / Renderer** (Rust) |
| **Input Format** | Raw LeRobot directory (`parquet` + `mp4` + `json`) | Pre-packaged `.rrd` recording |
| **Execution Engine** | Python interpreter, PyTorch, Pandas, LeRobot | Compiled native Rust + WGPU |
| **Dataset Strictness** | **High**: Fails if schema version (v2.1 vs v3.0) mismatches package | **Agnostic**: Plays any valid `.rrd` recording |
| **Startup Time** | 3–15 seconds (imports heavy Python packages) | $< 0.1$ seconds |
| **Primary Use** | Inspecting fresh datasets immediately after conversion | Daily visualization, debugging trajectories, sharing results |

---

## 6. Troubleshooting Common Issues

1. **Ruby `rerun` Gem Collision**:
   * *Symptom*: Terminal prints `13:51:00 [rerun] Tarfy launched ... Errno::EACCES`.
   * *Cause*: Host `PATH` is picking up the Ruby file-watcher gem named `rerun`.
   * *Fix*: Always invoke via `uvx --from rerun-sdk rerun ...`.

2. **"Address already in use (os error 98)" / Window Doesn't Open**:
   * *Symptom*: Logs state `Another viewer is already running, streaming data to it`, but no window appears.
   * *Cause*: An orphaned headless process is occupying port `9876`.
   * *Fix*: Clean ports via `pkill -9 -f rerun 2>/dev/null; fuser -k 9876/tcp 9090/tcp 2>/dev/null || true` or append `--port auto`.

3. **Browser Reports "Canvas / WebGL2 Not Available"**:
   * *Symptom*: `failed to create wgpu surface: canvas.getContext() returned null`.
   * *Fix*: Append `&renderer=webgl` to the URL or pass `--renderer webgl` on launch.

4. **File Permission Errors (`PermissionError: [Errno 13]`)**:
   * *Symptom*: Host cannot write or acquire lock files on datasets/models.
   * *Cause*: Docker root user created the files.
   * *Fix*: Run inside container: `chown -R 1000:1000 /datasets /models && chmod -R 775 /datasets /models`.

---

## 7. Depth-Anything Spatial Auditor (`depth_spatial_auditor.py`)

A built-in tool using **Depth Anything V2** to audit 3D spatial alignment between 2D RGB demonstration datasets and simulation camera views.

### How to Run

```bash
docker exec isaaclab_arena-latest /isaac-sim/python.sh \
  /workspaces/isaaclab_arena/isaaclab_arena_examples/tools/depth_spatial_auditor.py \
  --dataset-video /datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded/lerobot/videos/chunk-000/observation.images.ego_view/episode_000000.mp4 \
  --sim-frame /workspaces/isaaclab_arena/eval_output/g1_apple_to_plate/v6_kitchen_robot_view.png \
  --output-viz /workspaces/isaaclab_arena/eval_output/depth_spatial_comparison.png \
  --output-json /workspaces/isaaclab_arena/eval_output/depth_spatial_comparison.json
```

### Outputs
* **4-Panel Diagnostic Figure**: Side-by-side RGB and Inferno-colormap depth maps with bounding boxes, relative depth values, and surface slope metrics.
* **JSON Spatial Report**: Quantifies object distance delta ($\Delta D$), pixel position deltas ($\Delta X, \Delta Y$), and surface pitch slope ratios.
